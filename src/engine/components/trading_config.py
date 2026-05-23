import MetaTrader5 as mt5
 
from dataclasses       import dataclass
from src.config.loader import load_trading_yaml     # ← was: load_yaml
 
 
@dataclass(frozen=True)
class TradingConfig:
    """Immutable snapshot of configs/trading.yaml."""
    symbol:               str
    timeframe:            str
    timeframe_value:      int
    deviation:            int
    base_volume:          float
    tick_sleep:           float   # seconds (converted from tick_sleep_ms)
    rate_fetch_interval:  int     # seconds between full history refreshes
    bar_lookback:         int     # bars to fetch for indicator warmup
    checkpoint_interval:  int     # ticks between periodic checkpoint saves
    restart_delay:        int     # seconds between crash restarts
    max_restart_attempts: int     # -1 = unlimited
    max_fetch_attempts:   int     # max attempts to fetch market data before error
 
 
def load_trading_config() -> TradingConfig:
    """Load, validate, and return an immutable TradingConfig from trading.yaml."""
    raw = load_trading_yaml()     # ← validates before returning (was load_yaml, no validation)
 
    return TradingConfig(
        symbol               = raw.get("symbol",                 "ETHUSD#"),
        timeframe            = raw.get("timeframe",              "H4"),
        timeframe_value      = raw.get("timeframe_value",        mt5.TIMEFRAME_H4),
        deviation            = raw.get("deviation",              3),
        base_volume          = raw.get("base_volume",            0.1),
        tick_sleep           = raw.get("tick_sleep_ms",          100) / 1000.0,
        rate_fetch_interval  = raw.get("rate_fetch_interval_s",  1),
        bar_lookback         = raw.get("bar_lookback",           220),
        checkpoint_interval  = raw.get("checkpoint_interval_ticks", 100),
        restart_delay        = raw.get("restart_delay_seconds",  10),
        max_restart_attempts = raw.get("max_restart_attempts",   -1),
        max_fetch_attempts   = raw.get("max_fetch_attempts",     5),
    )