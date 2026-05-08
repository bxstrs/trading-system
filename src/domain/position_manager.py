'''src/domain/position_manager.py'''
from typing import List, Tuple, Dict, Optional
from datetime import datetime

import MetaTrader5 as mt5
from src.domain.trade_converter import mt5_position_to_trade_result
from src.core.types import TradeResult, Direction
from src.infrastructure.logger.logger import log
from src.infrastructure.logger.data_logger import DataLogger
from src.config.loader import load_yaml
from src.domain.risk_manager import RiskManager


class PositionManager:
    def __init__(self, bridge, datalogger: Optional[DataLogger] = None):
        
        self.bridge = bridge
        self.datalogger = datalogger or DataLogger()
        
        risk_config = load_yaml("risk.yaml")

        self._position_metadata: Dict[Tuple[int, int], Dict] = {}
        self._failed_closes_queqe: List[Tuple] = []
        
    # ------------------------------------------------------------------
    # Position Queries
    # ------------------------------------------------------------------

    def get_strategy_positions(self, symbol: str, strategy_id: str) -> List[Tuple]:
        """Return list of (position, trade_result) tuples for strategy."""
        positions = self.bridge.get_positions(symbol)
        if not positions:
            return []

        result = []
        for pos in positions:
            match = pos.comment == str(strategy_id)
            log(
                f"[POSITION] ticket={pos.ticket} | "
                f"raw_comment='{pos.comment}' | "
                f"expected='{strategy_id}' | "
                f"exact_match={match}",
                level="DEBUG"
            )
            if match:
                # Retrieve metadata if exists, use placeholders if new position
                key = self._get_position_key(pos)
                meta = self._position_metadata.get(key, {})
                setup_id = meta.get('setup_id')
                execution_id = meta.get('execution_id')
                entry_slippage = meta.get('entry_slippage', 0.0)
                entry_latency_ms = meta.get('entry_latency_ms', 0.0)

                trade = mt5_position_to_trade_result(
                    pos,
                    setup_id,
                    execution_id,
                    entry_slippage,
                    entry_latency_ms
                )
                result.append((pos, trade))

        log(f"[POSITION] {len(result)} position(s) matched strategy_id='{strategy_id}'", level="DEBUG")
        return result
    
    def load_metadata(self, metadata: Dict[Tuple[int, int], Dict]) -> None:
        """Restore metadata from checkpoint."""
        self._position_metadata = {
            k: v for k, v in metadata.items()
        }
        log(f"[RECOVERY] Restored metadata for {len(self._position_metadata)} positions", level="INFO")

    def export_metadata(self):
        return dict(self._position_metadata)

    def remove_metadata(self, ticket: int):
        keys_to_remove = [
            key for key in self._position_metadata
            if key[0] == int(ticket)
        ]

        for key in keys_to_remove:
            del self._position_metadata[key]
            log(f"[META] Removed metadata {key}", level="DEBUG")

    def ensure_metadata(self, pos):
        key = self._get_position_key(pos)

        if key not in self._position_metadata:
            log(f"[META] Creating placeholder for {key}", level="WARNING")

            self._position_metadata[key] = {
                "setup_id": None,
                "execution_id": None,
                "entry_price": pos.price_open,
                "mae": 0.0,
                "mfe": 0.0,
                "recovered": True,
            }
    
    def reconcile(self, mt5_positions, checkpoint_data, position_storage):
        if not checkpoint_data:
            return

        result = position_storage.check_positions(mt5_positions, checkpoint_data)

        for ticket in result["closed"]:
            self.remove_metadata(ticket)

        mt5_map = {int(p.ticket): p for p in mt5_positions}

        for ticket in result["new"]:
            pos = mt5_map.get(ticket)
            if pos:
                self.ensure_metadata(pos)

    def has_open_position(self, symbol: str, strategy_id: str) -> bool:
        """Check if strategy has any open positions."""
        return len(self.get_strategy_positions(symbol, strategy_id)) > 0

    # ------------------------------------------------------------------
    # Position Lifecycle Tracking
    # ------------------------------------------------------------------

    def track_entry_position(
        self,
        position_ticket: int,
        open_time: datetime,
        setup_id: str,
        execution_id: str,
        entry_slippage: float = 0.0,
        entry_latency_ms: float = 0.0
    ) -> None:
        """Register position metadata when order fills."""
        metadata_key = self._build_position_key(position_ticket, open_time)

        self._position_metadata[metadata_key] = {
            'setup_id': setup_id,
            'execution_id': execution_id,
            'entry_slippage': entry_slippage,
            'entry_latency_ms': entry_latency_ms,
            'entry_price': None,
            'mae': 0.0,
            'mfe': 0.0,
        }

        log(f"[TRACKED] Position ticket={position_ticket} setup={setup_id}", level="DEBUG")

    # ------------------------------------------------------------------
    # Exit Handler
    # ------------------------------------------------------------------

    def handle_exit(self, strategy, market_state, risk_manager) -> None:
        """Check and execute exits for open positions."""
        trades = self.get_strategy_positions(
            market_state.symbol,
            strategy.strategy_id
        )

        for pos, trade in trades:
            # Update MAE/MFE for this position (every tick)
            self._update_mae_mfe(pos, trade)

            if strategy.check_exit(trade, market_state):
                exit_price = market_state.bid
                log(
                    f"[EXIT SIGNAL] {trade.direction} at {exit_price}",
                    level="SIGNAL"
                )
                try:
                    result = self.bridge.close_position(pos)
                    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                        retcode = result.retcode if result else "NONE"
                        self._queue_failed_close(
                            pos,
                            retries=3,
                            reason=f"retcode={retcode}"
                        )
                        continue
                except Exception as e:
                    self._queue_failed_close(
                        pos,
                        retries=3,
                        reason=str(e)
                    )
                    continue

                actual_exit_price = result.price if result and result.retcode == mt5.TRADE_RETCODE_DONE else market_state.bid

                deal_ticket = result.deal
                deals = self.bridge.history_deals_get(ticket=deal_ticket)
                actual_pnl = deals[0].profit if deals and len(deals) > 0 else None

                # Populate final trade result
                trade.exit_price = actual_exit_price
                trade.exit_time = market_state.timestamp
                trade.exit_bid = market_state.bid
                trade.exit_ask = market_state.ask
                trade.net_pnl = actual_pnl
                trade.status = "CLOSED"
                trade.exit_reason = "bollinger_exit"

                # Calculate duration
                if trade.entry_time and trade.exit_time:
                    duration_seconds = (trade.exit_time - trade.entry_time).total_seconds()
                    trade.duration_minutes = duration_seconds / 60.0

                # Add MAE/MFE from tracking
                key = self._get_position_key(pos)
                meta = self._position_metadata.get(key, {})
                trade.max_adverse_excursion = meta.get('mae', 0.0)
                trade.max_favorable_excursion = meta.get('mfe', 0.0)

                # Log to data logger
                if self.datalogger:
                    self.datalogger.log_trade_result(trade)

                risk_manager.update(trade)
                strategy.update_trade_result(trade)

                # Clean up metadata
                if key in self._position_metadata:
                    del self._position_metadata[key]

# ── Private helpers ───────────────────────────────────────────────────────────

    def _get_position_key(self, pos) -> Tuple[int, int]:
        """Create stable metadata key for MT5 positions."""
        return (int(pos.ticket), int(pos.time))


    def _build_position_key(self, ticket: int, open_time) -> Tuple[int, int]:
        """Create metadata key from raw values."""

        if hasattr(open_time, "timestamp"):
            open_time = int(open_time.timestamp())

        return (int(ticket), int(open_time))
    
    # ------------------------------------------------------------------
    # MAE/MFE Tracking
    # ------------------------------------------------------------------

    def _update_mae_mfe(self, pos, trade: TradeResult) -> None:
        """Update max adverse/favorable excursion for open position."""
        key = self._get_position_key(pos)

        if key not in self._position_metadata:
            return

        meta = self._position_metadata[key]
        entry_price = trade.entry_price or meta.get('entry_price')

        if entry_price is None:
            return

        if trade.direction == Direction.LONG:
            # For longs: MAE = low from entry, MFE = high from entry
            mid_price = (pos.bid + pos.ask) / 2 if hasattr(pos, 'bid') else pos.price_current

            adverse = entry_price - mid_price  # Drawdown from entry
            favorable = mid_price - entry_price  # Profit from entry

            meta['mae'] = max(meta.get('mae', 0), adverse)
            meta['mfe'] = max(meta.get('mfe', 0), favorable)

        elif trade.direction == Direction.SHORT:
            # For shorts: MAE = high from entry, MFE = low from entry
            mid_price = (pos.bid + pos.ask) / 2 if hasattr(pos, 'bid') else pos.price_current

            adverse = mid_price - entry_price  # Drawdown from entry
            favorable = entry_price - mid_price  # Profit from entry

            meta['mae'] = max(meta.get('mae', 0), adverse)
            meta['mfe'] = max(meta.get('mfe', 0), favorable)
    
    # ------------------------------------------------------------------
    # Failed Close Retry Logic
    # ------------------------------------------------------------------
    def _queue_failed_close(self, pos, retries: int = 3, reason: str = "") -> None:
        """Queue failed position close for retry."""

        # Prevent duplicate queue entries
        already_queued = any(
            queued_pos.ticket == pos.ticket
            for queued_pos, _ in self._failed_closes_queqe
        )

        if already_queued:
            return

        self._failed_closes_queqe.append((pos, retries))

        log(
            f"[FAILED CLOSE] ticket={pos.ticket} "
            f"queued for retry ({retries} attempts left). "
            f"Reason: {reason}",
            level="WARNING"
        )