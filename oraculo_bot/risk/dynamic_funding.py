import numpy as np
from collections import defaultdict
from typing import Dict, List, Optional
import time

class FundingFilter:
    def __init__(self, lookback_days: int = 7, p_high: int = 95, p_low: int = 5, db=None):
        self.lookback = lookback_days * 3
        self.p_high = p_high
        self.p_low = p_low
        self.db = db
        self.history: Dict[str, List[float]] = defaultdict(list)

    async def update(self, symbol: str, funding_rate: float):
        hist = self.history[symbol]
        hist.append(funding_rate)
        if len(hist) > self.lookback:
            hist.pop(0)
        if self.db:
            with self.db.connect() as con:
                con.execute("INSERT INTO funding_history (symbol, funding_rate, timestamp) VALUES (?, ?, ?)",
                            (symbol, funding_rate, int(time.time())))

    def is_allowed(self, symbol: str, side: str, funding_rate: float, mult: float = 1.0) -> bool:
        hist = self.history.get(symbol, [])
        if len(hist) < 20:
            return True

        arr = np.array(hist, dtype=float)

        if side == "LONG":
            threshold = np.percentile(arr, self.p_high)
            return funding_rate <= threshold * mult
        else:
            threshold = np.percentile(arr, self.p_low)
            if threshold < 0:
                threshold = threshold / mult
                return funding_rate >= threshold
            else:
                threshold = threshold * mult
                return funding_rate >= threshold