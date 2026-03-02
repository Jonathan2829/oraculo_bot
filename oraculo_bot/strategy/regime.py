# oraculo_bot/strategy/regime.py
from __future__ import annotations

from typing import Optional
import pandas as pd


def _true_range(df: pd.DataFrame) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def _wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    # Wilder smoothing ~ EMA alpha=1/period
    return series.ewm(alpha=1 / period, adjust=False).mean()


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    tr = _true_range(df)
    atr = _wilder_smooth(tr, period)

    plus_di = 100 * (_wilder_smooth(plus_dm, period) / atr)
    minus_di = 100 * (_wilder_smooth(minus_dm, period) / atr)

    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di)).fillna(0.0)
    adx = _wilder_smooth(dx, period)
    return adx


def _bbands(close: pd.Series, period: int = 20, std: float = 2.0):
    mid = close.rolling(period).mean()
    sd = close.rolling(period).std(ddof=0)
    upper = mid + std * sd
    lower = mid - std * sd
    return upper, lower


def classify_regime(
    ohlcv,
    adx_period: int = 14,
    adx_threshold: int = 25,
    bb_period: int = 20,
    bb_std: float = 2.0,
) -> Optional[str]:
    if len(ohlcv) < max(adx_period, bb_period) + 60:
        return None

    df = pd.DataFrame(
        {
            "high": [x[2] for x in ohlcv],
            "low": [x[3] for x in ohlcv],
            "close": [x[4] for x in ohlcv],
        }
    )

    adx = _adx(df, adx_period)
    if adx.isna().all():
        return None
    adx_now = float(adx.iloc[-1])

    upper, lower = _bbands(df["close"], bb_period, bb_std)
    width = (upper - lower) / df["close"]
    width_now = float(width.iloc[-1])
    width_mean = float(width.rolling(50).mean().iloc[-1])

    trend = "TREND" if adx_now > adx_threshold else "RANGE"

    if width_now > width_mean * 1.2:
        vol = "EXPANDING"
    elif width_now < width_mean * 0.8:
        vol = "CONTRACTING"
    else:
        vol = "NEUTRAL"

    return f"{trend}_{vol}"


def is_trend(ohlcv, adx_period: int = 14, threshold: int = 25) -> bool:
    r = classify_regime(ohlcv, adx_period=adx_period, adx_threshold=threshold)
    return bool(r and r.startswith("TREND"))


def is_volatility_expanding(
    ohlcv, bb_period: int = 20, bb_std: float = 2.0, factor: float = 1.2
) -> bool:
    if len(ohlcv) < bb_period + 50:
        return False

    df = pd.DataFrame({"close": [x[4] for x in ohlcv]})
    upper, lower = _bbands(df["close"], bb_period, bb_std)
    width = (upper - lower) / df["close"]
    width_now = float(width.iloc[-1])
    width_mean = float(width.rolling(50).mean().iloc[-1])
    return width_now > width_mean * factor