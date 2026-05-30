from src.domain.market_data             import MarketSnapshot, History
from src.domain.trading                 import Signal, Position
from src.domain.enums                   import Direction
from src.strategies.bb_squeeze.config   import BBSqueezeConfig
from src.strategies.base                import Strategy
from src.indicators.volatility          import IncrementalVolatility, BandwidthMACalculator
from src.infrastructure.logger.logger   import log


class BBSqueeze(Strategy):

    def __init__(self, config: BBSqueezeConfig):
        super().__init__(config)

        # Adaptive state
        self._last_trade_was_loss:  bool = False
        self._current_bar_time           = None
        self._tracked_setup_bar          = None
        self._entry_window_bar           = None
        self._consumed_setup_bar         = None

        self.indicators = IncrementalVolatility(
            bb_period  = config.bb_period,
            bb_dev     = config.bb_dev,
            atr_period = config.atr_period,
        )
        self.bandwidth_ma = BandwidthMACalculator(
            bw_ma_period = config.bw_ma_period,
        )

    # ─────────────────────────────────────────────────────────────
    # Indicator update — called by forward.py every bar unconditionally
    # ─────────────────────────────────────────────────────────────

    def update_indicators(self, history: History) -> None:
        """Update indicators from a full History object (used at runtime)."""
        closes = history.close
        highs  = history.high
        lows   = history.low

        if len(closes) < 3 or len(highs) < 3 or len(lows) < 3:
            log(
                f"[BB] Not enough data to update indicators: "
                f"{len(closes)} closes, {len(highs)} highs, {len(lows)} lows",
                level="DEBUG",
            )
            return

        self.indicators.update(
            close      = closes[-1],
            high       = highs[-1],
            low        = lows[-1],
            prev_close = closes[-2],
        )
        self.bandwidth_ma.update(self.indicators.get_bandwidth())

        # Update bar time here so forward.py can use it as the gate
        self._current_bar_time = history.time_unix[-1]

    def update_indicators_incremental(
        self,
        close:       float,
        high:        float,
        low:         float,
        open_:       float,
        prev_close:  float,
        time_unix:   int   = 0,
        tick_volume: int   = 0,
    ) -> None:

        self.indicators.update(
            close      = close,
            high       = high,
            low        = low,
            prev_close = prev_close,
        )
        self.bandwidth_ma.update(self.indicators.get_bandwidth())

        if time_unix:
            self._current_bar_time = time_unix

    # ─────────────────────────────────────────────────────────────
    # Entry logic
    # ─────────────────────────────────────────────────────────────

    def generate_signal(
        self,
        snapshot: MarketSnapshot,
        spread:   float,
    ) -> Signal | None:

        history = snapshot.history
        tick    = snapshot.tick

        if history is None:
            return None

        current_bar_time = history.time_unix[-1]
        setup_bar_time   = history.time_unix[-1]

        # ── Readiness guard ──────────────────────────────────────────
        if not (self.indicators.is_ready() and self.bandwidth_ma.is_ready()):
            log(f"[BB] Indicators not ready — bb:{self.indicators.is_ready()}, bw_ma:{self.bandwidth_ma.is_ready()}",
                level="DEBUG",
            )
            return None

        # ── Spread guard ─────────────────────────────────────────────
        if spread > self.config.max_spread:
            log(f"[BB] Spread too high: {spread}", level="DEBUG")
            return None

        # ── Setup window tracking ─────────────────────────────────────
        if self._tracked_setup_bar != setup_bar_time:
            self._tracked_setup_bar = setup_bar_time
            self._entry_window_bar  = current_bar_time

        if current_bar_time != self._entry_window_bar:
            log(
                f"[BB][FILTERED] Setup expired — "
                f"setup={setup_bar_time}, window={self._entry_window_bar}, now={current_bar_time}", 
                level="DEBUG",
            )
            return None

        # ── Consumed setup guard ─────────────────────────────────────
        if self._consumed_setup_bar == setup_bar_time:
            return None

        # ── Data-gap guard ───────────────────────────────────────────
        if len(history.time_unix) >= 3:
            bar_interval = history.time_unix[-2] - history.time_unix[-3]
            actual_gap   = history.time_unix[-1] - history.time_unix[-2]
            if bar_interval > 0 and actual_gap > bar_interval * 1.5:
                log(
                    f"[BB][FILTERED] Data gap — expected ~{bar_interval}s, got {actual_gap}s",
                    level="WARNING",
                )
                return None

        # ── Indicator values ─────────────────────────────────────────
        prev_upper, prev_lower, _ = self.indicators.get_previous_bollinger_bands()
        atr_value    = self.indicators.get_atr()
        bandwidth    = self.indicators.get_bandwidth()
        bandwidth_ma = self.bandwidth_ma.get_bandwidth_ma()

        if prev_upper is None or prev_lower is None or atr_value == 0 or bandwidth_ma == 0:
            return None

        # ── Bandwidth filter (squeeze condition) ─────────────────────
        if bandwidth >= self.config.constant * bandwidth_ma:
            return None

        # ── Previous candle OHLC (the setup candle) ──────────────────
        prev_open  = history.open[-1]
        prev_close = history.close[-1]
        prev_high  = history.high[-1]
        prev_low   = history.low[-1]

        # ── Adaptive filter ───────────────────────────────────────────
        if self._last_trade_was_loss:
            if abs(prev_close - prev_open) <= self.config.adaptive_constant * atr_value:
                return None

        # ── Candle validity ───────────────────────────────────────────
        valid_buy = (prev_lower < prev_open < prev_upper and prev_close > prev_upper)
        valid_sell = (prev_lower < prev_open < prev_upper and prev_close < prev_lower)

        # ── BUY signal ───────────────────────────────────────────────
        if prev_close > prev_upper and valid_buy:
            if tick.ask and tick.ask > prev_high + 0.1 * atr_value:
                self._consumed_setup_bar = setup_bar_time
                return Signal(
                    signal_id   = f"{tick.time}_BUY",
                    symbol      = tick.symbol,
                    timestamp   = tick.time,
                    direction   = Direction.LONG,
                    strategy_id = self.strategy_id,
                    entry_price = tick.ask,
                    notes       = "BB squeeze breakout BUY",
                )

        # ── SELL signal ──────────────────────────────────────────────
        if prev_close < prev_lower and valid_sell:
            if tick.bid and tick.bid < prev_low - 0.1 * atr_value:
                self._consumed_setup_bar = setup_bar_time
                return Signal(
                    signal_id   = f"{tick.time}_SELL",
                    symbol      = tick.symbol,
                    timestamp   = tick.time,
                    direction   = Direction.SHORT,
                    strategy_id = self.strategy_id,
                    entry_price = tick.bid,
                    notes       = "BB squeeze breakout SELL",
                )

        return None

    # ─────────────────────────────────────────────────────────────
    # Exit logic
    # ─────────────────────────────────────────────────────────────

    def check_exit(self, pos: Position, snapshot: MarketSnapshot) -> tuple[bool, str]:
        """
        Close a LONG when bid falls to/below the lower band.
        Close a SHORT when ask rises to/above the upper band.

        Returns (should_exit, reason)

        Bug #6 fix: bands are now always current because update_indicators()
        is called unconditionally from forward.py every bar, not just when
        generate_signal() runs.
        """
        prev_upper, prev_lower, _ = self.indicators.get_previous_bollinger_bands()

        if prev_upper is None or prev_lower is None:
            return False, ""

        if pos.direction == Direction.LONG:
            if snapshot.tick.bid <= prev_lower:
                return True, "bollinger_lower_cross"

        if pos.direction == Direction.SHORT:
            if snapshot.tick.ask >= prev_upper:
                return True, "bollinger_upper_cross"

        return False, ""

    # ─────────────────────────────────────────────────────────────
    # Post-trade state update
    # ─────────────────────────────────────────────────────────────

    def update_trade_result(self, trade) -> None:
        if trade.net_pnl is None:
            return
        self._last_trade_was_loss = trade.net_pnl < 0

    def save_state(self) -> dict:
        return {"last_trade_was_loss": self._last_trade_was_loss}

    def restore_state(self, state: dict) -> None:
        if state:
            self._last_trade_was_loss = state.get("last_trade_was_loss", False)

    # ─────────────────────────────────────────────────────────────
    # Indicator snapshot (for DataLogger)
    # ─────────────────────────────────────────────────────────────

    def expose_indicator_values(self) -> dict:
        prev_upper, prev_lower, prev_middle = self.indicators.get_previous_bollinger_bands()
        return {
            "bb_upper":               prev_upper,
            "bb_lower":               prev_lower,
            "bb_middle":              prev_middle,
            "atr":                    self.indicators.get_atr(),
            "bandwidth":              self.indicators.get_bandwidth(),
            "bandwidth_ma":           self.bandwidth_ma.get_bandwidth_ma(),
            "adaptive_filter_active": self._last_trade_was_loss,
        }