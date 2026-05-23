from src.config.loader import load_yaml
from src.infrastructure.logger.logger import log
from src.domain.trading import TradeResult

from src.config.loader import load_yaml
from src.infrastructure.logger.logger import log
from src.domain.trading import TradeResult
 
 
class RiskManager:
 
    def __init__(self):
        risk_config = load_yaml("risk.yaml")
        self.config = risk_config
 
        self.enable_consecutive_loss_limit = self.config.get("enable_consecutive_loss_limit", False)
        self.max_consecutive_losses        = self.config.get("max_consecutive_losses", 5)
        self.enable_drawdown_limit         = self.config.get("enable_drawdown_limit", False)
        self.max_drawdown                  = self.config.get("max_drawdown", 0.2)
 
        # Mutable risk tracking state
        # These are now serialized/deserialized via save_state()/restore_state()
        self._consecutive_losses: int = 0
        self._trading_halted:    bool = False
 
    # ------------------------------------------------------------------
    # Risk Guards
    # ------------------------------------------------------------------
 
    def can_trade(self) -> bool:
        if self._trading_halted:
            log("[RISK] Trading halted — manual restart required", level="WARNING")
        return not self._trading_halted
 
    def update(self, trade_result: TradeResult) -> None:
        pnl = trade_result.net_pnl or 0.0
 
        if pnl < 0:
            self._consecutive_losses += 1
            log(f"[RISK] Loss streak: {self._consecutive_losses}", level="WARNING")
 
            if (
                self.enable_consecutive_loss_limit
                and self._consecutive_losses >= self.max_consecutive_losses
            ):
                self._trading_halted = True
                log(
                    f"[RISK] Max consecutive losses ({self.max_consecutive_losses}) reached "
                    f"→ trading halted",
                    level="ERROR",
                )
        else:
            if self._consecutive_losses > 0:
                log(f"[RISK] Loss streak broken at {self._consecutive_losses}", level="INFO")
            self._consecutive_losses = 0
 
    # ------------------------------------------------------------------
    # State Persistence (Bug #8 fix)
    # ------------------------------------------------------------------
 
    def save_state(self) -> dict:
        """
        Return a serializable snapshot of mutable risk state.
        Called by _save_checkpoint() in forward.py and included in the
        checkpoint JSON alongside position metadata.
 
        Must only contain JSON-serializable primitives.
        """
        return {
            "consecutive_losses": self._consecutive_losses,
            "trading_halted":     self._trading_halted,
        }
 
    def restore_state(self, state: dict) -> None:
        """
        Restore mutable risk state from a checkpoint.
        Called by _run_recovery() in forward.py before warmup.
 
        Validates values before applying to prevent corrupt checkpoint
        from bypassing risk limits.
        """
        if not isinstance(state, dict):
            log("[RISK] restore_state received invalid state — ignoring", level="ERROR")
            return
 
        consecutive_losses = state.get("consecutive_losses", 0)
        trading_halted     = state.get("trading_halted", False)
 
        # Validate types and sensible ranges
        if not isinstance(consecutive_losses, int) or consecutive_losses < 0:
            log(
                f"[RISK] Invalid consecutive_losses in checkpoint: {consecutive_losses!r} — defaulting to 0",
                level="ERROR",
            )
            consecutive_losses = 0
 
        if not isinstance(trading_halted, bool):
            log(
                f"[RISK] Invalid trading_halted in checkpoint: {trading_halted!r} — defaulting to False",
                level="ERROR",
            )
            trading_halted = False
 
        self._consecutive_losses = consecutive_losses
        self._trading_halted     = trading_halted
 
        log(
            f"[RISK] State restored: consecutive_losses={self._consecutive_losses}, trading_halted={self._trading_halted}",
            level="INFO",
        )
 
        if self._trading_halted:
            log(
                "[RISK] ⚠️ Trading was halted before the crash. Fix the underlying issue and clear the checkpoint to resume.",
                level="WARNING",
            )