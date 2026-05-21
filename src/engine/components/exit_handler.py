from src.domain.enums import TradeStatus
from src.domain.market_data import MarketSnapshot
from src.domain.trading import TradeResult, TradeExecution
from src.infrastructure.logger.data_logger import DataLogger
from src.infrastructure.logger.logger import log

def try_exit(
        bridge,
        position_manager, 
        risk_manager,
        strategy, 
        snapshot: MarketSnapshot,
        datalogger: DataLogger,
) -> bool:

    positions = position_manager.get_strategy_positions(snapshot.tick.symbol, strategy.strategy_id)

    for pos in positions:

        exit_signal = strategy.check_exit(
            pos, 
            snapshot
        )

        if not exit_signal:
            continue
        
        if exit_signal:
            exit_price = snapshot.tick.bid
            log(f"[EXIT] {pos.direction} at {exit_price}",level="INFO")
            
            result = bridge.close_position(pos)

            execution = TradeExecution(
                setup_id            = None,
                position_id         = result.position_id,
                order               = result.order,
                deal                = result.deal,
                fill_price          = result.fill_price,
                fill_volume         = result.fill_volume,
                fill_time           = result.fill_time,
                slippage            = abs(result.fill_price - exit_price),
                latency_ms          = result.latency_ms,
                status              = result.status,
            )
            # datalogger.log_trade_execution(execution)

            deals   = bridge.history_deals_get(ticket=result.deal)
            key     = position_manager._get_position_key(pos)
            meta    = position_manager._position_metadata.get(key, {})


            # ── Build and log TradeResult ──────────────────────────────────────
            trade_result = TradeResult (
                setup_id                = meta.get("setup_id"),
                position_id             = result.position_id,
                order                   = result.order,
                symbol                  = pos.symbol,
                volume                  = result.fill_volume,
                exit_price              = result.fill_price,
                exit_time               = result.fill_time,
                exit_reason             = "bollinger_exit",
                exit_bid                = snapshot.tick.bid,
                exit_ask                = snapshot.tick.ask,
                total_fees              = sum(d.fee + d.swap + d.commission for d in deals) if deals else 0.0,
                net_pnl                 = sum(d.profit for d in deals) if deals else 0.0,
                duration_minutes        = (result.fill_time - pos.time).total_seconds() / 60.0,
                risk_reward_ratio       = None,
                max_adverse_excursion   = meta.get('mae', 0.0),
                max_favorable_excursion = meta.get('mfe', 0.0),
                is_recovered            = False,
                status                  = TradeStatus.CLOSED
            )
            datalogger.log_trade_result(trade_result)

            risk_manager.update(trade_result)
            strategy.update_trade_result(trade_result)

            # Clean up metadata
            if key in position_manager._position_metadata:
                position_manager.remove_metadata(pos.ticket)

            continue
        return True
    return False