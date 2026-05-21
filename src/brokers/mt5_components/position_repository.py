"""MT5 Position queries - handles position and deal lookups."""
import MetaTrader5 as mt5

from typing import List
from datetime import datetime, timezone, timedelta
from src.domain.enums import Direction
from src.domain.trading import Position, TradeHistory
from src.infrastructure.logger.logger import log


class PositionRepository:
    """Queries and retrieves position/deal information."""

    def __init__(self, connection_manager):
        self.connection_manager = connection_manager

    def get_positions(self, symbol: str) -> List[Position]:

        if not self.connection_manager.ensure_connected():
            raise ConnectionError("Not connected to MT5")

        raw_positions = mt5.positions_get(symbol=symbol)

        if not raw_positions:
            return []
        
        result = []
        for raw_position in raw_positions:
            direction = (
                Direction.LONG
                if raw_position.type == mt5.POSITION_TYPE_BUY
                else Direction.SHORT
            )
            pos = Position(
                ticket      = raw_position.ticket,
                magic       = raw_position.magic,
                time        = datetime.fromtimestamp(raw_position.time, tz=timezone.utc),
                symbol      = raw_position.symbol,
                direction   = direction,
                volume      = raw_position.volume,
                sl          = raw_position.sl,
                tp          = raw_position.tp,
                open_price  = raw_position.price_open,
                profit      = raw_position.profit,
                comment     = raw_position.comment,
            )
            result.append(pos)
        return result

    def history_deals_get(self, ticket) -> List[TradeHistory]:

        if not self.connection_manager.ensure_connected():
            raise ConnectionError("Not connected to MT5")
        
        histories = mt5.history_deals_get(ticket=ticket)

        if not histories:
            return []
        
        result = []
        for trade_history in histories:
            history = TradeHistory(
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
            result.append(history)
        return result
    
    def history_deals_get_by_position(self, position_id: int) -> List[TradeHistory]:

        if not self.connection_manager.ensure_connected():
            raise ConnectionError("Not connected to MT5")
        
        date_from = datetime(2000, 1, 1, tzinfo=timezone.utc)
        date_to   = datetime.now(timezone.utc) + timedelta(days=1)

        histories = mt5.history_deals_get(
            date_from, date_to, position = position_id
        )

        if not histories:
            return []

        result = []
        for trade_history in histories:
            history = TradeHistory(
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
            result.append(history)
        return result

