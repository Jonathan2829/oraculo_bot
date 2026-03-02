from dataclasses import dataclass
from typing import List
from ..indicators.ta import atr, rsi

@dataclass
class MomentumState:
    ok: bool
    atr_pct: float
    atr_abs: float
    vol_rel: float
    body_pct: float
    atr_expand: float
    rsi: float
    reason: List[str]

def momentum_5m(ohlcv_5m, settings) -> MomentumState:
    closes = [x[4] for x in ohlcv_5m]
    highs = [x[2] for x in ohlcv_5m]
    lows = [x[3] for x in ohlcv_5m]
    opens = [x[1] for x in ohlcv_5m]
    vols = [x[5] for x in ohlcv_5m]

    close = closes[-1]
    body = abs(closes[-1] - opens[-1])
    body_pct = body / close if close else 0.0

    a = atr(highs, lows, closes, settings.atr_period)
    a_now = a[-1] if a else None
    atr_pct = (a_now / close) if (a_now and close) else 0.0

    if len(vols) >= 20:
        vol_sma = sum(vols[-20:]) / 20
        vol_rel = vols[-1] / vol_sma if vol_sma > 0 else 1.0
    else:
        vol_rel = 1.0

    a_clean = [x for x in a if x is not None] if a else []
    if len(a_clean) >= 20 and a_now is not None:
        a_sma = sum(a_clean[-20:]) / 20
        atr_expand = a_now / a_sma if a_sma > 0 else 1.0
    else:
        atr_expand = 1.0

    rr = rsi(closes, 14)
    rsi_now = rr[-1] if rr else 50.0

    reasons = []
    ok = True

    if atr_pct < settings.atr_pct_min:
        ok = False; reasons.append(f"ATR% bajo ({atr_pct*100:.2f}%)")
    if vol_rel < settings.vol_rel_min:
        ok = False; reasons.append(f"Volumen débil (x{vol_rel:.2f})")
    if body_pct < settings.body_pct_min:
        ok = False; reasons.append(f"Vela sin fuerza (cuerpo {body_pct*100:.2f}%)")
    if atr_expand < settings.atr_expand_min:
        ok = False; reasons.append(f"ATR no expande (x{atr_expand:.2f})")
    if settings.rsi_neutral_low <= rsi_now <= settings.rsi_neutral_high:
        ok = False; reasons.append(f"RSI neutro ({rsi_now:.1f})")

    return MomentumState(
        ok=ok,
        atr_pct=float(atr_pct),
        atr_abs=float(a_now) if a_now else 0.0,
        vol_rel=float(vol_rel),
        body_pct=float(body_pct),
        atr_expand=float(atr_expand),
        rsi=float(rsi_now),
        reason=reasons,
    )