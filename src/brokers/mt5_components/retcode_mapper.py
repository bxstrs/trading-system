import MetaTrader5 as mt5
from src.domain.enums import ExecutionStatus


MT5_RETCODE_MAP = {
    mt5.TRADE_RETCODE_DONE:             ExecutionStatus.DONE,
    mt5.TRADE_RETCODE_REJECT:           ExecutionStatus.REJECTED,
    mt5.TRADE_RETCODE_DONE_PARTIAL:     ExecutionStatus.PARTIAL,
}


def map_retcode(retcode: int) -> ExecutionStatus:
    return MT5_RETCODE_MAP.get(retcode, ExecutionStatus.FAILED)


DEAL_REASON_MAP = {
    0: "manual_close",  # DEAL_REASON_CLIENT
    1: "manual_close",  # DEAL_REASON_MOBILE
    2: "manual_close",  # DEAL_REASON_WEB
    3: "expert",        # DEAL_REASON_EXPERT
    4: "sl_hit",        # DEAL_REASON_SL
    5: "tp_hit",        # DEAL_REASON_TP
    6: "stop_out",      # DEAL_REASON_SO
}


def map_deal_reason(reason: int) -> str:
    return DEAL_REASON_MAP.get(reason, "manual_close")