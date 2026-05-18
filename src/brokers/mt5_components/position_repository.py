"""MT5 Position queries - handles position and deal lookups."""
import MetaTrader5 as mt5
from datetime import datetime, timezone

from src.domain.enums import Direction
from src.domain.trading import Position, TradeHistory
from src.infrastructure.logger.logger import log


class PositionRepository:
    """Queries and retrieves position/deal information."""

    def __init__(self, connection_manager):
        self.connection_manager = connection_manager

    def get_positions(self, symbol: str) -> Position:

        if not self.connection_manager.ensure_connected():
            raise ConnectionError("Not connected to MT5")

        raw_position = mt5.positions_get(symbol=symbol)
        direction = (
            Direction.LONG
            if raw_position.type == mt5.POSITION_TYPE_BUY
            else Direction.SHORT
        )
        
        return Position(
            ticket      = raw_position.ticket,
            time        = datetime.fromtimestamp(raw_position.time, tz=timezone.utc),
            symbol      = raw_position.symbol,
            direction   = direction,
            volume      = raw_position.volumn,
            sl          = raw_position.sl,
            tp          = raw_position.tp,
            open_price  = raw_position.price_open,
        )

    def history_deals_get(self, ticket) -> TradeHistory:

        if not self.connection_manager.ensure_connected():
            raise ConnectionError("Not connected to MT5")
        
        trade_history = mt5.history_deals_get(ticket=ticket)

        return TradeHistory(
            ticket      = trade_history.ticket,
            position_id = trade_history.position_id,
            symbol      = trade_history.symbol,
            timestamp   = datetime.fromtimestamp(trade_history.time, tz=timezone.utc),
            volume      = trade_history.volume,
            price       = trade_history.price,
            commission  = trade_history.commission,
            swap        = trade_history.swap,
            profit      = trade_history.profit,
            fee         = trade_history.fee,
        )
