import pandas as pd
import pandas_ta as ta
from typing import Optional

def classify_regime(ohlcv, adx_period: int = 14, adx_threshold: int = 25,
                    bb_period: int = 20, bb_std: float = 2.0) -> Optional[str]:
    if len(ohlcv) < max(adx_period, bb_period) + 60:
        return None

    df = pd.DataFrame({
        'high': [x[2] for x in ohlcv],
        'low':  [x[3] for x in ohlcv],
        'close':[x[4] for x in ohlcv],
    })

    adx_df = ta.adx(df['high'], df['low'], df['close'], length=adx_period)
    if adx_df is None or adx_df.empty:
        return None
    adx = float(adx_df[f'ADX_{adx_period}'].iloc[-1])

    bb = ta.bbands(df['close'], length=bb_period, std=bb_std)
    if bb is None or bb.empty:
        return None

    width_series = (bb[f'BBU_{bb_period}_{bb_std}'] - bb[f'BBL_{bb_period}_{bb_std}']) / df['close']
    width_now = float(width_series.iloc[-1])
    width_mean = float(width_series.rolling(50).mean().iloc[-1])

    trend = "TREND" if adx > adx_threshold else "RANGE"

    if width_now > width_mean * 1.2:
        vol = "EXPANDING"
    elif width_now < width_mean * 0.8:
        vol = "CONTRACTING"
    else:
        vol = "NEUTRAL"

    return f"{trend}_{vol}"

def is_trend(ohlcv, adx_period: int = 14, threshold: int = 25) -> bool:
    if len(ohlcv) < adx_period + 60:
        return False
    df = pd.DataFrame({
        'high': [x[2] for x in ohlcv],
        'low': [x[3] for x in ohlcv],
        'close': [x[4] for x in ohlcv]
    })
    adx_df = ta.adx(df['high'], df['low'], df['close'], length=adx_period)
    if adx_df is None or adx_df.empty:
        return False
    adx = float(adx_df[f'ADX_{adx_period}'].iloc[-1])
    return adx > threshold

def is_volatility_expanding(ohlcv, bb_period: int = 20, bb_std: float = 2.0, factor: float = 1.2) -> bool:
    if len(ohlcv) < bb_period + 50:
        return False
    df = pd.DataFrame({'close': [x[4] for x in ohlcv]})
    bb = ta.bbands(df['close'], length=bb_period, std=bb_std)
    if bb is None or bb.empty:
        return False
    width_series = (bb[f'BBU_{bb_period}_{bb_std}'] - bb[f'BBL_{bb_period}_{bb_std}']) / df['close']
    width_now = float(width_series.iloc[-1])
    width_mean = float(width_series.rolling(50).mean().iloc[-1])
    return width_now > width_mean * factor