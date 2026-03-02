import time
from typing import List, Tuple, Optional
from ..config import Settings

class MetricsTracker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.trades: List[float] = []
        self.equity_curve: List[Tuple[float, float]] = []
        self.start_balance = settings.capital_usdt
        self.current_balance = settings.capital_usdt
        self.max_drawdown = 0.0
        self.daily_pnl = 0.0
        self.last_reset_day = time.localtime().tm_yday

    def update_balance(self, balance: float):
        self.current_balance = balance
        self.equity_curve.append((time.time(), balance))
        if len(self.equity_curve) > 1:
            peak = max(x[1] for x in self.equity_curve)
            dd = (peak - balance) / peak * 100
            if dd > self.max_drawdown:
                self.max_drawdown = dd

    def add_trade(self, pnl: float) -> None:
        self.trades.append(pnl)
        self.daily_pnl += pnl

    def check_limits(self) -> Optional[str]:
        if self.daily_pnl <= -self.settings.daily_max_loss_usdt:
            return "MAX_DAILY_LOSS"
        if self.max_drawdown > self.settings.max_drawdown_percent:
            return "MAX_DRAWDOWN"
        if len(self.trades) >= 10:
            wins = [p for p in self.trades if p > 0]
            losses = [-p for p in self.trades if p < 0]
            if losses:
                pf = (sum(wins) / sum(losses)) if sum(losses) > 0 else float('inf')
                if pf < 1.0:
                    return "PROFIT_FACTOR_BELOW_1"
        return None

    def reset_daily(self):
        self.daily_pnl = 0.0
        self.last_reset_day = time.localtime().tm_yday

    def get_metrics(self) -> dict:
        wins = [p for p in self.trades if p > 0]
        losses = [-p for p in self.trades if p < 0]
        profit_factor = (sum(wins) / sum(losses)) if sum(losses) > 0 else float('inf')
        return {
            "total_trades": len(self.trades),
            "winrate": len(wins) / len(self.trades) if self.trades else 0,
            "profit_factor": profit_factor,
            "max_drawdown": self.max_drawdown,
            "daily_pnl": self.daily_pnl,
            "balance": self.current_balance
        }