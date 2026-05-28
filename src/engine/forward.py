import signal
import time
import traceback
import os

from src.brokers.mt5                            import MT5Bridge
from src.domain.exceptions                      import MarketDataUnavailable
from src.engine.components.data_handler         import fetch_full_market_data, get_market_snapshot
from src.engine.components.entry_handler        import try_entry, resolve_pending_intents
from src.engine.components.exit_handler         import try_exit
from src.engine.components.reconcile_handler    import check_manual_closes
from src.engine.components.trading_config       import TradingConfig, load_trading_config
from src.engine.components.warmup               import warmup_strategy
from src.engine.components.position_manager     import PositionManager
from src.engine.components.risk_manager         import RiskManager
from src.strategies.strategy_loader             import load_strategy
from src.infrastructure.logger.data_logger      import DataLogger
from src.infrastructure.logger.logger           import log
from src.infrastructure.notifier.line_notifier  import LineNotifier
from src.infrastructure.state.position_storage  import PositionStorage
from src.infrastructure.state.intent_storage      import IntentStore


# ── Module-level singletons ───────────────────────────────────────────────────
# NOTE: These fire at import time. A future refactor should move them into
# run_forward() to support multi-strategy and make unit tests import-safe.

_trading_config: TradingConfig  = load_trading_config()
_position_storage: PositionStorage = PositionStorage()
_should_exit: bool = False
# ── Async-signal-safe shutdown pipe ─────────────────────
_shutdown_r, _shutdown_w = os.pipe()
os.set_blocking(_shutdown_r, False)


# ── Signal handling ───────────────────────────────────────────────────────────

def _signal_handler(signum, frame) -> None:
    # async-signal-safe: ONLY os.write allowed
    try:
        os.write(_shutdown_w, b"X")
    except OSError:
        pass

# ── Core loop ─────────────────────────────────────────────────────────────────

def main_loop(strategy_name: str, notifier: LineNotifier) -> None:

    global _should_exit

    while True:
        try:
            os.read(_shutdown_r, 1)
        except BlockingIOError:
            break

    _should_exit = False

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT,  _signal_handler)

    # ── Bootstrap ─────────────────────────────────────────────────────
    bridge = MT5Bridge()
    try:
        bridge.connect()
    except Exception as exc:
        message = f"MT5 initialization failed: {exc}"
        log(message, level="ERROR")
        _notify(notifier, message)
        raise

    strategy         = load_strategy(strategy_name)
    datalogger       = DataLogger(strategy_id=strategy.strategy_id, symbol=_trading_config.symbol)
    intent_store     = IntentStore()                                
    position_manager = PositionManager(bridge, datalogger=datalogger)
    risk_manager     = RiskManager()

    history, tick = fetch_full_market_data(bridge, _trading_config)

    log(f"Loaded strategy: {strategy.strategy_id}")

    # ── Recovery sequence (order matters) ─────────────────────────────
    # 1. Load checkpoint + restore metadata + risk state
    _run_recovery(bridge, position_manager, strategy, risk_manager)
    # 2. Resolve any PENDING intents left by previous crash
    #    Must run BEFORE warmup so metadata is complete before indicators run
    resolve_pending_intents(intent_store, bridge, position_manager, _trading_config, strategy)
    # 3. Warm up strategy indicators
    warmup_strategy(strategy, history)

    # ── Loop state ────────────────────────────────────────────────────
    tick_counter           = 0
    ticks_since_checkpoint = 0
    last_entry_bar_time    = None
    current_bar_time       = history.time_unix[-1]
    last_fetch_time        = time.time()
    last_flush_time        = time.time()
    loop_start             = time.time()
    had_position           = position_manager.has_open_position(
        _trading_config.symbol, strategy.magic_number
    )

    try:
        while True:
            # ── async shutdown check (pipe) ─────────────────────────
            try:
                os.read(_shutdown_r, 1)
                _should_exit = True
            except BlockingIOError:
                pass

            if _should_exit:
                break

            tick_counter           += 1
            ticks_since_checkpoint += 1
            iteration_start = time.time()
            entry_executed  = False

            # ── Refresh position cache ────────────────────────────────
            position_manager.refresh_cache(_trading_config.symbol)

            # ── Periodic checkpoint (interval-based) ──────────────────
            if ticks_since_checkpoint >= _trading_config.checkpoint_interval:
                _save_checkpoint(position_manager, risk_manager, strategy) 
                ticks_since_checkpoint = 0

            # ── Periodic abandoned-row flush ──────────────────────────
            # Prevents unbounded _pending_rows cache growth on rejected setups
            if time.time() - last_flush_time > 3600:
                datalogger.flush_abandoned_rows()
                intent_store.cleanup_old(max_age_seconds=86_400)
                last_flush_time = time.time()

            # ── Market data refresh ───────────────────────────────────
            if time.time() - last_fetch_time > _trading_config.rate_fetch_interval:
                snapshot = get_market_snapshot(bridge, _trading_config, force_full=True)
                if snapshot.history:
                    current_bar_time = snapshot.history.time_unix[-1]
                last_fetch_time = time.time()
                _heartbeat_logger(tick_counter, snapshot.tick, current_bar_time)
            else:
                snapshot = get_market_snapshot(bridge, _trading_config, force_full=False)
                _heartbeat_logger(tick_counter, snapshot.tick, current_bar_time)

            if snapshot.history and current_bar_time != strategy._current_bar_time:
                strategy.update_indicators(snapshot.history)
                strategy._current_bar_time = current_bar_time

            # ── MAE/MFE update — every tick ──────────────────────────
            for pos in position_manager.get_strategy_positions(
                _trading_config.symbol, strategy.magic_number
            ):
                position_manager._update_mae_mfe(snapshot.tick, pos)

            # ── Manual-close detection ────────────────────────────────
            reconciled = check_manual_closes(
                bridge, position_manager, risk_manager,
                strategy, snapshot, datalogger, _trading_config,
            )
            if reconciled > 0:
                _save_checkpoint(position_manager, risk_manager, strategy)
                ticks_since_checkpoint = 0

            # ── Exit check ────────────────────────────────────────────
            exit_executed = try_exit(
                bridge, position_manager, risk_manager,
                strategy, snapshot, datalogger,
            )
            if exit_executed:
                # Bug #2 fix: checkpoint immediately after close
                _save_checkpoint(position_manager, risk_manager, strategy)
                ticks_since_checkpoint = 0

            # ── Detect position just closed → block re-entry this bar ──
            current_has_position = position_manager.has_open_position(
                _trading_config.symbol, strategy.magic_number
            )
            if had_position and not current_has_position:
                log("[POSITION CLOSED] Blocking re-entry for current bar.", level="INFO")
                last_entry_bar_time = current_bar_time

            had_position = current_has_position

            # ── Entry attempt ─────────────────────────────────────────

            if not had_position and last_entry_bar_time != current_bar_time:
                spread = bridge.get_spread(_trading_config.symbol)
                entry_executed = try_entry(
                    bridge,
                    position_manager,
                    risk_manager,
                    strategy,
                    snapshot,
                    spread,
                    datalogger,
                    _trading_config,
                    intent_store,                                    
                )

            if entry_executed:
                had_position        = True
                last_entry_bar_time = current_bar_time
                _save_checkpoint(position_manager, risk_manager, strategy)
                ticks_since_checkpoint = 0
                log(f"[ENTRY] Signal executed in {time.time() - iteration_start:.3f}s")

            time.sleep(_trading_config.tick_sleep)

    except KeyboardInterrupt:
        log("Stopped by user", level="INFO")

    except MarketDataUnavailable as exc:
        message = f"Market data unavailable: {exc}"
        log(message, level="ERROR")
        _notify(notifier, message)
        raise

    except Exception as exc:
        message = f"Unhandled exception in forward loop: {exc}"
        log(message, level="ERROR")
        _notify(notifier, message)
        traceback.print_exc()
        raise

    finally:
        log("Graceful shutdown: saving state and closing resources", level="INFO")
        if 'position_manager' in dir() and 'risk_manager' in dir() and 'strategy' in dir():
            _save_checkpoint(position_manager, risk_manager, strategy)
        if 'datalogger' in dir():
            datalogger.close(clean_exit=_should_exit)
        bridge.shutdown()
        if 'loop_start' in dir() and 'tick_counter' in dir():
            elapsed = time.time() - loop_start
            log(
                f"Stopped. Processed {tick_counter} ticks in {elapsed:.1f}s "
                f"({tick_counter / elapsed:.1f} ticks/sec)",
                level="INFO",
            )

# ── Restart wrapper ───────────────────────────────────────────────────────────

def run_forward(strategy_name: str = "bb_squeeze") -> None:

    notifier = LineNotifier()
    attempt  = 0

    try:
        while (
            _trading_config.max_restart_attempts < 0
            or attempt < _trading_config.max_restart_attempts
        ):
            attempt += 1
            try:
                main_loop(strategy_name, notifier)
                break  # clean exit — don't restart
            except KeyboardInterrupt:
                log("Forward runner stopped by user", level="INFO")
                break
            except Exception as exc:
                message = (
                    f"Forward runner crashed (attempt {attempt}): {exc}. "
                    f"Restarting in {_trading_config.restart_delay}s."
                )
                log(message, level="ERROR")
                _notify(notifier, message)
                traceback.print_exc()

                if (
                    _trading_config.max_restart_attempts >= 0
                    and attempt >= _trading_config.max_restart_attempts
                ):
                    log("Reached max restart attempts, exiting", level="ERROR")
                    break

                time.sleep(_trading_config.restart_delay)

    finally:
        for fd in (_shutdown_r, _shutdown_w):
            try:
                os.close(fd)
            except OSError:
                pass

    log("Forward runner exiting", level="INFO")


# ── Private helpers ───────────────────────────────────────────────────────────

def _notify(notifier: LineNotifier, message: str) -> None:
    if notifier and notifier.enabled:
        notifier.notify(message)


def _save_checkpoint(
    position_manager: PositionManager,
    risk_manager:     RiskManager,          
    strategy,
) -> None:

    positions = position_manager.get_strategy_positions(
        _trading_config.symbol,
        strategy.magic_number,
    )

    _position_storage.save_positions(
        positions,
        strategy_id = strategy.strategy_id,
        metadata    = position_manager.serialize_metadata(),
        risk_state  = risk_manager.save_state(),    
        strategy_state = getattr(strategy, "save_state", lambda: {})(),
    )


def _run_recovery(
    bridge,
    position_manager: PositionManager,
    strategy,
    risk_manager:     RiskManager,
) -> None:
    """
    On startup, reload checkpoint state:
      1. Position metadata (MAE/MFE, setup_id, fill times)
      2. Risk state (consecutive_losses, trading_halted)   ← Bug #8A fix
    """
    checkpoint_data = _position_storage.load_positions(strategy.strategy_id)

    if not checkpoint_data:
        log("[RECOVERY] No checkpoint found — starting fresh", level="INFO")
        return

    # ── Restore position metadata ──────────────────────────────────────
    position_manager.load_metadata(
        PositionManager.deserialize_metadata(
            checkpoint_data.get("metadata", {})
        )
    )

    # ── Reconcile against live MT5 positions ───────────────────────────
    live_positions = bridge.get_positions(_trading_config.symbol)
    position_manager.reconcile(live_positions, checkpoint_data, _position_storage)

    risk_state = checkpoint_data.get("risk_state", {})
    risk_manager.restore_state(risk_state)
    
    if hasattr(strategy, "restore_state"):
        strategy.restore_state(checkpoint_data.get("strategy_state", {}))


def _heartbeat_logger(counter: int, tick, current_bar_time=None) -> None:
    if counter % 100 != 0:
        return
    if current_bar_time:
        log(
            f"[TICK {counter}] Bar: {current_bar_time}, "
            f"Bid: {tick.bid:.5f}, Ask: {tick.ask:.5f}",
            level="INFO",
        )
    else:
        log(
            f"[TICK {counter}] Bid: {tick.bid:.5f}, Ask: {tick.ask:.5f}",
            level="INFO",
        )