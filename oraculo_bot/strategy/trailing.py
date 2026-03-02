def pivots(ohlcv, left=2, right=2):
    highs = [x[2] for x in ohlcv]
    lows  = [x[3] for x in ohlcv]
    ph, pl = [], []
    for i in range(left, len(ohlcv)-right):
        h = highs[i]; l = lows[i]
        if all(h > highs[i-j] for j in range(1,left+1)) and all(h > highs[i+j] for j in range(1,right+1)):
            ph.append((i, h))
        if all(l < lows[i-j] for j in range(1,left+1)) and all(l < lows[i+j] for j in range(1,right+1)):
            pl.append((i, l))
    return ph, pl

def compute_new_sl(side: str, ohlcv, current_sl: float, entry: float, max_sl_pct: float = 0.05):
    ph, pl = pivots(ohlcv)
    last_price = ohlcv[-1][4] if ohlcv else None
    if last_price is None:
        return None

    buffer = 0.0005

    if side == "SHORT":
        candidates = [p for (_, p) in ph if (p < current_sl and p > last_price * (1 + buffer))]
        if not candidates:
            return None
        new_sl = min(candidates)
        if new_sl >= current_sl:
            return None
    else:
        candidates = [p for (_, p) in pl if (p > current_sl and p < last_price * (1 - buffer))]
        if not candidates:
            return None
        new_sl = max(candidates)
        if new_sl <= current_sl:
            return None

    sl_pct = abs((entry - new_sl) / entry) if entry else 1.0
    if sl_pct > max_sl_pct:
        return None

    return float(new_sl)