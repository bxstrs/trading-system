"""
src/infrastructure/state/intent_store.py

Write-ahead log (WAL) for order intentions.

WHY THIS EXISTS:
  The crash window between `bridge.send_order()` returning DONE and
  `position_manager.track_entry_position()` writing metadata is a
  duplicate-execution risk. If the engine crashes in that window:
    - MT5 has a filled position
    - Our metadata has nothing
    - On restart, `ensure_metadata()` creates a placeholder with setup_id=None
    - `check_manual_closes()` fires on the next tick and logs a phantom TradeResult
    - The strategy's `_last_trade_was_loss` is reset incorrectly

  The intent store solves this by writing a durable "I intend to send
  this order" record BEFORE touching the broker, then marking it FILLED
  or ABANDONED based on the broker response. On startup, any PENDING
  intents are resolved against live MT5 positions before warmup runs.

INTENT LIFECYCLE:
  PENDING   → written atomically before order_send()
  FILLED    → written atomically after confirmed fill, includes position_id
  ABANDONED → written if order fails/rejects/no-response

THREAD SAFETY:
  Not thread-safe by design. This engine is single-threaded per symbol.
  If you introduce multi-threading per symbol, add a lock around
  _atomic_write and get_pending_intents.
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional

from src.infrastructure.logger.logger import log


class IntentStore:

    _STATUS_PENDING   = "PENDING"
    _STATUS_FILLED    = "FILLED"
    _STATUS_ABANDONED = "ABANDONED"

    def __init__(self, checkpoint_dir: str = "checkpoints"):
        self.checkpoint_dir = checkpoint_dir
        os.makedirs(checkpoint_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public write API
    # ------------------------------------------------------------------

    def write_pending(self, intent_id: str, setup) -> bool:
        """
        Write intent record BEFORE sending the order.
        Must succeed before any broker call is made.
        Returns False if the write fails (caller should abort the trade).
        """
        record = {
            "intent_id":       intent_id,
            "status":          self._STATUS_PENDING,
            "created_at":      datetime.now(timezone.utc).isoformat(),
            "setup_id":        setup.setup_id,
            "strategy_id":     setup.strategy_id,
            "symbol":          setup.symbol,
            "direction":       setup.direction.value if hasattr(setup.direction, "value") else str(setup.direction),
            "intended_volume": setup.intended_volume,
            "position_id":     None,
        }
        ok = self._atomic_write(intent_id, record)
        if ok:
            log(f"[INTENT] Wrote PENDING intent={intent_id}", level="DEBUG")
        else:
            log(f"[INTENT] FAILED to write PENDING intent={intent_id}", level="ERROR")
        return ok

    def mark_filled(self, intent_id: str, position_id: int) -> bool:
        """
        Mark intent as filled after confirmed broker response.
        Idempotent: safe to call more than once with the same position_id.
        """
        record = self._read(intent_id)
        if record is None:
            log(f"[INTENT] Cannot mark filled — intent {intent_id} not found", level="ERROR")
            return False
        if record.get("status") == self._STATUS_FILLED:
            return True  # already marked, idempotent
        record["status"]      = self._STATUS_FILLED
        record["position_id"] = int(position_id)
        record["filled_at"]   = datetime.now(timezone.utc).isoformat()
        ok = self._atomic_write(intent_id, record)
        if ok:
            log(f"[INTENT] Marked FILLED intent={intent_id}, position={position_id}", level="DEBUG")
        return ok

    def mark_abandoned(self, intent_id: str, reason: str = "") -> bool:
        """Mark intent abandoned when order fails or is rejected."""
        record = self._read(intent_id)
        if record is None:
            return False
        if record.get("status") == self._STATUS_ABANDONED:
            return True  # idempotent
        record["status"]       = self._STATUS_ABANDONED
        record["abandoned_at"] = datetime.now(timezone.utc).isoformat()
        record["reason"]       = reason
        ok = self._atomic_write(intent_id, record)
        if ok:
            log(f"[INTENT] Marked ABANDONED intent={intent_id}: {reason}", level="DEBUG")
        return ok

    # ------------------------------------------------------------------
    # Public read API
    # ------------------------------------------------------------------

    def get_pending_intents(self) -> list[dict]:
        """
        Return all PENDING intents.
        Called once at startup to detect crash-window orphans.
        """
        pending = []
        try:
            for fname in os.listdir(self.checkpoint_dir):
                if not fname.startswith("intent_") or not fname.endswith(".json"):
                    continue
                path = os.path.join(self.checkpoint_dir, fname)
                try:
                    with open(path, "r") as f:
                        record = json.load(f)
                    if record.get("status") == self._STATUS_PENDING:
                        pending.append(record)
                except Exception as exc:
                    log(f"[INTENT] Failed to read {fname}: {exc}", level="ERROR")
        except Exception as exc:
            log(f"[INTENT] Failed to list checkpoint dir: {exc}", level="ERROR")
        return pending

    def cleanup_old(self, max_age_seconds: int = 86_400) -> int:
        """
        Remove FILLED and ABANDONED intents older than max_age_seconds.
        NEVER removes PENDING intents — those must be explicitly resolved.
        Call this once per day from a maintenance job, not from the hot loop.
        """
        now = datetime.now(timezone.utc)
        removed = 0
        try:
            for fname in os.listdir(self.checkpoint_dir):
                if not fname.startswith("intent_") or not fname.endswith(".json"):
                    continue
                path = os.path.join(self.checkpoint_dir, fname)
                try:
                    with open(path, "r") as f:
                        record = json.load(f)
                    if record.get("status") == self._STATUS_PENDING:
                        continue  # NEVER auto-delete pending intents
                    created_str = record.get("created_at")
                    if not created_str:
                        continue
                    created = datetime.fromisoformat(created_str)
                    if (now - created).total_seconds() > max_age_seconds:
                        os.remove(path)
                        removed += 1
                except Exception:
                    pass
        except Exception as exc:
            log(f"[INTENT] cleanup_old error: {exc}", level="ERROR")
        if removed:
            log(f"[INTENT] Cleaned up {removed} old intent file(s)", level="DEBUG")
        return removed

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _path(self, intent_id: str) -> str:
        return os.path.join(self.checkpoint_dir, f"intent_{intent_id}.json")

    def _read(self, intent_id: str) -> Optional[dict]:
        path = self._path(intent_id)
        try:
            with open(path, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            log(f"[INTENT] Intent file not found: {intent_id}", level="WARNING")
            return None
        except Exception as exc:
            log(f"[INTENT] Failed to read intent {intent_id}: {exc}", level="ERROR")
            return None

    def _atomic_write(self, intent_id: str, record: dict) -> bool:
        """Write record atomically: write to .tmp → fsync → os.replace."""
        path = self._path(intent_id)
        tmp  = path + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(record, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            return True
        except Exception as exc:
            log(f"[INTENT] Atomic write failed for intent {intent_id}: {exc}", level="ERROR")
            try:
                os.remove(tmp)
            except Exception:
                pass
            return False