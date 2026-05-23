'''src/strategies/base.py'''
import hashlib
from abc import ABC, abstractmethod
from typing import Any

from src.domain.market_data import MarketSnapshot 
from src.domain.trading import TradeResult, Signal


class Strategy(ABC):
    def __init__(self, config: Any):
        self.config = config
        self.strategy_id = self.__class__.__name__
        self.magic_number = self._stable_magic(self.strategy_id)

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

    def _stable_magic(self, strategy_id: str) -> int:
        digest = hashlib.md5(strategy_id.encode("utf-8"), usedforsecurity=False).hexdigest()
        raw = int(digest[:7], 16)
        return (raw % 90_000_000) + 10_000_000