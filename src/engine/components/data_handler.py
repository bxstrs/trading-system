"""src/engine/marketstate_builder.py

Handles all market data retrieval and construction of MarketState objects.
Isolated here so the main loop stays free of data-plumbing details,
and so these functions can be tested independently.
"""
import time
from datetime import datetime, timezone

from typing import Tuple
from src.core.types import MarketState, TickData
from src.core.exceptions import MarketDataUnavailable
from src.engine.trading_config import TradingConfig
from src.infrastructure.logger.logger import log


def fetch_data(
    bridge,
    config: TradingConfig,
) -> Tuple[dict, TickData]:

    for attempt in range(config.max_fetch_attempts):

        try:
            bridge.ensure_connected()
            history = bridge.get_rates(config.symbol, config.timeframe_value, config.bar_lookback)
            tick = bridge.get_tick(config.symbol)

            return history, tick
        
        except MarketDataUnavailable as exc:
            log(
                f"Market data fetch failed "
                f"({attempt + 1}/{config.max_fetch_attempts}): {exc}",
                level="WARNING",
            )

        time.sleep(config.tick_sleep)

    raise MarketDataUnavailable(
        f"Failed after {config.max_fetch_attempts} attempts"
    )


def build_market_state(
    history: dict,
    tick,
    config: TradingConfig,
    use_previous: bool = False,
) -> MarketState:

    idx = -2 if use_previous else -1

    if not history or not history.get("timestamp") or len(history["timestamp"]) < abs(idx):
        raise ValueError(
            f"Insufficient history: got {len(history.get('timestamp', []))} bars, "
            f"need at least {abs(idx)}"
        )

    if tick is None or tick.bid is None or tick.ask is None:
        raise ValueError(
            f"Invalid tick data: bid={getattr(tick, 'bid', None)}, "
            f"ask={getattr(tick, 'ask', None)}"
        )

    return MarketState(
        symbol=config.symbol,
        interval=config.timeframe,
        timestamp=datetime.fromtimestamp(history["timestamp"][idx], tz=timezone.utc),
        open=history["open"][idx],
        high=history["high"][idx],
        low=history["low"][idx],
        close=history["close"][idx],
        bid=tick.bid,
        ask=tick.ask,
    )
