from typing import List, Optional
from dataclasses import dataclass

@dataclass
class Pivot:
    idx: int
    price: float
    kind: str  # "H" or "L"

@dataclass
class StructureState:
    bias: str  # "BULL", "BEAR", "RANGE"
    last_bos: Optional[str]  # "BULL_BOS", "BEAR_BOS", None
    bos_level: Optional[float]
    last_swing_high: Optional[float]
    last_swing_low: Optional[float]
    impulse_from: Optional[float]
    impulse_to: Optional[float]

def find_pivots(ohlcv, left: int = 2, right: int = 2) -> List[Pivot]:
    highs = [x[2] for x in ohlcv]
    lows = [x[3] for x in ohlcv]
    out = []
    for i in range(left, len(ohlcv) - right):
        h = highs[i]
        l = lows[i]
        is_ph = all(h > highs[i-j] for j in range(1, left+1)) and all(h > highs[i+j] for j in range(1, right+1))
        is_pl = all(l < lows[i-j] for j in range(1, left+1)) and all(l < lows[i+j] for j in range(1, right+1))
        if is_ph:
            out.append(Pivot(i, h, "H"))
        if is_pl:
            out.append(Pivot(i, l, "L"))
    out.sort(key=lambda p: p.idx)
    return out

def _last(pivots: List[Pivot], kind: str, n: int) -> List[Pivot]:
    xs = [p for p in pivots if p.kind == kind]
    return xs[-n:] if len(xs) >= n else xs

def detect_structure(ohlcv_15m, settings) -> StructureState:
    pivs = find_pivots(ohlcv_15m, left=settings.pivot_left, right=settings.pivot_right)
    hs = _last(pivs, "H", settings.bos_lookback_pivots)
    ls = _last(pivs, "L", settings.bos_lookback_pivots)

    if len(hs) < 2 or len(ls) < 2:
        return StructureState("RANGE", None, None, None, None, None, None)

    h1, h2 = hs[-2].price, hs[-1].price
    l1, l2 = ls[-2].price, ls[-1].price

    if h2 > h1 and l2 > l1:
        bias = "BULL"
    elif h2 < h1 and l2 < l1:
        bias = "BEAR"
    else:
        bias = "RANGE"

    closes = [x[4] for x in ohlcv_15m]
    last_close = closes[-1]
    last_swing_high = hs[-1].price
    last_swing_low = ls[-1].price

    last_bos = None
    bos_level = None
    impulse_from = None
    impulse_to = None

    if bias == "BULL" and last_close > last_swing_high:
        last_bos = "BULL_BOS"
        bos_level = last_swing_high
        impulse_from = last_swing_low
        impulse_to = last_close
    elif bias == "BEAR" and last_close < last_swing_low:
        last_bos = "BEAR_BOS"
        bos_level = last_swing_low
        impulse_from = last_swing_high
        impulse_to = last_close

    return StructureState(
        bias=bias,
        last_bos=last_bos,
        bos_level=bos_level,
        last_swing_high=last_swing_high,
        last_swing_low=last_swing_low,
        impulse_from=impulse_from,
        impulse_to=impulse_to,
    )

def pullback_ok(ohlcv_5m, side: str, impulse_from: float, impulse_to: float, settings) -> bool:
    if impulse_from is None or impulse_to is None:
        return False
    move = abs(impulse_to - impulse_from)
    if move <= 0:
        return False

    seg = ohlcv_5m[-60:] if len(ohlcv_5m) >= 60 else ohlcv_5m
    highs = [x[2] for x in seg]
    lows = [x[3] for x in seg]
    close = seg[-1][4]

    if side == "SHORT":
        retr = (max(highs) - impulse_to) / move
        return retr <= settings.pullback_max_retrace and close <= max(highs)
    else:
        retr = (impulse_to - min(lows)) / move
        return retr <= settings.pullback_max_retrace and close >= min(lows)