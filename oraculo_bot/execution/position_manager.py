import asyncio
import logging
from ..strategy.trailing import compute_new_sl
from ..storage.trade_store import TradeStore
from ..constants import CloseReason, TradeState

log = logging.getLogger(__name__)

class PositionManager:
    def __init__(self, ex, order_mgr, store: TradeStore, settings, risk_mgr):
        self.ex = ex
        self.order_mgr = order_mgr
        self.store = store
        self.settings = settings
        self.risk_mgr = risk_mgr
        self.metrics_tracker = None

    def set_metrics_tracker(self, tracker):
        self.metrics_tracker = tracker

    async def manage(self, trade_id: int, symbol: str, side: str, entry: float, sl: float, tp1: float, tp2: float):
        loop = asyncio.get_running_loop()
        start_time = loop.time()
        max_hold = self.settings.max_holding_sec

        tp1_hit = False
        tp1_qty_ratio = 0.5

        while True:
            trade = await self.store.get_trade(trade_id)
            if trade is None or trade.get("state") not in (TradeState.RUNNING.value, TradeState.PROTECTIVE_PLACED.value):
                break

            positions = await self.ex.fetch_positions()
            pos = next((p for p in positions if self._sym_match(p, symbol)), None)

            pos_amt = 0.0
            if pos:
                info = pos.get("info", {}) or {}
                try:
                    pos_amt = abs(float(info.get("positionAmt", 0) or 0))
                except Exception:
                    pos_amt = 0.0

            # Si ya no hay posición en exchange, cerramos en DB según reason
            if pos_amt == 0:
                reason = await self._get_close_reason(trade_id, symbol)
                await self._close_db(trade_id, symbol, reason)
                break

            ticker = await self.ex.fetch_ticker(symbol)
            last_price = self._pick_price(ticker)
            if last_price is None:
                await asyncio.sleep(1)
                continue

            # --- TP1 parcial ---
            if (not tp1_hit) and tp1:
                if (side == "LONG" and last_price >= tp1) or (side == "SHORT" and last_price <= tp1):
                    close_side = "sell" if side == "LONG" else "buy"
                    tp1_qty = pos_amt * tp1_qty_ratio

                    # ✅ Ejecuta cierre parcial y GUARDA la orden (antes no lo hacías)
                    close_order = await self.order_mgr.place_market_close(symbol, close_side, tp1_qty)
                    await self.store.save_order(trade_id, close_order, "TP1")

                    # mover SL a BE (ligero buffer)
                    new_sl = entry * 1.001 if side == "LONG" else entry * 0.999

                    # cancelar stops reduceOnly existentes
                    open_orders = await self.ex.fetch_open_orders(symbol)
                    for o in open_orders:
                        otype = (o.get("type") or "").lower()
                        reduce = o.get("reduceOnly")
                        if reduce is None:
                            reduce = (o.get("info", {}) or {}).get("reduceOnly")
                        reduce = str(reduce).lower() in ("true", "1", "yes")

                        if otype in ("stop_market", "stop", "stop_loss") and reduce:
                            try:
                                await self.order_mgr.cancel_order(symbol, o["id"])
                            except Exception:
                                pass

                    remaining = max(0.0, pos_amt - tp1_qty)
                    if remaining > 0:
                        new_sl_order = await self.order_mgr.place_stop_loss(symbol, close_side, new_sl, remaining)
                        await self.store.save_order(trade_id, new_sl_order, "SL")
                        await self.store.update_trade_sl(trade_id, float(new_sl))
                        sl = float(new_sl)

                    tp1_hit = True

                    # colocar TP2 sobre remanente
                    if tp2 and remaining > 0:
                        tp2_order = await self.order_mgr.place_take_profit_market(symbol, close_side, tp2, remaining)
                        await self.store.save_order(trade_id, tp2_order, "TP2")

                    await asyncio.sleep(1)
                    continue

            # --- Trailing tras TP1 ---
            if tp1_hit:
                ohlcv = await self.ex.fetch_ohlcv(symbol, self.settings.tf_trigger, limit=100)
                new_sl = compute_new_sl(side, ohlcv, sl, entry, self.settings.max_sl_pct)
                if new_sl and float(new_sl) != float(sl):
                    # cancelar stop reduceOnly existente
                    open_orders = await self.ex.fetch_open_orders(symbol)
                    for o in open_orders:
                        otype = (o.get("type") or "").lower()
                        reduce = o.get("reduceOnly")
                        if reduce is None:
                            reduce = (o.get("info", {}) or {}).get("reduceOnly")
                        reduce = str(reduce).lower() in ("true", "1", "yes")

                        if otype in ("stop_market", "stop", "stop_loss") and reduce:
                            try:
                                await self.order_mgr.cancel_order(symbol, o["id"])
                            except Exception:
                                pass

                    close_side = "sell" if side == "LONG" else "buy"
                    new_sl_order = await self.order_mgr.place_stop_loss(symbol, close_side, float(new_sl), pos_amt)
                    await self.store.save_order(trade_id, new_sl_order, "SL")
                    await self.store.update_trade_sl(trade_id, float(new_sl))
                    sl = float(new_sl)

            # ✅ CRÍTICO: TIMEOUT debe cerrar en EXCHANGE (antes NO cerrabas)
            if (loop.time() - start_time) > max_hold:
                close_side = "sell" if side == "LONG" else "buy"
                try:
                    close_order = await self.order_mgr.place_market_close(symbol, close_side, pos_amt)
                    await self.store.save_order(trade_id, close_order, "CLOSE")
                except Exception as e:
                    log.error(f"Timeout close error {symbol}: {e}")
                await self._close_db(trade_id, symbol, CloseReason.TIMEOUT)
                break

            await asyncio.sleep(2)

    def _pick_price(self, ticker: dict):
        if not isinstance(ticker, dict):
            return None
        candidates = [
            ticker.get("last"),
            ticker.get("mark"),
            (ticker.get("info", {}) or {}).get("markPrice"),
            (ticker.get("info", {}) or {}).get("lastPrice"),
        ]
        for x in candidates:
            try:
                if x is None:
                    continue
                v = float(x)
                if v > 0:
                    return v
            except Exception:
                continue
        return None

    def _sym_match(self, pos, symbol):
        def norm(x: str) -> str:
            return (x or "").replace("/", "").replace(":", "").upper()

        s = pos.get("symbol") or ""
        if norm(s) == norm(symbol):
            return True

        info_sym = ((pos.get("info") or {}).get("symbol") or "")
        if info_sym and norm(info_sym) == norm(symbol):
            return True

        return False

    async def _get_close_reason(self, trade_id: int, symbol: str) -> CloseReason:
        sl_order_id = await self.store.get_order_id_by_type(trade_id, "SL")
        tp1_order_id = await self.store.get_order_id_by_type(trade_id, "TP1")
        tp2_order_id = await self.store.get_order_id_by_type(trade_id, "TP2")
        close_order_id = await self.store.get_order_id_by_type(trade_id, "CLOSE")

        for order_id in [sl_order_id, tp1_order_id, tp2_order_id, close_order_id]:
            if order_id:
                try:
                    order = await self.ex.fetch_order(symbol, order_id)
                    if (order.get("status") or "").lower() == "closed":
                        if order_id == sl_order_id:
                            return CloseReason.SL
                        if order_id == close_order_id:
                            return CloseReason.MANUAL
                        return CloseReason.TP
                except Exception:
                    pass
        return CloseReason.EXCHANGE_CLOSED

    async def _close_db(self, trade_id: int, symbol: str, reason: CloseReason):
        pnl = await self._calculate_pnl(trade_id, symbol)
        await self.store.close_trade(trade_id, reason, pnl)
        if self.metrics_tracker and pnl is not None:
            self.metrics_tracker.add_trade(pnl)
        if self.risk_mgr and pnl is not None:
            if pnl < 0:
                await self.risk_mgr.register_loss(symbol)
            else:
                await self.risk_mgr.register_win(symbol)

    async def _calculate_pnl(self, trade_id: int, symbol: str) -> float | None:
        trade = await self.store.get_trade(trade_id)
        if not trade or not trade.get("entry_price"):
            return None

        entry = float(trade["entry_price"])
        side = trade.get("side")  # "LONG"/"SHORT"
        qty_total = float(trade.get("quantity") or 0.0)
        if entry <= 0 or qty_total <= 0:
            return None

        exit_orders = []
        for typ in ("TP1", "TP2", "SL", "CLOSE"):
            order_id = await self.store.get_order_id_by_type(trade_id, typ)
            if order_id:
                try:
                    order = await self.ex.fetch_order(symbol, order_id)
                    if (order.get("status") or "").lower() == "closed":
                        exit_orders.append(order)
                except Exception:
                    pass

        if not exit_orders:
            return None

        total_pnl = 0.0
        for order in exit_orders:
            avg_price = float(order.get("average") or order.get("price") or 0)
            filled_qty = float(order.get("filled") or 0)
            if avg_price <= 0 or filled_qty <= 0:
                continue

            order_side = (order.get("side") or "").lower()  # "buy"/"sell"
            if order_side == "sell":  # cerrando LONG
                pnl_partial = (avg_price - entry) * filled_qty
            else:  # cerrando SHORT
                pnl_partial = (entry - avg_price) * filled_qty
            total_pnl += pnl_partial

        fee_rate = 0.0005
        total_fees = (entry * qty_total) * fee_rate * 2
        total_pnl -= total_fees

        return float(total_pnl)