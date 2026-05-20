"""infrastructure/state/position_storage.py"""
import json
import os
from datetime import datetime, timezone

from src.infrastructure.logger.logger import log

class PositionStorage:
    def __init__(self, checkpoint_dir="checkpoints"):
        self.checkpoint_dir = checkpoint_dir
        os.makedirs(checkpoint_dir, exist_ok=True)
    
    def save_positions(self, positions, metadata, strategy_id):
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
                "metadata": {
                    str(ticket): {
                        "setup_id": meta.get('setup_id'),
                        "execution_id": meta.get('execution_id'),
                        "entry_slippage": meta.get('entry_slippage', 0.0),
                        "entry_latency_ms": meta.get('entry_latency_ms', 0.0),
                        "entry_price": meta.get('entry_price'),
                        "mae": meta.get('mae', 0.0),
                        "mfe": meta.get('mfe', 0.0),
                    }
                    for ticket, meta in metadata.items()
                }
                
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
        """Load positions from last checkpoint"""
        try:
            path = f"{self.checkpoint_dir}/{strategy_id}_positions.json"
            if not os.path.exists(path):
                return None
            
            with open(path, 'r') as f:
                checkpoint = json.load(f)
            
            log(f"[STATE] Loaded checkpoint from {checkpoint['timestamp']}", level="INFO")
            return checkpoint
        except Exception as e:
            log(f"[ERROR] Failed to load checkpoint: {e}", level="ERROR")
            return None
    
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