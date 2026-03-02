import asyncio
import logging
from typing import Dict, Optional

from ..exchange.binance_client import BinanceClient
from ..exchange.filters import get_precision, round_price, round_amount
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import ccxt

log = logging.getLogger(__name__)


class OrderManager:
    def __init__(self, client: BinanceClient):
        self.client = client
        self._markets: Optional[dict] = None

    async def _ensure_markets(self):
        if self._markets is None:
            self._markets = await self.client.load_markets()

    async def _get_precision_and_min(self, symbol: str):
        # ✅ CRÍTICO: normalizar símbolo (ADA/USDT -> ADA/USDT:USDT en futures, si aplica)
        symbol = await self.client.normalize_symbol(symbol)

        await self._ensure_markets()
        market = (self._markets or {}).get(symbol)
        if not market:
            # Fallback por si markets cacheó antes de normalizar (raro, pero posible)
            await self.client.load_markets(reload=True)
            self._markets = await self.client.load_markets()
            market = (self._markets or {}).get(symbol)

        if not market:
            raise ValueError(f"Symbol {symbol} not found in markets")

        tick_size, step_size = get_precision(market)
        min_qty = market.get("limits", {}).get("amount", {}).get("min", 0.0)
        min_notional = market.get("limits", {}).get("cost", {}).get("min", 0.0)
        return symbol, tick_size, step_size, float(min_qty or 0.0), float(min_notional or 0.0)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(ccxt.NetworkError) | retry_if_exception_type(ccxt.ExchangeError),
    )
    async def place_entry(self, symbol: str, side: str, price: float, quantity: float, post_only: bool = True) -> dict:
        symbol, tick_size, step_size, min_qty, min_notional = await self._get_precision_and_min(symbol)

        price_rounded = round_price(price, tick_size)
        qty_rounded = round_amount(quantity, step_size, min_qty)

        if qty_rounded <= 0:
            raise ValueError("Quantity rounded to zero")

        notional = price_rounded * qty_rounded
        if min_notional > 0 and notional < min_notional:
            raise ValueError(f"Notional {notional:.6f} below minimum {min_notional}")

        params = {"timeInForce": "GTX"} if post_only else {"timeInForce": "GTC"}
        return await self.client.create_limit_order(symbol, side, qty_rounded, price_rounded, params)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(ccxt.NetworkError) | retry_if_exception_type(ccxt.ExchangeError),
    )
    async def place_market_order(self, symbol: str, side: str, quantity: float, params: Dict = None) -> dict:
        symbol, _, step_size, min_qty, min_notional = await self._get_precision_and_min(symbol)

        qty_rounded = round_amount(quantity, step_size, min_qty)
        if qty_rounded <= 0:
            raise ValueError("Quantity rounded to zero")

        # Validar notional con precio actual (si el exchange lo exige)
        if min_notional > 0:
            ticker = await self.client.fetch_ticker(symbol)
            last = ticker.get("last") or ticker.get("mark") or (ticker.get("info", {}) or {}).get("markPrice")
            if last is not None:
                last = float(last)
                notional = last * qty_rounded
                if notional < min_notional:
                    raise ValueError(f"Notional {notional:.6f} below minimum {min_notional}")

        return await self.client.create_market_order(symbol, side, qty_rounded, params or {"reduceOnly": False})

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(ccxt.NetworkError) | retry_if_exception_type(ccxt.ExchangeError),
    )
    async def place_stop_loss(self, symbol: str, side: str, stop_price: float, quantity: float) -> dict:
        symbol, tick_size, step_size, min_qty, _ = await self._get_precision_and_min(symbol)

        stop_rounded = round_price(stop_price, tick_size)
        qty_rounded = round_amount(quantity, step_size, 0.0)

        if min_qty > 0 and qty_rounded < min_qty:
            raise ValueError(f"Stop loss quantity {qty_rounded} below minimum {min_qty}")

        return await self.client.create_stop_market_order(
            symbol, side, qty_rounded, stop_rounded, {"reduceOnly": True}
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(ccxt.NetworkError) | retry_if_exception_type(ccxt.ExchangeError),
    )
    async def place_take_profit_limit(self, symbol: str, side: str, price: float, quantity: float) -> dict:
        symbol, tick_size, step_size, min_qty, _ = await self._get_precision_and_min(symbol)

        price_rounded = round_price(price, tick_size)
        qty_rounded = round_amount(quantity, step_size, 0.0)

        if min_qty > 0 and qty_rounded < min_qty:
            raise ValueError(f"Take profit quantity {qty_rounded} below minimum {min_qty}")

        return await self.client.create_limit_order(
            symbol, side, qty_rounded, price_rounded, {"reduceOnly": True}
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(ccxt.NetworkError) | retry_if_exception_type(ccxt.ExchangeError),
    )
    async def place_take_profit_market(self, symbol: str, side: str, tp_price: float, quantity: float) -> dict:
        symbol, tick_size, step_size, min_qty, _ = await self._get_precision_and_min(symbol)

        tp_rounded = round_price(tp_price, tick_size)
        qty_rounded = round_amount(quantity, step_size, 0.0)

        if min_qty > 0 and qty_rounded < min_qty:
            raise ValueError(f"Take profit quantity {qty_rounded} below minimum {min_qty}")

        return await self.client.create_take_profit_market_order(
            symbol, side, qty_rounded, tp_rounded, {"reduceOnly": True}
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(ccxt.NetworkError) | retry_if_exception_type(ccxt.ExchangeError),
    )
    async def place_market_close(self, symbol: str, side: str, quantity: float) -> dict:
        symbol, _, step_size, min_qty, _ = await self._get_precision_and_min(symbol)

        qty_rounded = round_amount(quantity, step_size, 0.0)

        if min_qty > 0 and qty_rounded < min_qty:
            raise ValueError(f"Market close quantity {qty_rounded} below minimum {min_qty}")

        return await self.client.create_market_order(symbol, side, qty_rounded, {"reduceOnly": True})

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(ccxt.NetworkError) | retry_if_exception_type(ccxt.ExchangeError),
    )
    async def cancel_order(self, symbol: str, order_id: str) -> dict:
        # ✅ CRÍTICO: orden correcto (symbol, order_id) hacia nuestro wrapper
        symbol = await self.client.normalize_symbol(symbol)
        return await self.client.cancel_order(symbol, order_id)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(ccxt.NetworkError) | retry_if_exception_type(ccxt.ExchangeError),
    )
    async def wait_for_fill(self, symbol: str, order_id: str, timeout: int = 15) -> dict | None:
        symbol = await self.client.normalize_symbol(symbol)

        loop = asyncio.get_running_loop()
        start = loop.time()

        while loop.time() - start < timeout:
            # ✅ CRÍTICO: fetch_order en nuestro wrapper es (symbol, order_id)
            order = await self.client.fetch_order(symbol, order_id)
            status = (order.get("status") or "").lower()

            if status == "closed":
                return order
            if status in ("canceled", "expired", "rejected"):
                return None

            await asyncio.sleep(0.5)

        return None