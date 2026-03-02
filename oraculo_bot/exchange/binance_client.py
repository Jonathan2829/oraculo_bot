import ccxt.async_support as ccxt
from typing import Optional, Dict, List, Any


class BinanceClient:
    """
    Cliente Binance (CCXT Async) con modo:
      - PUBLICO: sin apiKey/secret (market data OK)
      - PRIVADO: con apiKey/secret (balance/órdenes OK)

    Parche clave:
      - Futures USDT-M => usa ccxt.binanceusdm (evita endpoints mixtos)
      - Desactiva fetchCurrencies para evitar llamadas que disparan -2008
      - adjustForTimeDifference para minimizar problemas de timestamp
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        market_type: str = "futures",
        testnet: bool = False,
    ):
        self.market_type = (market_type or "futures").strip().lower()
        self.testnet = bool(testnet)

        # Base options CCXT
        opts: Dict[str, Any] = {
            "enableRateLimit": True,
            "options": {
                # MUY importante para no meterse a endpoints raros
                "fetchCurrencies": False,
                # Ajusta reloj local vs servidor
                "adjustForTimeDifference": True,
            },
        }

        # Credenciales (si vienen vacías => público)
        if api_key and api_secret:
            opts["apiKey"] = api_key.strip()
            opts["secret"] = api_secret.strip()

        # ==========================
        # Selección de Exchange CCXT
        # ==========================
        # futures/usdm => Binance USDT-M Futures
        if self.market_type in ("futures", "future", "usdm"):
            self.ex = ccxt.binanceusdm(opts)

        # coinm => Binance COIN-M Futures (por si algún día lo usas)
        elif self.market_type in ("coinm", "delivery"):
            self.ex = ccxt.binancecoinm(opts)

        # spot (y margin spot) => Binance Spot
        else:
            # Para spot, defaultType = spot
            opts["options"]["defaultType"] = "spot"
            self.ex = ccxt.binance(opts)

        # Testnet:
        # - En spot binance: sandbox funciona.
        # - En binanceusdm/binancecoinm: sandbox depende de CCXT/endpoint,
        #   pero set_sandbox_mode(True) es lo más estándar.
        if self.testnet:
            try:
                self.ex.set_sandbox_mode(True)
            except Exception:
                pass

        self._markets = None

    async def close(self):
        try:
            await self.ex.close()
        except Exception:
            pass

    async def load_markets(self, reload: bool = False):
        if self._markets is None or reload:
            self._markets = await self.ex.load_markets(reload)
        return self._markets

    # ===============================
    # NORMALIZACIÓN DE SÍMBOLO
    # ===============================
    async def normalize_symbol(self, symbol: str) -> str:
        """
        Permite usar ADA/USDT aunque CCXT use ADA/USDT:USDT en futures.
        """
        markets = await self.load_markets()

        if symbol in markets:
            return symbol

        # En futures USDT-M, CCXT suele usar "ADA/USDT:USDT"
        if self.market_type in ("futures", "future", "usdm"):
            if symbol.endswith("/USDT"):
                candidate = f"{symbol}:USDT"
                if candidate in markets:
                    return candidate

        if ":USDT" in symbol:
            base = symbol.replace(":USDT", "")
            if base in markets:
                return base

        return symbol

    # ===============================
    # MARKET DATA (NO requiere keys)
    # ===============================
    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 400) -> List[List[float]]:
        sym = await self.normalize_symbol(symbol)
        return await self.ex.fetch_ohlcv(sym, timeframe, limit=limit)

    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        sym = await self.normalize_symbol(symbol)
        return await self.ex.fetch_ticker(sym)

    async def fetch_tickers(self, symbols: Optional[List[str]] = None) -> Dict[str, Any]:
        if symbols:
            symbols = [await self.normalize_symbol(s) for s in symbols]
        return await self.ex.fetch_tickers(symbols)

    async def fetch_markets(self) -> List[Dict]:
        return await self.ex.fetch_markets()

    # ===============================
    # PRIVADO (requiere keys válidas)
    # ===============================
    async def fetch_balance(self) -> Dict:
        return await self.ex.fetch_balance()

    async def fetch_positions(self) -> List[Dict]:
        # CCXT moderno
        try:
            if hasattr(self.ex, "fetch_positions"):
                return await self.ex.fetch_positions()
        except Exception:
            pass

        # Fallback: endpoint futures (solo si es futures)
        if self.market_type not in ("futures", "future", "usdm"):
            return []

        try:
            # binanceusdm trae fapi privado disponible
            data = await self.ex.fapiPrivateV2GetPositionRisk()
            out = []
            for p in data:
                sym_raw = p.get("symbol", "")
                sym = f"{sym_raw[:-4]}/USDT" if sym_raw.endswith("USDT") else sym_raw
                out.append({"symbol": sym, "info": p, "entryPrice": p.get("entryPrice")})
            return out
        except Exception:
            return []

    async def fetch_open_orders(self, symbol: str = None) -> List[Dict]:
        sym = await self.normalize_symbol(symbol) if symbol else None
        return await self.ex.fetch_open_orders(sym)

    async def create_limit_order(self, symbol: str, side: str, amount: float, price: float, params: Dict = None) -> Dict:
        sym = await self.normalize_symbol(symbol)
        return await self.ex.create_limit_order(sym, side, amount, price, params or {})

    async def create_market_order(self, symbol: str, side: str, amount: float, params: Dict = None) -> Dict:
        sym = await self.normalize_symbol(symbol)
        return await self.ex.create_order(sym, "MARKET", side, amount, None, params or {})

    async def create_stop_market_order(self, symbol: str, side: str, amount: float, stop_price: float, params: Dict = None) -> Dict:
        sym = await self.normalize_symbol(symbol)
        p = params or {}
        p.update({
            "stopPrice": stop_price,
            "workingType": "MARK_PRICE",
            "priceProtect": True,
            "reduceOnly": True,
        })
        return await self.ex.create_order(sym, "STOP_MARKET", side, amount, None, p)

    async def create_take_profit_market_order(self, symbol: str, side: str, amount: float, stop_price: float, params: Dict = None) -> Dict:
        sym = await self.normalize_symbol(symbol)
        p = params or {}
        p.update({
            "stopPrice": stop_price,
            "workingType": "MARK_PRICE",
            "priceProtect": True,
            "reduceOnly": True,
        })
        return await self.ex.create_order(sym, "TAKE_PROFIT_MARKET", side, amount, None, p)

    async def cancel_order(self, symbol: str, order_id: str) -> Dict:
        sym = await self.normalize_symbol(symbol)
        return await self.ex.cancel_order(order_id, sym)

    async def fetch_order(self, symbol: str, order_id: str) -> Dict:
        sym = await self.normalize_symbol(symbol)
        return await self.ex.fetch_order(order_id, sym)

    async def fetch_order_book(self, symbol: str, limit: int = 10) -> Dict:
        sym = await self.normalize_symbol(symbol)
        return await self.ex.fetch_order_book(sym, limit)

    async def fetch_funding_rate(self, symbol: str):
        sym = await self.normalize_symbol(symbol)
        try:
            return await self.ex.fetch_funding_rate(sym)
        except Exception:
            return None

    async def set_leverage(self, symbol: str, leverage: int):
        sym = await self.normalize_symbol(symbol)
        try:
            return await self.ex.set_leverage(leverage, sym, {})
        except Exception:
            return None

    async def set_margin_mode(self, symbol: str, mode: str = "isolated"):
        sym = await self.normalize_symbol(symbol)
        try:
            return await self.ex.set_margin_mode(mode, sym, {})
        except Exception:
            return None

    async def fetch_status(self):
        return await self.ex.fetch_status()