"""infrastructure/state/position_storage.py"""
import json
import os
from datetime import datetime, timezone

from src.infrastructure.logger.logger import log

class PositionStorage:
    def __init__(self, checkpoint_dir="checkpoints"):
        self.checkpoint_dir = checkpoint_dir
        os.makedirs(checkpoint_dir, exist_ok=True)
    
    def save_positions(
            self, 
            positions: list, 
            metadata: dict,
            strategy_id: str, 
            risk_state: dict | None = None, 
        ):
        """Save open positions to disk for recovery after crash"""
        try:
            checkpoint = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "strategy_id": str(strategy_id),
                "positions": [
                    {
                        "ticket": int(pos.ticket),
                        "symbol": str(pos.symbol),
                        "type": int(pos.direction.code), 
                        "volume": float(pos.volume),
                        "open_price": float(pos.open_price),
                        "magic": int(pos.magic),
                        "comment": str(pos.comment),
                        "open_time": int(pos.time.timestamp()),
                    } for pos in positions
                ],
                "metadata": metadata,
                "risk_state": risk_state or {
                    "consecutive_losses": 0,
                    "trading_halted":     False,
                },
            }
            
            path = os.path.join(self.checkpoint_dir, f"{strategy_id}_positions.json")
            tmp_path = f"{path}.tmp"

            with open(tmp_path, 'w') as f:
                json.dump(checkpoint, f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            os.replace(tmp_path, path)
            
            log(f"[STATE] Saved {len(positions)} positions for {strategy_id}", level="DEBUG")
            return True
        except Exception as e:
            log(f"[ERROR] Failed to save positions: {e}", level="ERROR")
            return False
    
    def load_positions(self, strategy_id):
        """Load checkpoint from disk. Returns None if no checkpoint exists."""
        path = os.path.join(self.checkpoint_dir, f"{strategy_id}_positions.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r") as f:
                checkpoint = json.load(f)
            log(
                f"[STATE] Loaded checkpoint from {checkpoint.get('timestamp', 'unknown')}",
                level="INFO",
            )
            return checkpoint
        except Exception as exc:
            log(f"[STATE] Failed to load checkpoint: {exc}", level="ERROR")
            return None
        
    def load_risk_state(self, strategy_id: str) -> dict:
        """
        Convenience: load only the risk_state from the checkpoint.
        Returns a safe default dict if no checkpoint or no risk_state key.
        """
        checkpoint = self.load_positions(strategy_id)
        if checkpoint is None:
            return {"consecutive_losses": 0, "trading_halted": False}
        return checkpoint.get(
            "risk_state",
            {"consecutive_losses": 0, "trading_halted": False},
        )
    
    def check_positions(self, mt5_positions, checkpoint_data):
        if not checkpoint_data or not checkpoint_data.get("positions"):
            return {"closed": set(), "new": set()}
        
        live_tickets = {int(p.ticket) for p in mt5_positions}
        checkpoint_tickets = {p["ticket"] for p in checkpoint_data["positions"]}
        
        closed_tickets = checkpoint_tickets - live_tickets
        new_tickets = live_tickets - checkpoint_tickets

        if closed_tickets:
            log(f"[CHECKED] Closed tickets: {closed_tickets}", level="INFO")

        if new_tickets:
            log(f"[CHECKED] New MT5 tickets: {new_tickets}", level="WARNING")

        return {
            "closed": closed_tickets,
            "new": new_tickets,
        }