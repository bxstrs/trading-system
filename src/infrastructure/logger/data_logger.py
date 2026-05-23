import csv
import os
import time
from collections import defaultdict

from src.infrastructure.logger.logger import log


class DataLogger:
    """Trade journal using plain CSV (append-safe, tool-compatible)."""

    TRADE_HEADERS = [
        # TradeSetup: signal intent
        "setup_id", "strategy_id", "symbol", "signal_timestamp",
        "direction", "trigger_price",
        "bb_upper", "bb_lower", "bb_middle", "bandwidth", "bandwidth_ma", "atr", "spread",
        "intended_entry_price", "intended_volume",
        "hour_of_day", "candle_open", "candle_high", "candle_low", "candle_close",
        "prev_trade_pnl", "adaptive_filter_active",
        # TradeExecution: fill details
        "position_id", "deal", "fill_price", "fill_volume", "fill_time",
        "slippage", "latency_ms", "execution_status",
        # TradeResult: complete lifecycle
        "exit_price", "exit_time", "exit_reason",
        "exit_bid", "exit_ask", "total_fees", "net_pnl",
        "duration_minutes", "risk_reward_ratio",
        "max_adverse_excursion", "max_favorable_excursion", "trade_status",
    ]

    PORTFOLIO_HEADERS = [
        "timestamp", "strategy_id", "symbol",
        "total_trades", "wins", "losses", "consecutive_wins", "consecutive_losses",
        "max_drawdown", "current_drawdown", "profit_factor",
        "avg_win", "avg_loss", "payoff_ratio",
        "win_rate", "expected_payoff", "daily_pnl", "cumulative_pnl",
    ]

    MAX_PENDING_ROWS = 500

    def __init__(
        self,
        base_path:   str = "logs",
        strategy_id: str = "default",
        symbol:      str = "UNKNOWN",
    ):
        os.makedirs(base_path, exist_ok=True)

        self.base_path   = base_path
        self.strategy_id = strategy_id
        self.symbol      = symbol

        trade_filename     = f"trades_{symbol}_{strategy_id}.csv"
        portfolio_filename = f"portfolio_{symbol}_{strategy_id}.csv"

        self.trade_filepath     = os.path.join(base_path, trade_filename)
        self.portfolio_filepath = os.path.join(base_path, portfolio_filename)

        # Detect whether files already exist BEFORE opening them
        trade_is_new     = not os.path.exists(self.trade_filepath)
        portfolio_is_new = not os.path.exists(self.portfolio_filepath)

        # "a" = append text — safe across restarts, no gzip member issue
        self.trade_file     = open(self.trade_filepath,     "a", newline="", encoding="utf-8")
        self.portfolio_file = open(self.portfolio_filepath, "a", newline="", encoding="utf-8")

        self.trade_writer     = csv.DictWriter(self.trade_file,     fieldnames=self.TRADE_HEADERS)
        self.portfolio_writer = csv.DictWriter(self.portfolio_file, fieldnames=self.PORTFOLIO_HEADERS)

        # Only write headers when creating a new file
        if trade_is_new:
            self.trade_writer.writeheader()
        if portfolio_is_new:
            self.portfolio_writer.writeheader()

        # Row cache for partial updates (setup → execution → result)
        self._pending_rows:      dict = defaultdict(dict)
        self._row_timestamps:    dict = {}      # setup_id → time.monotonic()
        self._writes_since_fsync: int = 0
        self._fsync_batch_size:   int = 10

    def log_trade_setup(self, setup) -> None:
        """Log trade setup. Row remains open for execution/result updates."""
        setup_id = setup.setup_id

        row = {
            "setup_id":              setup_id,
            "strategy_id":           setup.strategy_id,
            "symbol":                setup.symbol,
            "signal_timestamp":      setup.timestamp.isoformat() if setup.timestamp else None,
            "direction":             setup.direction.value if hasattr(setup.direction, "value") else setup.direction,
            "trigger_price":         setup.trigger_price,
            "bb_upper":              setup.bb_upper,
            "bb_lower":              setup.bb_lower,
            "bb_middle":             setup.bb_middle,
            "bandwidth":             setup.bandwidth,
            "bandwidth_ma":          setup.bandwidth_ma,
            "atr":                   setup.atr,
            "spread":                setup.spread,
            "intended_entry_price":  setup.intended_entry_price,
            "intended_volume":       setup.intended_volume,
            "hour_of_day":           setup.hour_of_day,
            "candle_open":           setup.candle_open,
            "candle_high":           setup.candle_high,
            "candle_low":            setup.candle_low,
            "candle_close":          setup.candle_close,
            "prev_trade_pnl":        setup.prev_trade_pnl,
            "adaptive_filter_active": setup.adaptive_filter_active,
        }

        self._pending_rows[setup_id].update(row)
        self._row_timestamps[setup_id] = time.monotonic()

        self._evict_if_needed()

    def log_trade_execution(self, execution) -> None:
        """Update pending row with execution details."""
        setup_id = execution.setup_id
        if setup_id is None:
            return

        row = {
            "position_id":      execution.position_id,
            "deal":             execution.deal,
            "fill_price":       execution.fill_price,
            "fill_volume":      execution.fill_volume,
            "fill_time":        execution.fill_time.isoformat() if execution.fill_time else None,
            "slippage":         execution.slippage,
            "latency_ms":       execution.latency_ms,
            "execution_status": execution.status,
        }
        self._pending_rows[setup_id].update(row)

    def log_trade_result(self, result) -> None:
        """Merge all cached data and write complete row to CSV."""
        setup_id = result.setup_id

        row = {
            "exit_price":               result.exit_price,
            "exit_time":                result.exit_time.isoformat() if result.exit_time else None,
            "exit_reason":              result.exit_reason,
            "exit_bid":                 result.exit_bid,
            "exit_ask":                 result.exit_ask,
            "total_fees":               result.total_fees,
            "net_pnl":                  result.net_pnl,
            "duration_minutes":         result.duration_minutes,
            "risk_reward_ratio":        result.risk_reward_ratio,
            "max_adverse_excursion":    result.max_adverse_excursion,
            "max_favorable_excursion":  result.max_favorable_excursion,
            "trade_status":             result.status,
        }

        complete_row = {**self._pending_rows.get(setup_id, {}), **row}

        self.trade_writer.writerow(complete_row)
        self.trade_file.flush()

        # Periodic fsync to ensure durability without blocking every write
        self._writes_since_fsync += 1
        if self._writes_since_fsync >= self._fsync_batch_size:
            try:
                os.fsync(self.trade_file.fileno())
            except (OSError, ValueError):
                pass
            self._writes_since_fsync = 0

        self._pending_rows.pop(setup_id, None)
        self._row_timestamps.pop(setup_id, None)

    def flush_abandoned_rows(self, timeout_seconds: float = 3600.0) -> int:
        """Write stale pending rows as CANCELLED. Call periodically from main loop."""
        now = time.monotonic()
        stale_ids = [
            sid for sid, ts in self._row_timestamps.items()
            if (now - ts) >= timeout_seconds
        ]
        orphan_ids = [
            sid for sid in self._pending_rows
            if sid not in self._row_timestamps
        ]
        flush_ids = list(set(stale_ids + orphan_ids))

        for setup_id in flush_ids:
            row = dict(self._pending_rows[setup_id])
            row.setdefault("trade_status", "CANCELLED")
            row.setdefault("exit_reason", f"No result after {timeout_seconds:.0f}s")
            self.trade_writer.writerow(row)
            self._pending_rows.pop(setup_id, None)
            self._row_timestamps.pop(setup_id, None)

        if flush_ids:
            self.trade_file.flush()
            log(f"[DATALOGGER] Flushed {len(flush_ids)} abandoned row(s)", level="WARNING")

        return len(flush_ids)

    def log_portfolio_stats(self, stats) -> None:
        row = {
            "timestamp":           stats.timestamp.isoformat() if stats.timestamp else None,
            "strategy_id":         stats.strategy_id,
            "symbol":              stats.symbol,
            "total_trades":        stats.total_trades,
            "wins":                stats.wins,
            "losses":              stats.losses,
            "consecutive_wins":    stats.consecutive_wins,
            "consecutive_losses":  stats.consecutive_losses,
            "max_drawdown":        stats.max_drawdown,
            "current_drawdown":    stats.current_drawdown,
            "profit_factor":       stats.profit_factor,
            "avg_win":             stats.avg_win,
            "avg_loss":            stats.avg_loss,
            "payoff_ratio":        stats.payoff_ratio,
            "win_rate":            stats.win_rate,
            "expected_payoff":     stats.expected_payoff,
            "daily_pnl":           stats.daily_pnl,
            "cumulative_pnl":      stats.cumulative_pnl,
        }
        self.portfolio_writer.writerow(row)
        self.portfolio_file.flush()
        try:
            os.fsync(self.portfolio_file.fileno())
        except (OSError, IOError):
            pass

    def close(self, clean_exit: bool = False) -> None:
        """Flush all pending data and close files."""
        if clean_exit:
            flushed = self.flush_abandoned_rows(timeout_seconds=0)
        else:
            flushed = 0

        if flushed:
            log(f"[DATALOGGER] Flushed {flushed} abandoned row(s) on close", level="WARNING")

        for f in (self.trade_file, self.portfolio_file):
            if f:
                try:
                    f.flush()
                    os.fsync(f.fileno())
                except (OSError, ValueError):
                    pass
                try:
                    f.close()
                except (OSError, ValueError):
                    pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False  # always propagate exceptions

    # ── Private helpers ───────────────────────────────────────────────

    def _evict_if_needed(self) -> None:
        """
        Bug #13 fix: if pending cache exceeds MAX_PENDING_ROWS,
        force-flush the oldest rows as CANCELLED to prevent memory leak.
        This guards against high signal-rejection rates or missing result calls.
        """
        if len(self._pending_rows) <= self.MAX_PENDING_ROWS:
            return

        # Sort by timestamp, evict the oldest half
        sorted_by_age = sorted(
            self._row_timestamps.items(),
            key=lambda kv: kv[1]
        )
        evict_count = len(self._pending_rows) - (self.MAX_PENDING_ROWS // 2)
        evict_ids   = [sid for sid, _ in sorted_by_age[:evict_count]]

        for setup_id in evict_ids:
            row = dict(self._pending_rows[setup_id])
            row.setdefault("trade_status", "CANCELLED")
            row.setdefault("exit_reason", "evicted: pending cache overflow")
            self.trade_writer.writerow(row)
            self._pending_rows.pop(setup_id, None)
            self._row_timestamps.pop(setup_id, None)

        if evict_ids:
            self.trade_file.flush()
            log(
                f"[DATALOGGER] Evicted {len(evict_ids)} rows from pending cache "
                f"(cache exceeded {self.MAX_PENDING_ROWS} rows)",
                level="WARNING",
            )