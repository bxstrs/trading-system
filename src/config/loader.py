import yaml
from pathlib import Path
from src.infrastructure.logger.logger import log


BASE_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "configs"


def load_yaml(relative_path: str) -> dict:
    """Load any YAML config file. Returns raw dict — caller is responsible for validation."""
    path = BASE_CONFIG_PATH / relative_path

    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    with open(path, "r") as f:
        config = yaml.safe_load(f)

    if not config:
        raise ValueError(f"Config file is empty: {path}")

    return config


def load_trading_yaml() -> dict:
    """Load and validate trading.yaml. Raises ValueError on bad config."""
    config = load_yaml("trading.yaml")
    validate_trading_config(config)
    return config


def load_risk_yaml() -> dict:
    """Load and validate risk.yaml. Raises ValueError on bad config."""
    config = load_yaml("risk.yaml")
    validate_risk_config(config)
    return config


def validate_trading_config(config: dict) -> None:
    """Validate trading.yaml has required fields and correct types."""
    required_fields = ["symbol", "timeframe", "timeframe_value", "deviation", "base_volume"]
    missing = [f for f in required_fields if f not in config]

    if missing:
        raise ValueError(f"trading.yaml missing required fields: {missing}")

    symbol          = config.get("symbol")
    base_volume     = config.get("base_volume")
    timeframe_value = config.get("timeframe_value")

    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError(f"trading.yaml: 'symbol' must be a non-empty string, got {symbol!r}")

    if not isinstance(base_volume, (int, float)):
        raise ValueError(
            f"trading.yaml: 'base_volume' must be a number, got {type(base_volume).__name__}. "
            f"Check for accidental quoting: base_volume: 0.1 not base_volume: '0.1'"
        )

    if base_volume <= 0:
        raise ValueError(f"trading.yaml: 'base_volume' must be > 0, got {base_volume}")

    if not (0.01 <= float(base_volume) <= 10.0):
        raise ValueError(
            f"trading.yaml: 'base_volume' must be between 0.01 and 10.0 lots, got {base_volume}"
        )

    if not isinstance(timeframe_value, int):
        raise ValueError(
            f"trading.yaml: 'timeframe_value' must be a valid MT5 integer constant, "
            f"got {type(timeframe_value).__name__}: {timeframe_value!r}"
        )

    log(
        f"[CONFIG] trading.yaml validated: symbol={symbol}, "
        f"volume={base_volume}, timeframe={timeframe_value}",
        level="DEBUG",
    )


def validate_risk_config(config: dict) -> None:
    """Validate risk.yaml has required fields and correct types."""
    required_fields = ["risk_per_trade", "max_consecutive_losses", "max_drawdown"]
    missing = [f for f in required_fields if f not in config]

    if missing:
        raise ValueError(f"risk.yaml missing required fields: {missing}")

    risk_per_trade = config.get("risk_per_trade")

    if not isinstance(risk_per_trade, (int, float)):
        raise ValueError(
            f"risk.yaml: 'risk_per_trade' must be a number, got {type(risk_per_trade).__name__}"
        )

    if not (0 < risk_per_trade < 1):
        raise ValueError(
            f"risk.yaml: 'risk_per_trade' must be between 0 and 1 (exclusive), got {risk_per_trade}"
        )

    max_consecutive_losses = config.get("max_consecutive_losses")
    if not isinstance(max_consecutive_losses, int) or max_consecutive_losses < 1:
        raise ValueError(
            f"risk.yaml: 'max_consecutive_losses' must be a positive integer, "
            f"got {max_consecutive_losses!r}"
        )

    log(
        f"[CONFIG] risk.yaml validated: risk_per_trade={risk_per_trade}, "
        f"max_consecutive_losses={max_consecutive_losses}",
        level="DEBUG",
    )