'''src/engine/components/position_manager.py'''
from typing import List, Tuple, Dict
from datetime import datetime

from src.domain.enums import Direction
from src.domain.market_data import TickData
from src.domain.trading import Position
from src.infrastructure.logger.logger import log
from src.infrastructure.logger.data_logger import DataLogger


class PositionManager:
    def __init__(self, bridge, datalogger: DataLogger | None = None):

        self.bridge = bridge
        self.datalogger = datalogger or DataLogger()

        self._position_metadata: Dict[Tuple[int, int], Dict] = {}

    # ------------------------------------------------------------------
    # Position Queries
    # ------------------------------------------------------------------

    def get_strategy_positions(self, symbol: str, strategy_id: str) -> List[Position]:

        positions = self.bridge.get_positions(symbol)
        if not positions:
            return []

        result = []
        for pos in positions:
            match = pos.comment == str(strategy_id)
            log(
                f"[POSITION] ticket={pos.ticket} | raw_comment='{pos.comment}' | expected='{strategy_id}' | exact_match={match}",
                level="DEBUG"
            )
            if not match:
                continue

            key  = self._get_position_key(pos)
            meta = self._position_metadata.get(key, {})
            result.append(pos)

        log(f"[POSITION] {len(result)} position(s) matched strategy_id='{strategy_id}'", level="DEBUG")
        return result
    

    def export_metadata(self):
        return dict(self._position_metadata)
    

    def load_metadata(self, metadata: Dict[Tuple[int, int], Dict]) -> None:
        """Restore metadata from checkpoint."""
        self._position_metadata = {k: v for k, v in metadata.items()}
        log(f"[RECOVERY] Restored metadata for {len(self._position_metadata)} positions", level="INFO")


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
                "setup_id":   None,
                "execution_id": None,
                "entry_price": pos.open_price,
                "mae":        0.0,
                "mfe":        0.0,
                "recovered":  True,
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
        entry_slippage: float = 0.0,
        entry_latency_ms: float = 0.0,
    ) -> None:
        """Register position metadata when order fills."""
        metadata_key = self._build_position_key(position_ticket, open_time)

        self._position_metadata[metadata_key] = {
            'setup_id':         setup_id,
            'entry_slippage':   entry_slippage,
            'entry_latency_ms': entry_latency_ms,
            'entry_price':      None,
            'mae':              0.0,
            'mfe':              0.0,
        }

        log(f"[TRACKED] Position ticket={position_ticket} setup={setup_id}", level="DEBUG")

    # ------------------------------------------------------------------
    # MAE/MFE Tracking
    # ------------------------------------------------------------------

    def _update_mae_mfe(self, tick: TickData, pos: Position) -> None:
        """Update max adverse/favorable excursion for open position."""
        key = self._get_position_key(pos)


        if key not in self._position_metadata:
            return

        meta        = self._position_metadata[key]
        entry_price = pos.open_price or meta.get('entry_price')

        if entry_price is None:
            return

        mid_price = (tick.bid + tick.ask) / 2

        if pos.direction == Direction.LONG:
            adverse   = entry_price - mid_price
            favorable = mid_price   - entry_price
        elif pos.direction == Direction.SHORT:
            adverse   = mid_price   - entry_price
            favorable = entry_price - mid_price
        else:
            return

        meta['mae'] = max(meta.get('mae', 0.0), adverse)
        meta['mfe'] = max(meta.get('mfe', 0.0), favorable)

    # ── Private helpers ────────────────────────────────────────────────

    def _get_position_key(self, pos) -> Tuple[int, int]:
        t = pos.time
        return (int(pos.ticket), int(t.timestamp()) if hasattr(t, 'timestamp') else int(t))

    def _build_position_key(self, ticket: int, open_time) -> Tuple[int, int]:
        if hasattr(open_time, 'timestamp'):
            open_time = int(open_time.timestamp())
        return (int(ticket), int(open_time))