from datetime import datetime, timezone

from src.domain.enums import Direction
from src.domain.market_data import TickData
from src.domain.trading import Position
from src.infrastructure.logger.logger import log
from src.infrastructure.logger.data_logger import DataLogger


class PositionManager:

    def __init__(self, bridge, datalogger: DataLogger | None = None):
        self.bridge    = bridge
        self.datalogger = datalogger or DataLogger()
        self._position_metadata: dict[int, dict] = {}

    # ------------------------------------------------------------------
    # Position Queries
    # ------------------------------------------------------------------

    def get_strategy_positions(self, symbol: str, strategy_id: str) -> list[Position]:
        positions = self.bridge.get_positions(symbol)
        if not positions:
            return []

        result = []
        for pos in positions:
            if pos.comment != str(strategy_id):
                continue
            result.append(pos)

        log(
            f"[POSITION] {len(result)} position(s) matched strategy_id='{strategy_id}'",
            level="DEBUG",
        )
        return result

    def has_open_position(self, symbol: str, strategy_id: str) -> bool:
        return len(self.get_strategy_positions(symbol, strategy_id)) > 0

    def load_metadata(self, metadata: dict) -> None:
        if not metadata:
            self._position_metadata = {}
            return

        restored = {}
        for k, v in metadata.items():
            try:
                restored[int(k)] = v
            except (ValueError, TypeError) as exc:
                log(f"[RECOVERY] Bad metadata key '{k}': {exc}", level="ERROR")
        self._position_metadata = restored
        log(f"[RECOVERY] Restored metadata for {len(restored)} position(s)", level="INFO")

    def remove_metadata(self, ticket: int) -> None:
        key = int(ticket)
        if key in self._position_metadata:
            del self._position_metadata[key]
            log(f"[META] Removed metadata for ticket={ticket}", level="DEBUG")

    def ensure_metadata(self, pos: Position) -> None:
        """Create placeholder metadata for a position recovered from MT5 with no checkpoint."""
        key = int(pos.ticket)
        if key not in self._position_metadata:
            log(f"[META] Creating placeholder for recovered ticket={pos.ticket}", level="WARNING")
            self._position_metadata[key] = {
                "setup_id":        None,
                "entry_price":     pos.open_price,
                "entry_fill_time": pos.time,
                "mae":             0.0,
                "mfe":             0.0,
                "recovered":       True,
                "reconciled":      False,
            }

    def reconcile(self, mt5_positions, checkpoint_data, position_storage) -> None:
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

    # ------------------------------------------------------------------
    # Position Lifecycle Tracking
    # ------------------------------------------------------------------

    def track_entry_position(
        self,
        position_ticket:  int,
        setup_id:         str,
        entry_slippage:   float = 0.0,
        entry_latency_ms: float = 0.0,
        entry_fill_price: float | None = None,       # Bug #10 fix: was always None
        entry_fill_time:  datetime | None = None,    # Bug #10 fix: was never stored
    ) -> None:
        """
        Register position metadata when order fills.

        entry_fill_price and entry_fill_time are now required for correct
        duration_minutes calculation in exit_handler and MAE/MFE tracking.
        """
        key = int(position_ticket)
        self._position_metadata[key] = {
            "setup_id":         setup_id,
            "entry_slippage":   entry_slippage,
            "entry_latency_ms": entry_latency_ms,
            "entry_price":      entry_fill_price,   # ← fix: was None
            "entry_fill_time":  entry_fill_time,    # ← fix: was missing entirely
            "mae":              0.0,
            "mfe":              0.0,
        }
        log(
            f"[TRACKED] ticket={position_ticket} setup={setup_id} "
            f"price={entry_fill_price} fill_time={entry_fill_time}",
            level="DEBUG",
        )

    # ------------------------------------------------------------------
    # MAE/MFE Tracking
    # ------------------------------------------------------------------

    def _update_mae_mfe(self, tick: TickData, pos: Position) -> None:
        key = int(pos.ticket)
        if key not in self._position_metadata:
            return

        meta        = self._position_metadata[key]
        entry_price = meta.get("entry_price") or pos.open_price  # fallback to MT5 value

        if entry_price is None:
            return

        mid_price = (tick.bid + tick.ask) / 2

        if pos.direction == Direction.LONG:
            adverse   = entry_price - mid_price
            favorable = mid_price   - entry_price
        else:
            adverse   = mid_price   - entry_price
            favorable = entry_price - mid_price

        meta["mae"] = max(meta.get("mae", 0.0), adverse)
        meta["mfe"] = max(meta.get("mfe", 0.0), favorable)

    # ------------------------------------------------------------------
    # Serialization helpers (for checkpoint)
    # ------------------------------------------------------------------

    def serialize_metadata(self) -> dict:
        """
        Convert metadata to JSON-serializable form.
        datetime objects are converted to ISO strings.
        """
        result = {}
        for ticket, meta in self._position_metadata.items():
            entry = dict(meta)
            if isinstance(entry.get("entry_fill_time"), datetime):
                entry["entry_fill_time"] = entry["entry_fill_time"].isoformat()
            result[str(ticket)] = entry
        return result

    @staticmethod
    def deserialize_metadata(raw: dict) -> dict:
        """
        Restore metadata from checkpoint.
        ISO datetime strings are converted back to datetime objects.
        """
        result = {}
        for k, v in raw.items():
            entry = dict(v)
            eft = entry.get("entry_fill_time")

            if isinstance(eft, str):
                try:
                    dt = datetime.fromisoformat(eft)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    entry["entry_fill_time"] = datetime.fromisoformat(str(dt))
                except ValueError:
                    entry["entry_fill_time"] = None
            try:
                result[int(k)] = entry
            except (ValueError, TypeError):
                log(f"[RECOVERY] Bad metadata key '{k}'", level="ERROR")
        return result

    # ── Private helpers ────────────────────────────────────────────────

    def _get_position_key(self, pos) -> int:
        return int(pos.ticket)