"""MT5 Order execution - handles sending and closing trades."""
import time
import MetaTrader5 as mt5
import uuid

from datetime                                   import datetime, timezone
from src.domain.enums                           import Direction, ExecutionStatus
from src.domain.trading                         import TradeSetup, TradeExecution
from src.brokers.mt5_components.retcode_mapper  import map_retcode
from src.infrastructure.logger.logger           import log

#==================================
# APPLY THIS LATER
#==================================
# RETRYABLE_STATUSES = {
#    ExecutionStatus.REQUOTE,
#    ExecutionStatus.PRICE_CHANGED,
#    ExecutionStatus.TIMEOUT,
# }
#==================================

class OrderExecutor:
    def __init__(self, data_fetcher):
        self.data_fetcher = data_fetcher

    def send_order(self, setup: TradeSetup, volume: float, magic: int, comment: str = "forward_test", max_retries: int = 3) -> TradeExecution | None:
        
        tick = self.data_fetcher.get_tick(setup.symbol)

        if setup.direction == Direction.LONG:
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        elif setup.direction == Direction.SHORT:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            raise ValueError(f"Unsupported direction: {setup.direction}")

        request = self._build_order_request(
            symbol      = setup.symbol,
            order_type  = order_type,
            volume      = volume,
            price       = price,
            magic       = magic,
            comment     = comment
        )

        # Retry logic with exponential backoff
        for attempt in range(1, max_retries + 1):
            try:
                begin_time = datetime.now(timezone.utc).second
                result = mt5.order_send(request)
                status = map_retcode(result.retcode)

                if result and status == ExecutionStatus.DONE:
                    fill_time = datetime.now(timezone.utc)
                    log(f"Order success (attempt {attempt}): {result}", level="INFO")
                    return TradeExecution(
                            setup_id            = setup.setup_id,
                            position_id         = result.position,
                            fill_price          = result.price,
                            fill_volume         = result.volume,
                            fill_time           = fill_time,
                            slippage            = abs(result.price - price),
                            latency_ms          = (begin_time - fill_time.second) / 1000,
                            status              = ExecutionStatus.DONE,
                    )
                else:
                    error_msg = f"Order failed with retcode {result.retcode}: {getattr(result, 'comment', 'N/A')}"
                    log(error_msg, level="WARNING")

                    if attempt < max_retries:
                        # Exponential backoff: [0.5, 1.0, 2.0] seconds
                        backoff = 0.5 * (2 ** (attempt - 1))
                        log(f"Retrying order in {backoff}s (attempt {attempt}/{max_retries})...", level="INFO")
                        time.sleep(backoff)
                    else:
                        log(f"Order failed after {max_retries} attempts", level="ERROR")
                        return result

            except Exception as e:
                log(f"Order send exception (attempt {attempt}): {e}", level="ERROR")
                if attempt < max_retries:
                    backoff = 0.5 * (2 ** (attempt - 1))
                    log(f"Retrying order in {backoff}s (attempt {attempt}/{max_retries})...", level="INFO")
                    time.sleep(backoff)
                else:
                    return None

        return None

    def close_position(self, position, max_retries: int = 3) -> TradeExecution | None:

        tick = self.data_fetcher.get_tick(position.symbol)

        if position.type == mt5.POSITION_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask

        request = self._build_order_request(
            symbol          = position.symbol,
            order_type      = order_type,
            volume          = position.volume,
            price           = price,
            magic           = position.magic,
            comment         = "close",
            position_ticket = position.ticket
        )

        for attempt in range(1, max_retries + 1):
            try:
                begin_time = datetime.now(timezone.utc).second
                result = mt5.order_send(request)
                status = map_retcode(result.retcode)

                if result and status == ExecutionStatus.DONE:
                    fill_time = datetime.now(timezone.utc)
                    log(f"Order success (attempt {attempt}): {result}", level="INFO")
                    return TradeExecution(
                            setup_id            = None,
                            position_id         = result.position,
                            fill_price          = result.price,
                            fill_volume         = result.volume,
                            fill_time           = fill_time,
                            slippage            = abs(result.price - price),
                            latency_ms          = (begin_time - fill_time.second) / 1000,
                            status              = ExecutionStatus.DONE,
                    )
                else:
                    error_msg = f"Order failed with retcode {result.retcode}: {getattr(result, 'comment', 'N/A')}"
                    log(error_msg, level="WARNING")

                    if attempt < max_retries:
                        # Exponential backoff: [0.5, 1.0, 2.0] seconds
                        backoff = 0.5 * (2 ** (attempt - 1))
                        log(f"Retrying order in {backoff}s (attempt {attempt}/{max_retries})...", level="INFO")
                        time.sleep(backoff)
                    else:
                        log(f"Order failed after {max_retries} attempts", level="ERROR")
                        return result

            except Exception as e:
                log(f"Order send exception (attempt {attempt}): {e}", level="ERROR")
                if attempt < max_retries:
                    backoff = 0.5 * (2 ** (attempt - 1))
                    log(f"Retrying order in {backoff}s (attempt {attempt}/{max_retries})...", level="INFO")
                    time.sleep(backoff)
                else:
                    return None

        return None
    
    # ── Private helpers ───────────────────────────────────────────────────────────

    def _build_order_request(self, symbol: str, order_type: int, volume: float, price: float, magic: int, comment: str, position_ticket: int | None = None) -> dict:

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       volume,
            "type":         order_type,
            "price":        price,
            "deviation":    10,
            "magic":        magic,
            "comment":      comment,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        if position_ticket is not None:
            request["position"] = position_ticket

        return request
