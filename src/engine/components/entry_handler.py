"""src/engine/entry_handler.py
 
Handles the full trade entry lifecycle:
  1. Pre-entry guards (risk limits, open position, bar dedup)
  2. Signal generation
  3. TradeSetup logging
  4. Order submission to MT5
  5. TradeExecution logging
  6. Position metadata registration
 
Extracted from forward.py so the logic can be read, tested, and modified
without touching the main loop orchestration.
"""
import uuid
from datetime   import datetime, timezone

from src.domain.enums                           import Direction, ExecutionStatus
from src.domain.market_data                     import MarketSnapshot
from src.domain.trading                         import TradeExecution, TradeSetup
from src.engine.components.trading_config       import TradingConfig
from src.infrastructure.logger.data_logger      import DataLogger
from src.infrastructure.logger.logger           import log
from src.infrastructure.state.intant_storage    import IntentStore
 
 
def try_entry(
    bridge,
    position_manager,
    risk_manager,
    strategy,
    snapshot: MarketSnapshot,
    spread: float,
    datalogger: DataLogger,
    config: TradingConfig,
    intent_store: IntentStore
) -> bool:

    # ── Pre-entry guards ──────────────────────────────────────────────
    if not risk_manager.can_trade():
        return False
 
    if position_manager.has_open_position(config.symbol, strategy.strategy_id):
        return False
 
    # ── Signal generation ─────────────────────────────────────────────
    signal = strategy.generate_signal(
        snapshot,
        spread,
    )
 
    if not signal:
        return False 
    
    direction_enum = Direction.LONG if signal.direction.name == "LONG" else Direction.SHORT
    log(f"[ENTRY] {signal.direction} at expected price: {signal.entry_price}", level="INFO")

    # ── Resolve setup-bar OHLC (history[-2] = the bar that triggered the setup) ──
    history          = snapshot.history
    setup_id         = str(uuid.uuid4())
    indicators_value = _get_indicator_values(strategy)

    if history is None:
        return False
    else:
        setup_open  = history.open[-2]
        setup_high  = history.high[-2]
        setup_low   = history.low[-2]
        setup_close = history.close[-2]
        setup_timestamp = datetime.fromtimestamp(history.time_unix[-2], tz=timezone.utc)
 
    # ── Build and log TradeSetup ──────────────────────────────────────
        setup = TradeSetup(
            setup_id                = setup_id,
            strategy_id             = strategy.strategy_id,
            symbol                  = config.symbol,
            timestamp               = setup_timestamp,
            direction               = direction_enum,
            trigger_price           = signal.entry_price,
            bb_upper                = indicators_value.get("bb_upper", 0.0),
            bb_lower                = indicators_value.get("bb_lower", 0.0),
            bb_middle               = indicators_value.get("bb_middle", 0.0),
            bandwidth               = indicators_value.get("bandwidth", 0.0),
            bandwidth_ma            = indicators_value.get("bandwidth_ma", 0.0),
            atr                     = indicators_value.get("atr", 0.0),
            spread                  = spread,
            intended_entry_price    = signal.entry_price,
            intended_volume         = config.base_volume,
            hour_of_day             = setup_timestamp.hour,
            candle_open             = setup_open,
            candle_high             = setup_high,
            candle_low              = setup_low,
            candle_close            = setup_close,
            prev_trade_pnl          = None,
            adaptive_filter_active  = indicators_value.get("adaptive_filter_active", False),
        )
        datalogger.log_trade_setup(setup)

    # ── WRITE INTENT BEFORE TOUCHING BROKER (crash safety) ───────────
    # If we crash between here and track_entry_position(), the PENDING intent will be found on restart and resolved against live positions.
    if not intent_store.write_pending(setup_id, setup):
        log(
            "[ENTRY] Could not write intent record — aborting entry to prevent "
            "untracked position on crash",
            level="ERROR",
        )
        return False
 
    # ── Submit order ──────────────────────────────────────────────────
    result = bridge.send_order(
        setup       = setup,
        volume      = config.base_volume,
        magic       = strategy.magic_number,
        comment     = strategy.strategy_id,
    )
 
    if result is None:
        intent_store.mark_abandoned(setup_id, reason="no response from MT5")
        log("Order failed: no response from MT5", level="ERROR")
        return False
 
    if result.status != ExecutionStatus.DONE:
        reason = f"retcode={result.status}, comment={getattr(result, 'comment', 'N/A')}"
        intent_store.mark_abandoned(setup_id, reason=reason)
        log(
            f"Order failed: retcode={result.status}, comment={getattr(result, 'comment', 'N/A')}",
            level="ERROR",
        )
        return False
    
    # ── Mark intent FILLED (idempotent — safe if called again on retry) ──
    intent_store.mark_filled(setup_id, position_id=result.position_id)
 
    # ── Log execution and register position ───────────────────────────
    execution = TradeExecution(
        position_id         = result.position_id,
        setup_id            = setup_id,
        order               = result.order,          
        deal                = result.deal,
        fill_price          = result.fill_price,
        fill_volume         = result.fill_volume,
        fill_time           = result.fill_time,
        slippage            = abs(result.fill_price - signal.entry_price),
        latency_ms          = result.latency_ms,
        status              = result.status,
    )
    datalogger.log_trade_execution(execution)
 
    position_manager.track_entry_position(
        setup_id            = setup_id,
        position_ticket     = result.position_id,
        entry_slippage      = execution.slippage,
        entry_latency_ms    = execution.latency_ms,
    )
    return True

def resolve_pending_intents(
    intent_store:     IntentStore,
    bridge,
    position_manager,
    config,
    strategy,
) -> None:
    """
    Called ONCE at startup, BEFORE warmup, AFTER load_positions().
 
    Resolves PENDING intents left by a crash in the window between
    order_send() and track_entry_position().
 
    Two cases:
      A) MT5 has a matching position → fill succeeded, register metadata.
      B) No matching MT5 position    → fill never happened, mark abandoned.
    """
    
    pending = intent_store.get_pending_intents()
    if not pending:
        return
 
    log(
        f"[INTENT] {len(pending)} PENDING intent(s) found — resolving before warmup",
        level="WARNING",
    )
 
    try:
        live_positions = bridge.get_positions(config.symbol)
    except Exception as exc:
        log(f"[INTENT] Cannot fetch positions for intent resolution: {exc}", level="ERROR")
        return
 
    # Build lookup: tickets that are already tracked (restored from checkpoint)
    already_tracked = set(position_manager._position_metadata.keys())
 
    for intent in pending:
        intent_id = intent["intent_id"]
        setup_id  = intent.get("setup_id", intent_id)
 
        log(f"[INTENT] Resolving intent={intent_id} setup={setup_id}", level="WARNING")
 
        # Find a live position with our magic number that has no metadata yet
        matched = None
        for pos in live_positions:
            if (
                pos.magic == strategy.magic_number
                and int(pos.ticket) not in already_tracked
            ):
                matched = pos
                break
 
        if matched is not None:
            log(
                f"[INTENT] Case A: fill confirmed → ticket={matched.ticket}. "
                f"Registering metadata.",
                level="WARNING",
            )
            intent_store.mark_filled(intent_id, position_id=matched.ticket)
            position_manager.track_entry_position(
                setup_id         = setup_id,
                position_ticket  = matched.ticket,
                entry_slippage   = 0.0,           # unknown after crash
                entry_latency_ms = 0.0,           # unknown after crash
                entry_fill_price = matched.open_price,
                entry_fill_time  = matched.time,
            )
            already_tracked.add(int(matched.ticket))
            log(f"[INTENT] Recovered position ticket={matched.ticket}", level="INFO")
        else:
            log(
                f"[INTENT] Case B: no matching live position for intent={intent_id} "
                f"— order never filled, marking ABANDONED",
                level="WARNING",
            )
            intent_store.mark_abandoned(
                intent_id,
                reason="no matching live position found on startup recovery",
            )
 
 
# ── Private helpers ───────────────────────────────────────────────────────────
 
def _get_indicator_values(strategy) -> dict:
    """Safely retrieve indicator snapshot from strategy, return {} on failure."""
    if not hasattr(strategy, "expose_indicator_values"):
        return {}
    try:
        return strategy.expose_indicator_values() or {}
    except Exception as exc:
        log(f"Failed to fetch strategy indicator values: {exc}", level="WARNING")
        return {}
