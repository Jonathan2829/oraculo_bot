# oraculo_bot/strategy/regime.py

from __future__ import annotations
from typing import Optional, List
import pandas as pd
import numpy as np


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df['high']
    low = df['low']
    close = df['close']

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df['high']
    low = df['low']
    close = df['close']

    plus_dm = high.diff()
    minus_dm = low.diff().abs()

    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0

    tr = _atr(df, period)

    plus_di = 100 * (plus_dm.rolling(period).mean() / tr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / tr)

    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx.rolling(period).mean()

    return adx


def _bbands(close: pd.Series, period: int = 20, std: float = 2.0):
    sma = close.rolling(period).mean()
    stddev = close.rolling(period).std()
    upper = sma + stddev * std
    lower = sma - stddev * std
    return upper, lower


def classify_regime(
    ohlcv,
    adx_period: int = 14,
    adx_threshold: int = 25,
    bb_period: int = 20,
    bb_std: float = 2.0
) -> Optional[str]:

    if len(ohlcv) < max(adx_period, bb_period) + 60:
        return None

    df = pd.DataFrame({
        'high': [x[2] for x in ohlcv],
        'low': [x[3] for x in ohlcv],
        'close': [x[4] for x in ohlcv],
    })

    adx_series = _adx(df, adx_period)
    if adx_series.isna().all():
        return None

    adx_value = float(adx_series.iloc[-1])

    upper, lower = _bbands(df['close'], bb_period, bb_std)
    width_series = (upper - lower) / df['close']
    width_now = float(width_series.iloc[-1])
    width_mean = float(width_series.rolling(50).mean().iloc[-1])

    trend = "TREND" if adx_value > adx_threshold else "RANGE"

    if width_now > width_mean * 1.2:
        vol = "EXPANDING"
    elif width_now < width_mean * 0.8:
        vol = "CONTRACTING"
    else:
        vol = "NEUTRAL"

    return f"{trend}_{vol}"


def is_trend(ohlcv, adx_period: int = 14, threshold: int = 25) -> bool:
    regime = classify_regime(ohlcv, adx_period=adx_period)
    if regime is None:
        return False
    return regime.startswith("TREND")


def is_volatility_expanding(
    ohlcv,
    bb_period: int = 20,
    bb_std: float = 2.0,
    factor: float = 1.2
) -> bool:

    regime = classify_regime(
        ohlcv,
        bb_period=bb_period,
        bb_std=bb_std
    )

    if regime is None:
        return False

    return "EXPANDING" in regime