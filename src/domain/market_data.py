from dataclasses import dataclass
from datetime import datetime
from domain.enums import Direction

@dataclass(slots=True)
class TickData:
    symbol:     str
    bid:        float
    ask:        float
    last:       float
    volume:     float
    time:       datetime


@dataclass
class History:
    symbol:         str
    timeframe:      int
    time_unix:      list
    open:           list
    high:           list
    low:            list
    close:          list
    tick_volume:    list
    real_volume:    list | None = None


@dataclass(frozen=True)
class MarketSnapshot:
    tick:               TickData
    history:            History | None = None
    is_full_refresh:    bool = False


@dataclass(slots=True)
class MarketState:
    symbol:     str
    interval:   str
    timestamp:  datetime
    open:       float
    high:       float
    low:        float
    close:      float
    volume:     float | None
    bid:        float | None    
    ask:        float | None

    def __post_init__(self):
        """Validate market state."""
        if self.high < self.low:
            raise ValueError("High must be >= Low")
        if self.close < 0 or self.open < 0:
            raise ValueError("Prices must be non-negative")

