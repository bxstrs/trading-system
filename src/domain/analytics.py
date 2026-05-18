from dataclasses import dataclass
from datetime import datetime
from src.domain.enums import PredictionDecision


@dataclass
class PortfolioStats:
    timestamp:          datetime
    strategy_id:        str
    symbol:             str

    total_trades:       int = 0
    wins:               int = 0
    losses:             int = 0
    consecutive_wins:   int = 0
    consecutive_losses: int = 0

    max_drawdown:       float = 0.0
    current_drawdown:   float = 0.0
    profit_factor:      float = 0.0  # Gross Profit / Gross Loss

    avg_win:            float = 0.0
    avg_loss:           float = 0.0
    payoff_ratio:       float = 0.0  # Avg Win / Avg Loss

    win_rate:           float = 0.0  # wins / total_trades
    expected_payoff:    float = 0.0  # (Avg Win × Win% - Avg Loss × Loss%)

    daily_pnl:          float = 0.0
    cumulative_pnl:     float = 0.0


@dataclass
class Prediction:
    prediction_id:      str
    signal_id:          str
    strategy_id:        str
    symbol:             str

    probability:        float  # 0.00 to 1.00 (likelihood signal is good)
    decision:           PredictionDecision
    model_name:         str
    notes:              str | None = None

    def __post_init__(self):
        """Validate prediction."""
        if not 0.00 <= self.probability <= 1.00:
            raise ValueError("Probability must be between 0.00 and 1.00")