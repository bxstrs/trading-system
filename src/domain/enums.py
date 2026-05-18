from enum import Enum

class Direction(str, Enum):
    LONG    = "LONG"
    SHORT   = "SHORT"


class OrderType(str, Enum):
    BUY             = "BUY"
    SELL            = "SELL"
    BUY_LIMIT       = "BUY_LIMIT"
    SELL_LIMIT      = "SELL_LIMIT"
    BUY_STOP        = "BUY_STOP"
    SELL_STOP       = "SELL_STOP"
    BUY_STOP_LIMIT  = "BUY_STOP_LIMIT"
    SELL_STOP_LIMIT = "SELL_STOP_LIMIT"


class TradeStatus(str, Enum):
    OPEN        = "OPEN"
    CLOSED      = "CLOSED"
    FAILED      = "FAILED"
    PENDING     = "PENDING"


class ExecutionStatus(str, Enum):
    DONE        = "DONE"
    REJECTED    = "REJECTED"
    PARTIAL     = "PARTIAL"
    FAILED      = "FAILED"


class PredictionDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    
