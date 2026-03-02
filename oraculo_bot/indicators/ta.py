# oraculo_bot/indicators/ta.py
from __future__ import annotations

from typing import List, Optional, Sequence


def _to_floats(x: Sequence[float]) -> List[float]:
    return [float(v) for v in x]


def sma(series: Sequence[float], period: int) -> List[Optional[float]]:
    """
    Simple Moving Average.
    Retorna lista del mismo largo con None hasta que haya datos suficientes.
    """
    s = _to_floats(series)
    n = len(s)
    if period <= 0 or n == 0:
        return [None] * n

    out: List[Optional[float]] = [None] * n
    csum = 0.0

    for i, v in enumerate(s):
        csum += v
        if i >= period:
            csum -= s[i - period]
        if i >= period - 1:
            out[i] = csum / period

    return out


def ema(series: Sequence[float], period: int) -> List[Optional[float]]:
    """
    Exponential Moving Average (EMA).
    Retorna lista del mismo largo. Primer valor usa el primer precio.
    """
    s = _to_floats(series)
    n = len(s)
    if period <= 0 or n == 0:
        return [None] * n

    k = 2.0 / (period + 1.0)
    out: List[Optional[float]] = [None] * n

    # Semilla EMA: primer valor de la serie
    ema_val = s[0]
    out[0] = ema_val

    for i in range(1, n):
        ema_val = (s[i] * k) + (ema_val * (1.0 - k))
        out[i] = ema_val

    return out


def _rma(values: Sequence[float], period: int) -> List[Optional[float]]:
    """
    Wilder's RMA (running moving average), equivalente a EMA con alpha=1/period.
    Retorna lista del mismo largo con None al inicio hasta periodo-1.
    """
    v = _to_floats(values)
    n = len(v)
    if period <= 0 or n == 0:
        return [None] * n

    out: List[Optional[float]] = [None] * n
    if n < period:
        return out

    # inicial: SMA de los primeros 'period'
    first = sum(v[:period]) / period
    out[period - 1] = first
    prev = first

    alpha = 1.0 / period
    for i in range(period, n):
        prev = (v[i] * alpha) + (prev * (1.0 - alpha))
        out[i] = prev

    return out


def rsi(closes: Sequence[float], period: int = 14) -> List[Optional[float]]:
    """
    RSI clásico con Wilder smoothing.
    Retorna lista del mismo largo con None al inicio.
    """
    c = _to_floats(closes)
    n = len(c)
    if period <= 0 or n == 0:
        return [None] * n
    if n < period + 1:
        return [None] * n

    # deltas
    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        d = c[i] - c[i - 1]
        gains[i] = d if d > 0 else 0.0
        losses[i] = (-d) if d < 0 else 0.0

    avg_gain = _rma(gains, period)
    avg_loss = _rma(losses, period)

    out: List[Optional[float]] = [None] * n
    for i in range(n):
        g = avg_gain[i]
        l = avg_loss[i]
        if g is None or l is None:
            out[i] = None
            continue
        if l == 0.0:
            out[i] = 100.0
            continue
        rs = g / l
        out[i] = 100.0 - (100.0 / (1.0 + rs))

    return out


def atr(ohlcv: Sequence[Sequence[float]], period: int = 14) -> List[Optional[float]]:
    """
    ATR (Average True Range) usando Wilder smoothing.
    ohlcv: lista de velas [ts, open, high, low, close, volume] o mínimo [*,*,high,low,close,*]
    Retorna lista del mismo largo con None al inicio.
    """
    n = len(ohlcv)
    if period <= 0 or n == 0:
        return [None] * n
    if n < 2:
        return [None] * n

    highs = [float(x[2]) for x in ohlcv]
    lows = [float(x[3]) for x in ohlcv]
    closes = [float(x[4]) for x in ohlcv]

    tr = [0.0] * n
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        h = highs[i]
        l = lows[i]
        pc = closes[i - 1]
        tr1 = h - l
        tr2 = abs(h - pc)
        tr3 = abs(l - pc)
        tr[i] = max(tr1, tr2, tr3)

    return _rma(tr, period)