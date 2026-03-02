import pandas as pd
import pandas_ta as ta
from typing import List, Optional

def ohlcv_to_df(ohlcv):
    return pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])

def ema(series: List[float], period: int) -> List[Optional[float]]:
    if len(series) < period:
        return [None] * len(series)
    s = pd.Series(series)
    out = ta.ema(s, length=period)
    return out.to_list()

def rsi(series: List[float], period: int = 14) -> List[Optional[float]]:
    if len(series) < period:
        return [None] * len(series)
    s = pd.Series(series)
    out = ta.rsi(s, length=period)
    return out.to_list()

def atr(high: List[float], low: List[float], close: List[float], period: int = 14) -> List[Optional[float]]:
    if len(close) < period:
        return [None] * len(close)
    df = pd.DataFrame({"high": high, "low": low, "close": close})
    out = ta.atr(df["high"], df["low"], df["close"], length=period)
    return out.to_list()