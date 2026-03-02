from time import time
from ..indicators.ta import ema, atr
from .structure import detect_structure, pullback_ok, find_pivots
from .momentum import momentum_5m
from .risk import position_size_usdt
from .zones import build_zones_from_pivots, pick_nearest_zone, rejection_ok
from .regime import classify_regime
from .session import is_session_allowed

def _last_valid(values):
    if not values:
        return None
    for v in reversed(values):
        if v is not None:
            return v
    return None

async def compute_signal(symbol, settings, market_data, funding_filter=None):
    o5 = await market_data.get_ohlcv(symbol, settings.tf_trigger, 400)
    o15 = await market_data.get_ohlcv(symbol, settings.tf_trend, 400)
    o1h = await market_data.get_ohlcv(symbol, settings.tf_confirm, 400)

    if not all([o5, o15, o1h]):
        return None
    if len(o5) < 5 or len(o1h) < 60 or len(o15) < 120:
        return None

    c1h = [x[4] for x in o1h]
    ema20_1h = _last_valid(ema(c1h, 20))
    ema50_1h = _last_valid(ema(c1h, 50))
    if ema20_1h is None or ema50_1h is None:
        return None
    if ema20_1h == ema50_1h:
        return None
    conf_trend = "BULL" if ema20_1h > ema50_1h else "BEAR"

    structure = detect_structure(o15, settings)
    if structure.bias == "RANGE" or structure.last_bos not in ("BULL_BOS", "BEAR_BOS"):
        return None

    side = "LONG" if structure.last_bos == "BULL_BOS" else "SHORT"

    if (side == "LONG" and conf_trend != "BULL") or (side == "SHORT" and conf_trend != "BEAR"):
        return None

    regime = classify_regime(o1h, adx_period=14, adx_threshold=settings.adx_threshold)
    if regime is None:
        return None
    if "RANGE" in regime:
        if not settings.allow_range_trades:
            return None
        if "CONTRACTING" in regime:
            return None

    if not is_session_allowed(settings.session_ranges):
        return None

    if funding_filter is not None:
        funding_info = await market_data.get_funding_rate(symbol)
        if isinstance(funding_info, dict) and "fundingRate" in funding_info and funding_info["fundingRate"] is not None:
            rate = float(funding_info["fundingRate"])
            await funding_filter.update(symbol, rate)
            if not funding_filter.is_allowed(symbol, side, rate):
                return None

    ticker = await market_data.get_ticker(symbol)
    bid = ticker.get("bid")
    ask = ticker.get("ask")
    if bid is None or ask is None or bid <= 0:
        return None
    spread_pct = (ask - bid) / bid  # fracción (ej: 0.003 = 0.3%)
    if spread_pct > settings.max_spread_pct:
        return None

    pivs_15 = find_pivots(o15, left=settings.pivot_left, right=settings.pivot_right)
    if not pivs_15:
        return None

    h15 = [x[2] for x in o15]
    l15 = [x[3] for x in o15]
    c15 = [x[4] for x in o15]
    atr15 = _last_valid(atr(h15, l15, c15, settings.atr_period))
    if atr15 is None or atr15 <= 0:
        return None

    zones = build_zones_from_pivots(pivs_15, float(atr15), k=settings.zone_width_k, max_zones_each=2)
    if not zones:
        return None

    price = o5[-2][4]
    if price is None or price <= 0:
        return None

    z_kind = "DEMAND" if side == "LONG" else "SUPPLY"
    z = pick_nearest_zone(price, zones, z_kind)
    if not z:
        return None

    z_low = float(min(z.low, z.high))
    z_high = float(max(z.low, z.high))

    candle_touch = o5[-2]
    last_h = candle_touch[2]
    last_l = candle_touch[3]
    if last_h is None or last_l is None:
        return None
    if not (last_h >= z_low and last_l <= z_high):
        return None

    if not rejection_ok(
        side, o5, z,
        min_wick_ratio=settings.rejection_min_wick,
        require_close_back_in=settings.rejection_require_close_in
    ):
        return None

    mom = momentum_5m(o5, settings)
    if not mom.ok:
        return None

    if not pullback_ok(o5, side, structure.impulse_from, structure.impulse_to, settings):
        return None

    atr_ref = float(mom.atr_abs) if getattr(mom, "atr_abs", None) and mom.atr_abs > 0 else float(atr15)
    if atr_ref <= 0:
        return None

    zbuf = float(settings.zone_sl_buffer)
    if zbuf <= 0:
        zbuf = 0.25

    atr_buf = atr_ref * zbuf
    if side == "LONG":
        sl = z_low - atr_buf
    else:
        sl = z_high + atr_buf

    if (side == "LONG" and sl >= price) or (side == "SHORT" and sl <= price):
        return None

    sl_pct = abs((price - sl) / price)
    if sl_pct > settings.max_sl_pct:
        return None

    score = 70
    if mom.vol_rel >= settings.vol_rel_min * 1.5:
        score += 10
    if mom.atr_expand >= settings.atr_expand_min * 1.2:
        score += 10
    score += 10
    score = min(100, score)

    if score < settings.score_min:
        return None

    tp1 = price + atr_ref if side == "LONG" else price - atr_ref
    tp2 = price + settings.tp2_r_mult * atr_ref if side == "LONG" else price - settings.tp2_r_mult * atr_ref

    size_usdt = position_size_usdt(
        settings.capital_usdt, settings.risk_per_trade, price, sl,
        settings.leverage, max_utilization=0.8
    )

    return {
        "symbol": symbol,
        "side": side,
        "score": int(score),
        "entry": float(price),
        "sl": float(sl),
        "tp1": float(tp1),
        "tp2": float(tp2),
        "sl_pct": float(sl_pct),
        "size_usdt": float(size_usdt),
        "leverage": int(settings.leverage),
        "timestamp": int(time()),
        "zone_kind": z.kind,
        "zone_low": float(z_low),
        "zone_high": float(z_high),
        "atr_expand": float(mom.atr_expand),
        "spread_pct": float(spread_pct),
    }