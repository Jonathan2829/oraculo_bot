def position_size_usdt(capital: float, risk_per_trade: float, entry: float, sl: float,
                       leverage: int, max_utilization: float = 0.8) -> float:
    risk_usdt = capital * risk_per_trade
    sl_dist = abs(entry - sl)
    if sl_dist <= 0:
        return 0.0
    qty = risk_usdt / sl_dist
    size_usdt = qty * entry
    max_notional = capital * leverage * max_utilization
    if size_usdt > max_notional:
        size_usdt = max_notional
    return max(0.0, float(size_usdt))

def r_multiple_estimate(side: str, entry: float, sl: float, tp2: float, outcome: str) -> float:
    r = abs(entry - sl)
    if r <= 0:
        return 0.0
    if outcome == "SL":
        return -1.0
    if outcome == "TP2":
        return abs(tp2 - entry) / r
    if outcome == "TP1":
        return 1.0
    return 0.0