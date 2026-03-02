from dataclasses import dataclass
from typing import List, Optional

@dataclass
class Zone:
    kind: str          # "SUPPLY" o "DEMAND"
    low: float
    high: float
    pivot_idx: int
    pivot_price: float

def _last_pivots(pivots, kind: str, n: int):
    xs = [p for p in pivots if p.kind == kind]
    return xs[-n:] if len(xs) >= n else xs

def build_zones_from_pivots(pivots, atr_abs: float, k: float = 0.35, max_zones_each: int = 2) -> List[Zone]:
    zones: List[Zone] = []
    w = max(atr_abs * k, 0.0)
    if w <= 0:
        return zones

    highs = _last_pivots(pivots, "H", max_zones_each)
    lows  = _last_pivots(pivots, "L", max_zones_each)

    for p in highs:
        zones.append(Zone("SUPPLY", low=float(p.price - w), high=float(p.price + w),
                          pivot_idx=int(p.idx), pivot_price=float(p.price)))
    for p in lows:
        zones.append(Zone("DEMAND", low=float(p.price - w), high=float(p.price + w),
                          pivot_idx=int(p.idx), pivot_price=float(p.price)))

    return zones

def in_zone(price: float, z: Zone) -> bool:
    return z.low <= price <= z.high

def pick_nearest_zone(price: float, zones: List[Zone], kind: str) -> Optional[Zone]:
    zs = [z for z in zones if z.kind == kind]
    if not zs:
        return None
    def dist(z: Zone):
        mid = (z.low + z.high) / 2.0
        return abs(price - mid)
    zs.sort(key=dist)
    return zs[0]

def rejection_ok(
    side: str,
    ohlcv_5m: List[List[float]],
    zone: Zone,
    min_wick_ratio: float = 0.45,
    require_close_back_in: bool = True
) -> bool:
    if not ohlcv_5m or len(ohlcv_5m) < 3:
        return False

    candle = ohlcv_5m[-2]
    o = float(candle[1]); h = float(candle[2]); l = float(candle[3]); c = float(candle[4])
    rng = max(h - l, 1e-12)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    mid = (zone.low + zone.high) / 2.0
    touched = (h >= zone.low and l <= zone.high)
    if not touched:
        return False

    if side == "SHORT":
        if (upper_wick / rng) < min_wick_ratio:
            return False
        if require_close_back_in and c > zone.high:
            return False
        if c > mid:
            return False
        return True
    else:  # LONG
        if (lower_wick / rng) < min_wick_ratio:
            return False
        if require_close_back_in and c < zone.low:
            return False
        if c < mid:
            return False
        return True