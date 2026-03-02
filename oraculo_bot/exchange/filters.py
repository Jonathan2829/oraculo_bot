from typing import Dict, Tuple
import math

def get_precision(market: Dict) -> Tuple[float, float]:
    tick_size = 0.0
    step_size = 0.0
    info = market.get("info", {}) or {}
    filters = info.get("filters") or market.get("filters") or []
    for f in filters:
        ft = f.get("filterType")
        if ft == "PRICE_FILTER":
            tick_size = float(f.get("tickSize") or 0.0)
        elif ft == "LOT_SIZE":
            step_size = float(f.get("stepSize") or 0.0)
    prec = market.get("precision") or {}
    if tick_size <= 0:
        p = prec.get("price")
        if isinstance(p, int):
            tick_size = 10 ** (-p)
    if step_size <= 0:
        a = prec.get("amount")
        if isinstance(a, int):
            step_size = 10 ** (-a)
    if tick_size <= 0:
        tick_size = 0.00001
    if step_size <= 0:
        step_size = 0.00001
    return tick_size, step_size

def floor_to_step(x: float, step: float) -> float:
    if step <= 0:
        return float(x)
    return math.floor(x / step) * step

def round_price(price: float, tick_size: float) -> float:
    return float(floor_to_step(price, tick_size))

def round_amount(amount: float, step_size: float, min_qty: float = 0.0) -> float:
    rounded = float(floor_to_step(amount, step_size))
    if min_qty > 0 and rounded < min_qty:
        rounded = float(min_qty)
    return rounded