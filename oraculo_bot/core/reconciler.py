import logging
from ..storage.trade_store import TradeStore
from ..exchange.binance_client import BinanceClient
from ..constants import CloseReason

log = logging.getLogger(__name__)

class Reconciler:
    def __init__(self, ex: BinanceClient, store: TradeStore):
        self.ex = ex
        self.store = store

    def _norm(self, s: str) -> str:
        return (s or "").replace("/", "").replace(":", "").upper()

    async def run_once(self):
        ex_positions = await self.ex.fetch_positions()
        ex_pos_dict = {}
        for p in ex_positions:
            info = p.get("info", {}) or {}
            try:
                amt = float(info.get("positionAmt", 0) or 0)
            except Exception:
                amt = 0.0
            if abs(amt) <= 0:
                continue

            sym = p.get("symbol") or ""
            info_sym = info.get("symbol") or ""
            # Guardamos por normalizado
            ex_pos_dict[self._norm(sym)] = p
            if info_sym:
                ex_pos_dict[self._norm(info_sym)] = p

        db_trades = await self.store.get_open_trades()

        # Cierra en DB si ya no hay posición en exchange
        for t in db_trades:
            if self._norm(t["symbol"]) not in ex_pos_dict:
                await self.store.close_trade(t["trade_id"], CloseReason.EXCHANGE_CLOSED, pnl=None)
                log.warning(f"Trade {t['trade_id']} cerrado en DB porque no está en exchange")

        # Si hay posición en exchange pero no existe en DB -> recovery
        for k_norm, pos in ex_pos_dict.items():
            if any(self._norm(t["symbol"]) == k_norm for t in db_trades):
                continue

            info = pos.get("info", {}) or {}
            qty = abs(float(info.get("positionAmt", 0) or 0))
            side = "LONG" if float(info.get("positionAmt", 0) or 0) > 0 else "SHORT"
            entry = float(info.get("entryPrice") or 0)

            # intentamos reconstruir símbolo usable
            sym_raw = info.get("symbol") or pos.get("symbol") or ""
            sym = sym_raw
            if sym_raw.endswith("USDT") and "/" not in sym_raw:
                base = sym_raw[:-4]
                sym = f"{base}/USDT"

            open_orders = await self.ex.fetch_open_orders(sym)
            sl = next((o for o in open_orders if (o.get("type") or "").lower() in ("stop_market","stop")), None)
            tp = next((o for o in open_orders if (o.get("type") or "").lower() == "limit" and (o.get("reduceOnly") or (o.get("info", {}) or {}).get("reduceOnly"))), None)

            trade_id = await self.store.create_recovery_trade(sym, side, qty, entry, sl, tp)
            log.warning(f"Trade de recuperación creado para {sym} con ID {trade_id}")