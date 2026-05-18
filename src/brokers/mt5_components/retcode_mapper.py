import MetaTrader5 as mt5
from src.domain.enums import ExecutionStatus


MT5_RETCODE_MAP = {
    mt5.TRADE_RETCODE_DONE:             ExecutionStatus.DONE,
    mt5.TRADE_RETCODE_REJECT:           ExecutionStatus.REJECTED,
    mt5.TRADE_RETCODE_DONE_PARTIAL:     ExecutionStatus.PARTIAL,
}


def map_retcode(retcode: int) -> ExecutionStatus:
    return MT5_RETCODE_MAP.get(retcode, ExecutionStatus.FAILED)