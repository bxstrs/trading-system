"""src/engine/forward.py"""
import signal
import time
import traceback
 
from src.core.exceptions import MarketDataUnavailable
from src.engine.components.entry_handler import try_entry
from src.engine.components.data_handler import build_market_state, fetch_data
from src.engine.trading_config import TradingConfig, load_trading_config
from src.engine.components.warmup import warmup_strategy
from src.execution.mt5_bridge import MT5Bridge
from src.domain.position_manager import PositionManager
from src.domain.risk_manager import RiskManager
from src.strategies.strategy_loader import load_strategy
from src.infrastructure.logger.data_logger import DataLogger
from src.infrastructure.logger.logger import log
from src.infrastructure.notifier.line_notifier import LineNotifier
from src.infrastructure.state.position_storage import PositionStorage
 
 
# ── Module-level singletons (config is frozen, position_storage is stateless) ───
_trading_config: TradingConfig = load_trading_config()
_position_storage: PositionStorage = PositionStorage()
_should_exit: bool = False
 
 
# ── Signal handling ───────────────────────────────────────────────────────────
 
def _signal_handler(signum, frame) -> None:
    global _should_exit
    _should_exit = True
    log(f"Received shutdown signal ({signum})", level="INFO")
 
# ── Core loop ─────────────────────────────────────────────────────────────────
 
def main_loop(strategy_name: str, notifier: LineNotifier) -> None:

    global _should_exit
    _should_exit = False
 
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
 
    # ── Bootstrap ─────────────────────────────────────────────────────
    bridge = MT5Bridge()
    try:
        bridge.connect()
    except Exception as exc:
        message = f"MT5 initialization failed: {exc}"
        log(message, level="ERROR")
        _notify(notifier, message)
        raise
 
    strategy = load_strategy(strategy_name)
    datalogger = DataLogger(strategy_id=strategy.strategy_id, symbol=_trading_config.symbol)
    position_manager = PositionManager(bridge, datalogger=datalogger)
    risk_manager = RiskManager()
    
    history, tick = fetch_data(bridge, _trading_config)

    log(f"Loaded strategy: {strategy.strategy_id}")
    _run_recovery(bridge, position_manager, strategy)
    warmup_strategy(strategy, history)
 
    # ── Loop state ────────────────────────────────────────────────────
    tick_counter = 0
    ticks_since_checkpoint = 0
    last_entry_bar_time = None
    current_bar_time = history["timestamp"][-1]
    last_fetch_time = time.time()
    loop_start = time.time()
    had_position = position_manager.has_open_position(_trading_config.symbol, strategy.strategy_id)
 
    try:
        while not _should_exit:
            tick_counter += 1
            ticks_since_checkpoint += 1
            iteration_start = time.time()
 
            # ── Periodic checkpoint ───────────────────────────────────
            if ticks_since_checkpoint >= _trading_config.checkpoint_interval:
                _save_checkpoint(position_manager, strategy)
                ticks_since_checkpoint = 0
 
            # ── Market data refresh ───────────────────────────────────
            if time.time() - last_fetch_time > _trading_config.rate_fetch_interval:

                history, tick = fetch_data(bridge, _trading_config)
                current_bar_time = history["timestamp"][-1]
                last_fetch_time = time.time()

                _heartbeat_logger(tick_counter, tick, current_bar_time)

            else:
                tick = bridge.get_tick(_trading_config.symbol)

                _heartbeat_logger(tick_counter, tick, current_bar_time)

            # ── Exit check ────────────────────────────────────────────
            current_state = build_market_state(history, tick, _trading_config, use_previous=False)
            position_manager.handle_exit(strategy, current_state, risk_manager)
 
            current_has_position = position_manager.has_open_position(
                _trading_config.symbol, strategy.strategy_id
            )
            if had_position and not current_has_position:
                log("[POSITION CLOSED] Blocking re-entry for current bar.", level="INFO")
                last_entry_bar_time = current_bar_time
 
            had_position = current_has_position
 
            # ── Entry attempt ─────────────────────────────────────────
            setup_state = build_market_state(history, tick, _trading_config, use_previous=True)
            spread = bridge.get_spread(_trading_config.symbol)
 
            executed, last_entry_bar_time = try_entry(
                bridge, position_manager, risk_manager, strategy,
                setup_state, history, spread,
                current_bar_time, last_entry_bar_time,
                datalogger, _trading_config,
            )
 
            if executed:
                had_position = True
                log(f"Signal executed in {time.time() - iteration_start:.3f}s")
 
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
        _save_checkpoint(position_manager, strategy)
        datalogger.close()
        bridge.shutdown()
        elapsed = time.time() - loop_start
        log(
            f"Stopped. Processed {tick_counter} ticks in {elapsed:.1f}s "
            f"({tick_counter / elapsed:.1f} ticks/sec)",
            level="INFO",
        )
 
 
# ── Restart wrapper ───────────────────────────────────────────────────────────
 
def run_forward(strategy_name: str = "bb_squeeze") -> None:

    notifier = LineNotifier()
    attempt = 0
 
    while _trading_config.max_restart_attempts < 0 or attempt < _trading_config.max_restart_attempts:
        attempt += 1
        try:
            main_loop(strategy_name, notifier)
            break  # Clean exit — don't restart
        except KeyboardInterrupt:
            log("Forward runner stopped by user", level="INFO")
            break
        except Exception as exc:
            message = (
                f"Forward runner crashed on attempt {attempt}: {exc}. "
                f"Restarting in {_trading_config.restart_delay}s."
            )
            log(message, level="ERROR")
            _notify(notifier, message)
            traceback.print_exc()
 
            if _trading_config.max_restart_attempts >= 0 and attempt >= _trading_config.max_restart_attempts:
                log("Reached max restart attempts, exiting", level="ERROR")
                break
 
            time.sleep(_trading_config.restart_delay)
 
    log("Forward runner exiting", level="INFO")

# ── Private helpers ───────────────────────────────────────────────────────────
 
def _notify(notifier: LineNotifier, message: str) -> None:
    """Send a LINE notification if the notifier is configured."""
    if notifier and notifier.enabled:
        notifier.notify(message)
 
def _save_checkpoint(position_manager: PositionManager, strategy) -> None:
    """Persist current open positions to disk for crash recovery."""
    positions = position_manager.get_strategy_positions(
        _trading_config.symbol, strategy.strategy_id
    )
    _position_storage.save_positions(
        [pos for pos, _ in positions],
        strategy_id = strategy.strategy_id,
        metadata = position_manager.export_metadata(),
    )
 
def _run_recovery(
    bridge,
    position_manager: PositionManager,
    strategy,
) -> None:
    checkpoint_data = _position_storage.load_positions(strategy.strategy_id)

    if not checkpoint_data:
        return

    # restore metadata
    position_manager.load_metadata(checkpoint_data.get("metadata", {}))

    live_positions = bridge.get_positions(_trading_config.symbol)

    position_manager.reconcile(
        live_positions,
        checkpoint_data,
        _position_storage
    )

def _heartbeat_logger(counter, tick, current_bar_time=None):

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
            f"[TICK {counter}] "
            f"Bid: {tick.bid:.5f}, Ask: {tick.ask:.5f}",
            level="INFO",
        )
 