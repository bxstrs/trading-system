'''src/strategies/base.py'''
from abc import ABC, abstractmethod
from typing import Any

from src.domain.market_data import MarketSnapshot, History
from src.domain.trading import TradeExecution, TradeResult, Signal


class Strategy(ABC):
    def __init__(self, config: Any):
        self.config = config
        self.strategy_id = self.__class__.__name__
        self.magic_number = hash(self.strategy_id) % (10 ** 8)

    # -----------------------------
    # Entry
    # -----------------------------
    @abstractmethod
    def generate_signal(
        self,
        snapshot: MarketSnapshot,
        spread: float,
    ) -> Signal | None:
        pass

    # -----------------------------
    # Exit
    # -----------------------------
    @abstractmethod
    def check_exit(
        self,
        trade,
        market_state: MarketSnapshot,
    ) -> bool:
        """
        Return True if trade should be closed
        """
        pass

    # -----------------------------
    # State update (after trade closes)
    # -----------------------------
    def update_trade_result(self, trade: TradeResult) -> None:
        """
        Optional override
        """
        pass