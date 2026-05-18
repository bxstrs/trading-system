from dataclasses import dataclass
from datetime import datetime
from domain.enums import Direction, TradeStatus, ExecutionStatus


@dataclass
class Signal:
    signal_id:      str
    strategy_id:    str
    symbol:         str
    timestamp:      datetime
    direction:      Direction
    entry_price:    float # Intended entry price.
    notes:          str | None = None


@dataclass(slots=True)
class Position:
    ticket:     int
    time:       datetime
    symbol:     str
    direction:  Direction
    volume:     float
    open_price: float
    sl:         float | None
    tp:         float | None


@dataclass
class TradeSetup:
    setup_id:               str
    strategy_id:            str
    symbol:                 str
    timestamp:              datetime

    direction:              Direction
    trigger_price:          float
    
    # Indicator should be optional in case multi-strategy
    bb_upper:               float | None
    bb_lower:               float | None
    bb_middle:              float | None
    bandwidth:              float | None 
    bandwidth_ma:           float | None
    atr:                    float | None
    spread:                 float | None

    intended_entry_price:   float
    intended_volume:        float

    hour_of_day:            int
    candle_open:            float
    candle_high:            float
    candle_low:             float
    candle_close:           float

    timeframe:              str             = "H4"
    prev_trade_pnl:         float | None    = None
    adaptive_filter_active: bool            = False


@dataclass
class TradeExecution:
    setup_id:               str | None
    position_id:            int
    fill_price:             float
    fill_volume:            float
    fill_time:              datetime | None
    slippage:               float | None
    latency_ms:             float | None
    status:                 ExecutionStatus


@dataclass
class TradeResult:
    position_id:            str
    symbol:                 str
    direction:              Direction

    entry_price:            float
    entry_time:             datetime
    volume:                 float
    entry_slippage:         float
    entry_latency_ms:       float

    exit_price:             float | None    = None
    exit_time:              datetime | None = None
    exit_reason:            str | None      = None
    exit_bid:               float | None    = None
    exit_ask:               float | None    = None

    gross_pnl:              float = 0.0
    fees:                   float = 0.0
    net_pnl:                float = 0.0

    duration_minutes:       float | None    = None
    risk_reward_ratio:      float | None    = None

    max_adverse_excursion:  float | None    = None
    max_favorable_excursion:float | None    = None
    is_recovered:           bool            = False
    status:                 TradeStatus     = TradeStatus.PENDING

    def __post_init__(self):
        """Validate trade result."""
        if self.volume <= 0:
            raise ValueError("Volume must be positive")
        if self.status == "CLOSED":
            if self.exit_price is None or self.exit_time is None:
                raise ValueError("Closed trades must have exit_price and exit_time")
            

@dataclass
class TradeHistory:
    ticket:             int
    position_id:        int
    symbol:             str 
    timestamp:          datetime
    volume:             float
    price:              float
    commission:         float   = 0.0
    swap:               float   = 0.0
    profit:             float   = 0.0
    fee:                float   = 0.0