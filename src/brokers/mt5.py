from typing import List
from src.domain.market_data import TickData, History
from src.domain.trading     import Position, TradeSetup, TradeHistory, TradeExecution
from src.brokers.mt5_components.connector import ConnectionManager
from src.brokers.mt5_components.data_fetcher import MarketDataFetcher
from src.brokers.mt5_components.order_executor import OrderExecutor
from src.brokers.mt5_components.position_repository import PositionRepository


class MT5Bridge:

    def __init__(self, login=None, password=None, server=None):
        """Initialize MT5 Bridge with all components."""
        self.connection = ConnectionManager(login, password, server)
        self.market_data = MarketDataFetcher(self.connection)
        self.executor = OrderExecutor(self.connection, self.market_data)
        self.positions = PositionRepository(self.connection)

        # Expose commonly used connection methods
        self.connected = self.connection.connected

    def connect(self) -> bool:
        return self.connection.connect()

    def shutdown(self):
        return self.connection.shutdown()

    def ensure_connected(self) -> bool:
        return self.connection.ensure_connected()

    # Market Data Methods
    def get_rates(self, symbol: str, timeframe, n: int = 180) -> History:
        return self.market_data.get_rates(symbol, timeframe, n)

    def get_tick(self, symbol: str) -> TickData:
        return self.market_data.get_tick(symbol)

    def get_spread(self, symbol: str) -> float:
        return self.market_data.get_spread(symbol)

    # Order Execution Methods
    def send_order(self, setup: TradeSetup, volume: float, magic: int, comment: str = "forward_test", max_retries: int = 3) -> TradeExecution | None:
        return self.executor.send_order(setup, volume, magic, comment, max_retries)

    def close_position(self, position) -> TradeExecution | None:
        return self.executor.close_position(position)

    # Position Queries
    def get_positions(self, symbol: str) -> List[Position]:
        return self.positions.get_positions(symbol)

    def history_deals_get(self, ticket) -> List[TradeHistory]:
        return self.positions.history_deals_get(ticket)
    
    def history_deals_get_by_position(self, position_id: int) -> List[TradeHistory]:
        return self.positions.history_deals_get_by_position(position_id)