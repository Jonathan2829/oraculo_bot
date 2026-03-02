import asyncio
import logging
from ..strategy.signal_engine import compute_signal
from ..execution.order_manager import OrderManager
from ..execution.trade_state import TradeStateMachine
from ..execution.position_manager import PositionManager
from ..risk.risk_manager import RiskManager
from ..storage.trade_store import TradeStore
from ..notifier.telegram import TelegramNotifier
from ..constants import TradeState, CloseReason

log = logging.getLogger(__name__)

class Scheduler:
    def __init__(self, settings, market_data, order_mgr: OrderManager, trade_store: TradeStore,
                 state_machine: TradeStateMachine, position_mgr: PositionManager,
                 risk_mgr: RiskManager, notifier: TelegramNotifier, funding_filter=None):
        self.settings = settings
        self.market_data = market_data
        self.order_mgr = order_mgr
        self.trade_store = trade_store
        self.state_machine = state_machine
        self.position_mgr = position_mgr
        self.risk_mgr = risk_mgr
        self.notifier = notifier
        self.funding_filter = funding_filter

    async def run_once(self, symbols):
        sem = asyncio.Semaphore(20)
        async def guard(sym):
            async with sem:
                return await self._evaluate_symbol(sym)
        tasks = [guard(sym) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        signals = [r for r in results if isinstance(r, dict)]
        signals.sort(key=lambda x: x["score"], reverse=True)

        open_positions = await self.trade_store.get_open_trades()
        open_count = len(open_positions)

        for sig in signals:
            if open_count >= self.settings.max_concurrent_positions:
                break
            can, reason = await self.risk_mgr.can_trade(sig["symbol"], sig["side"])
            if not can:
                continue
            await self._execute_signal(sig)
            open_count += 1

    async def _evaluate_symbol(self, symbol):
        try:
            return await compute_signal(symbol, self.settings, self.market_data, self.funding_filter)
        except Exception as e:
            log.exception(f"Error evaluando {symbol}: {e}")
            return None

    async def _execute_signal(self, signal):
        trade_id = await self.trade_store.create_trade(signal)
        await self.risk_mgr.register_trade(trade_id, signal["symbol"])

        await self.order_mgr.client.set_margin_mode(signal["symbol"], "isolated")
        await self.order_mgr.client.set_leverage(signal["symbol"], signal["leverage"])

        side = "buy" if signal["side"] == "LONG" else "sell"
        qty = signal["size_usdt"] / signal["entry"]

        # Decidir tipo de entrada según spread y volatilidad
        if signal.get("atr_expand", 1.0) < 1.5 and signal.get("spread_pct", 0) < 0.05:
            order = await self.order_mgr.place_entry(signal["symbol"], side, signal["entry"], qty, post_only=True)
        else:
            order = await self.order_mgr.place_market_order(signal["symbol"], side, qty, {"reduceOnly": False})

        await self.trade_store.save_order(trade_id, order, "ENTRY")
        await self.state_machine.transition(trade_id, TradeState.ENTRY_PLACED)

        filled = await self.order_mgr.wait_for_fill(signal["symbol"], order["id"], self.settings.entry_timeout_sec)
        if not filled:
            await self.order_mgr.cancel_order(signal["symbol"], order["id"])
            await self.trade_store.close_trade(trade_id, CloseReason.TIMEOUT, pnl=0)
            return

        fill_price = float(filled.get("average") or filled.get("price") or signal["entry"])
        filled_qty = float(filled.get("filled") or qty)

        await self.trade_store.update_entry_fill(trade_id, fill_price, filled_qty)
        await self.state_machine.transition(trade_id, TradeState.ENTRY_FILLED)

        sl_side = "sell" if signal["side"] == "LONG" else "buy"
        try:
            sl_order = await self.order_mgr.place_stop_loss(signal["symbol"], sl_side, signal["sl"], filled_qty)
            if signal.get("atr_expand", 1.0) > 2.0:
                tp_order = await self.order_mgr.place_take_profit_market(
                    signal["symbol"], sl_side, signal["tp1"], filled_qty
                )
            else:
                tp_order = await self.order_mgr.place_take_profit_limit(
                    signal["symbol"], sl_side, signal["tp1"], filled_qty
                )
            await self.trade_store.save_orders_atomic(trade_id, [(sl_order, "SL"), (tp_order, "TP1")])
            await self.state_machine.transition(trade_id, TradeState.PROTECTIVE_PLACED)
            await self.state_machine.transition(trade_id, TradeState.RUNNING)
        except Exception as e:
            log.critical(f"No se pudo colocar SL/TP para {signal['symbol']}, cerrando posición... Error: {e}")
            close_order = await self.order_mgr.place_market_close(signal["symbol"], sl_side, filled_qty)
            await self.trade_store.save_order(trade_id, close_order, "CLOSE")
            await self.trade_store.close_trade(trade_id, CloseReason.ERROR, pnl=None)
            await self.notifier.send(f"🔥 CRÍTICO: {signal['symbol']} cerrado por fallo de protección.")
            return

        msg = self._format_execution_msg(signal, fill_price)
        await self.notifier.send(msg)

        asyncio.create_task(self.position_mgr.manage(
            trade_id, signal["symbol"], signal["side"],
            fill_price, signal["sl"], signal["tp1"], signal["tp2"]
        ))

    def _format_execution_msg(self, signal, fill_price):
        return (
            f"<b>ENTRADA EJECUTADA</b>\n"
            f"{signal['symbol']} | {signal['side']} | Score {signal['score']}\n"
            f"Precio: {fill_price:.6f}\n"
            f"SL: {signal['sl']:.6f} ({signal['sl_pct']*100:.2f}%)\n"
            f"TP1: {signal['tp1']:.6f}\n"
            f"Tamaño: {signal['size_usdt']:.2f} USDT"
        )