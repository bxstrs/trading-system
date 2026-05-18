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

    def __getitem__(self, item):
        if isinstance(item, str):
            return getattr(self, item)
        
        elif isinstance(item, tuple):
            key, index = item
            return getattr(self, key)[index]

        raise TypeError("Invalid key type")


@dataclass(frozen=True)
class MarketSnapshot:
    tick:               TickData
    history:            History | None = None
    is_full_refresh:    bool = False
