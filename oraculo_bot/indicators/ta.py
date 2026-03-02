# oraculo_bot/indicators/ta.py
from __future__ import annotations

from typing import List, Optional


def ema(values: List[float], period: int) -> List[Optional[float]]:
    """
    Exponential Moving Average (EMA).
    Returns list same length as values; initial values are None until enough data.
    """
    if period <= 0:
        raise ValueError("period must be > 0")
    if not values:
        return []

    out: List[Optional[float]] = [None] * len(values)
    k = 2 / (period + 1)

    # Seed with SMA of first 'period'
    if len(values) < period:
        return out

    sma = sum(values[:period]) / period
    out[period - 1] = sma
    prev = sma

    for i in range(period, len(values)):
        prev = (values[i] - prev) * k + prev
        out[i] = prev

    return out


def atr(ohlcv: List[list], period: int) -> List[Optional[float]]:
    """
    Average True Range (ATR) using Wilder's smoothing.
    ohlcv rows: [timestamp, open, high, low, close, volume]
    Returns list same length as ohlcv; initial values are None.
    """
    if period <= 0:
        raise ValueError("period must be > 0")
    n = len(ohlcv)
    if n == 0:
        return []

    highs = [float(x[2]) for x in ohlcv]
    lows  = [float(x[3]) for x in ohlcv]
    closes = [float(x[4]) for x in ohlcv]

    tr: List[float] = [0.0] * n
    tr[0] = highs[0] - lows[0]

    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hc, lc)

    out: List[Optional[float]] = [None] * n
    if n < period + 1:
        return out

    # First ATR = SMA(TR[1..period]) (often TR[0] excluded; we use TR[1:period+1])
    first = sum(tr[1:period + 1]) / period
    out[period] = first
    prev = first

    # Wilder smoothing
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev

    return out