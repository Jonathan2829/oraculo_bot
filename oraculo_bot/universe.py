from typing import List
from .exchange.binance_client import BinanceClient

async def build_universe(ex: BinanceClient, price_max: float, max_symbols: int) -> List[str]:
    markets = await ex.fetch_markets()

    syms = []
    for m in markets:
        sym = m.get("symbol")
        if not sym or not sym.endswith("/USDT"):
            continue
        if not m.get("active", True):
            continue
        if any(x in sym for x in ["UP/", "DOWN/", "BULL/", "BEAR/"]):
            continue
        syms.append(sym)

    tickers = await ex.fetch_tickers(syms)
    filtered = []
    for sym in syms:
        t = tickers.get(sym) or {}
        last = t.get("last")
        if last is None:
            continue
        try:
            last = float(last)
        except Exception:
            continue
        if 0 < last <= price_max:
            filtered.append(sym)

    def vol_key(sym: str):
        t = tickers.get(sym) or {}
        v = t.get("quoteVolume")
        try:
            return float(v) if v is not None else 0.0
        except Exception:
            return 0.0

    filtered.sort(key=vol_key, reverse=True)
    return filtered[:max_symbols]