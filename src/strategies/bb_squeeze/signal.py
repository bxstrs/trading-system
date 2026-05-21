'''src/strategies/bb_squeeze/signal.py'''
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
        self._last_trade_was_loss: bool = False
        self._current_bar_time          = None      # tracks last processed bar
        self._tracked_setup_bar         = None      # setup bar (history[-2]) being monitored
        self._entry_window_bar          = None      # bar time when this setup first appeared
        self._consumed_setup_bar        = None
 
        self.indicators = IncrementalVolatility(
            bb_period=config.bb_period,
            bb_dev=config.bb_dev,
            atr_period=config.atr_period,
        )
        self.bandwidth_ma = BandwidthMACalculator(
            bw_ma_period=config.bw_ma_period,
        )
 
    # ─────────────────────────────────────────────────────────────
    # Indicator update  (accepts History dataclass)
    # ─────────────────────────────────────────────────────────────
 
    def update_indicators(self, history: History) -> None:
        closes = history.close
        highs  = history.high
        lows   = history.low
 
        if len(closes) < 3 or len(highs) < 3 or len(lows) < 3:
            log(
                f"Not enough data to update indicators: "
                f"{len(closes)} closes, {len(highs)} highs, {len(lows)} lows",
                level="DEBUG",
            )
            return
 
        self.indicators.update(
            close      = closes[-1],
            high       = highs[-1],
            low        = lows[-1],
            prev_close = closes[-2],        # required for True Range
        )
        self.bandwidth_ma.update(self.indicators.get_bandwidth())
 
    # ─────────────────────────────────────────────────────────────
    # Entry logic
    # ─────────────────────────────────────────────────────────────
 
    def generate_signal(
        self,
        snapshot: MarketSnapshot,
        spread: float,
    ) -> Signal | None:

        history = snapshot.history
        tick    = snapshot.tick

        if history is not None:
            current_bar_time = history.time_unix[-1]
            setup_bar_time   = history.time_unix[-2]
    
            # ── Update indicators once per bar ───────────────────────
            if self._current_bar_time != current_bar_time:
                self.update_indicators(history)
                log(f"ts={current_bar_time}, prev={self._current_bar_time}")
                self._current_bar_time = current_bar_time
    
            # ── Readiness guard ──────────────────────────────────────
            if not (self.indicators.is_ready() and self.bandwidth_ma.is_ready()):
                return log(
                    f"Indicators not ready — bb:{self.indicators.is_ready()}, "
                    f"bw_ma:{self.bandwidth_ma.is_ready()}",
                    level="DEBUG",
                )
    
            # ── Spread guard ─────────────────────────────────────────
            if spread > self.config.max_spread:
                log(f"Spread too high: {spread}", level="DEBUG")
                return None
    
            # ── Setup window tracking ─────────────────────────────────
            # A signal is valid only in the bar immediately after the setup bar forms.
            if self._tracked_setup_bar != setup_bar_time:
                self._tracked_setup_bar = setup_bar_time
                self._entry_window_bar  = current_bar_time
    
            if current_bar_time != self._entry_window_bar:
                log(
                    f"[FILTERED] Setup expired — "
                    f"setup={setup_bar_time}, window={self._entry_window_bar}, now={current_bar_time}",
                )
                return None
            
            # ── Consumed setup guard ─────────────────────────────────
            if self._consumed_setup_bar == setup_bar_time:
                return None
    
            # ── Data-gap guard ───────────────────────────────────────
            if len(history.time_unix) >= 3:
                bar_interval = history.time_unix[-2] - history.time_unix[-3]
                actual_gap   = history.time_unix[-1] - history.time_unix[-2]
                if bar_interval > 0 and actual_gap > bar_interval * 1.5:
                    log(
                        f"[FILTERED] Data gap — expected ~{bar_interval}s, got {actual_gap}s",
                        level="WARNING",
                    )
                    return None
    
            # ── Indicator values ─────────────────────────────────────
            prev_upper, prev_lower, _ = self.indicators.get_previous_bollinger_bands()
            atr_value    = self.indicators.get_atr()
            bandwidth    = self.indicators.get_bandwidth()
            bandwidth_ma = self.bandwidth_ma.get_bandwidth_ma()
    
            if prev_upper is None or prev_lower is None or atr_value == 0 or bandwidth_ma == 0:
                return None
    
            # ── Bandwidth filter (squeeze condition) ─────────────────
            if bandwidth >= self.config.constant * bandwidth_ma:
                return None
    
            # ── Previous candle OHLC (the setup candle) ──────────────
            prev_open  = history.open[-2]
            prev_close = history.close[-2]
            prev_high  = history.high[-2]
            prev_low   = history.low[-2]
    
            # ── Adaptive filter — tighten after a losing trade ───────
            if self._last_trade_was_loss:
                if abs(prev_close - prev_open) <= self.config.adaptive_constant * atr_value:
                    return None
    
            # ── Candle validity (reject wicks that cross the band) ───
            valid_buy = (
                prev_open < prev_upper and
                prev_close > prev_upper
            )
            valid_sell = (
                prev_open > prev_lower and
                prev_close < prev_lower
            )
    
            # ── BUY signal ───────────────────────────────────────────
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
    
            # ── SELL signal ──────────────────────────────────────────
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
 
    def check_exit(self, pos: Position, snapshot: MarketSnapshot) -> bool:
        """
        Close a LONG when bid falls to/below the lower band.
        Close a SHORT when ask rises to/above the upper band.
        """
        prev_upper, prev_lower, _ = self.indicators.get_previous_bollinger_bands()
 
        if prev_upper is None or prev_lower is None:
            return False
 
        if pos.direction == Direction.LONG:
            return snapshot.tick.bid <= prev_lower
 
        if pos.direction == Direction.SHORT:
            return snapshot.tick.ask >= prev_upper
 
        return False
 
    # ─────────────────────────────────────────────────────────────
    # Post-trade state update
    # ─────────────────────────────────────────────────────────────
 
    def update_trade_result(self, trade) -> None:
        if trade.net_pnl is None:
            return
        self._last_trade_was_loss = trade.net_pnl < 0
 
    # ─────────────────────────────────────────────────────────────
    # Indicator snapshot (for DataLogger)
    # ─────────────────────────────────────────────────────────────
 
    def expose_indicator_values(self) -> dict:
        prev_upper, prev_lower, prev_middle = self.indicators.get_previous_bollinger_bands()
        return {
            "bb_upper":              prev_upper,
            "bb_lower":              prev_lower,
            "bb_middle":             prev_middle,
            "atr":                   self.indicators.get_atr(),
            "bandwidth":             self.indicators.get_bandwidth(),
            "bandwidth_ma":          self.bandwidth_ma.get_bandwidth_ma(),
            "adaptive_filter_active": self._last_trade_was_loss,
        }
 