import os
import asyncio
from dataclasses import asdict
from typing import Optional, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, ApplicationBuilder,
    CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

from oraculo_bot.core.runtime import RuntimeStore, RuntimeState

def _env(name: str, default: str = "") -> str:
    v = os.getenv(name, default)
    return (v or "").strip()

def _env_bool(name: str, default: bool = False) -> bool:
    v = _env(name, "true" if default else "false").lower()
    return v in ("true", "1", "yes", "y", "on")

def _csv_ints(s: str) -> set[int]:
    out = set()
    for x in (s or "").split(","):
        x = x.strip()
        if not x:
            continue
        try:
            out.add(int(x))
        except Exception:
            pass
    return out

def _csv_strs(s: str) -> set[str]:
    return {x.strip() for x in (s or "").split(",") if x.strip()}

def _short_exc(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"

class ExchangeAdapter:
    """
    Adaptador opcional para acciones FULL.
    Si ya tienes ccxt exchange en tu app, pásalo aquí.
    """
    def __init__(self, exchange: Any):
        self.ex = exchange

    async def balance(self) -> str:
        b = await self.ex.fetch_balance()
        # intenta USDT
        usdt = None
        if isinstance(b, dict):
            if "USDT" in b and isinstance(b["USDT"], dict):
                usdt = b["USDT"]
            elif "total" in b and isinstance(b["total"], dict) and "USDT" in b["total"]:
                usdt = {"total": b["total"]["USDT"]}
        return str(usdt or b)

    async def positions(self) -> Any:
        if hasattr(self.ex, "fetch_positions"):
            return await self.ex.fetch_positions()
        raise RuntimeError("Exchange no soporta fetch_positions()")

    async def open_orders(self, symbol: Optional[str] = None) -> Any:
        if hasattr(self.ex, "fetch_open_orders"):
            return await self.ex.fetch_open_orders(symbol)
        raise RuntimeError("Exchange no soporta fetch_open_orders()")

    async def cancel_all(self, symbol: Optional[str] = None) -> Any:
        if hasattr(self.ex, "cancel_all_orders"):
            return await self.ex.cancel_all_orders(symbol)
        orders = await self.open_orders(symbol)
        res = []
        for o in orders:
            oid = o.get("id")
            sym = o.get("symbol")
            if oid and hasattr(self.ex, "cancel_order"):
                res.append(await self.ex.cancel_order(oid, sym))
        return res

    async def close_symbol_market(self, symbol: str) -> str:
        pos = await self.positions()
        symbol = symbol.upper()
        p = None
        for x in pos:
            if str(x.get("symbol","")).upper() == symbol:
                p = x
                break
        if not p:
            return f"No hay posición para {symbol}"

        contracts = p.get("contracts") or p.get("contractSize") or p.get("size") or p.get("amount")
        side = str(p.get("side","")).lower()
        if not contracts:
            info = p.get("info", {})
            contracts = info.get("positionAmt") or info.get("positionAmt".lower())
        try:
            amt = abs(float(contracts))
        except Exception:
            raise RuntimeError(f"No pude determinar tamaño de posición para {symbol}. Pos: {p}")

        if amt <= 0:
            return f"Posición {symbol} ya en 0"

        close_side = "sell" if side == "long" else "buy"
        if hasattr(self.ex, "create_market_order"):
            await self.ex.create_market_order(symbol, close_side, amt)
            return f"Cerrado MARKET {symbol} {close_side} {amt}"
        if hasattr(self.ex, "create_order"):
            await self.ex.create_order(symbol, "market", close_side, amt)
            return f"Cerrado MARKET {symbol} {close_side} {amt}"

        raise RuntimeError("Exchange no soporta create_market_order/create_order")

class TelegramPanel:
    def __init__(
        self,
        runtime_store: RuntimeStore,
        *,
        exchange_adapter: Optional[ExchangeAdapter] = None,
        logger=None,
    ):
        self.store = runtime_store
        self.exchange = exchange_adapter
        self.log = logger

        self.token = _env("TELEGRAM_BOT_TOKEN")
        self.enabled = _env_bool("TELEGRAM_PANEL_ENABLED", True)
        self.admin_ids = _csv_ints(_env("TELEGRAM_ADMIN_IDS"))
        self.allowed_chat_ids = {int(x) for x in _csv_strs(_env("TELEGRAM_ALLOWED_CHAT_IDS")) if x.lstrip("-").isdigit()}

        self._app: Optional[Application] = None
        self._pending_confirm: dict[tuple[int, str], dict] = {}  # (user_id, action) -> payload

    def _is_allowed(self, update: Update) -> bool:
        try:
            uid = update.effective_user.id if update.effective_user else None
            cid = update.effective_chat.id if update.effective_chat else None
            if uid is None or cid is None:
                return False
            if self.admin_ids and uid not in self.admin_ids:
                return False
            if self.allowed_chat_ids and cid not in self.allowed_chat_ids:
                return False
            return True
        except Exception:
            return False

    async def _deny(self, update: Update):
        if update.message:
            await update.message.reply_text("🚫 No autorizado.")
        elif update.callback_query:
            await update.callback_query.answer("No autorizado", show_alert=True)

    def _kb(self, st: RuntimeState) -> InlineKeyboardMarkup:
        pause_btn = InlineKeyboardButton("▶️ Reanudar" if st.paused else "⏸ Pausar", callback_data="toggle_pause")
        auto_btn  = InlineKeyboardButton("🤖 Auto ON" if not st.auto_trading else "🤖 Auto OFF", callback_data="toggle_auto")
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Balance", callback_data="balance"),
             InlineKeyboardButton("📌 Posiciones", callback_data="positions")],
            [InlineKeyboardButton("📄 Órdenes", callback_data="orders"),
             InlineKeyboardButton("🧾 Logs", callback_data="logs")],
            [pause_btn, auto_btn],
            [InlineKeyboardButton("⚙️ Ajustes", callback_data="settings"),
             InlineKeyboardButton("🔄 Refresh", callback_data="panel")],
            [InlineKeyboardButton("🧯 Close ALL", callback_data="confirm:closeall"),
             InlineKeyboardButton("🧨 Cancel ALL", callback_data="confirm:cancelall")],
        ])

    async def _panel_text(self) -> str:
        st = self.store.load_state()
        return (
            "🧠 <b>Oráculo Pro — Panel</b>\n\n"
            f"• Estado: {'⏸ PAUSADO' if st.paused else '✅ CORRIENDO'}\n"
            f"• Auto trading: {'✅ ON' if st.auto_trading else '❌ OFF'}\n"
            f"• Risk/trade: <b>{st.risk_per_trade:.3f}%</b>\n"
            f"• Leverage: <b>{st.leverage_default}x</b>\n"
            f"• Max posiciones: <b>{st.max_positions}</b>\n"
            f"• Scan interval: <b>{st.scan_interval_seconds}s</b>\n"
            f"• Whitelist: <b>{', '.join(st.whitelist_symbols) if st.whitelist_symbols else 'ALL'}</b>\n"
        )

    async def cmd_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        st = self.store.load_state()
        await update.message.reply_text(await self._panel_text(), parse_mode=ParseMode.HTML, reply_markup=self._kb(st))

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        await update.message.reply_text(await self._panel_text(), parse_mode=ParseMode.HTML)

    async def cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        self.store.update(paused=True)
        self.store.audit(str(update.effective_user.id), update.effective_user.full_name, "pause", {})
        await update.message.reply_text("⏸ Pausado.")

    async def cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        self.store.update(paused=False)
        self.store.audit(str(update.effective_user.id), update.effective_user.full_name, "resume", {})
        await update.message.reply_text("▶️ Reanudado.")

    async def cmd_autoon(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        self.store.update(auto_trading=True)
        self.store.audit(str(update.effective_user.id), update.effective_user.full_name, "auto_on", {})
        await update.message.reply_text("🤖 Auto trading: ON")

    async def cmd_autooff(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        self.store.update(auto_trading=False)
        self.store.audit(str(update.effective_user.id), update.effective_user.full_name, "auto_off", {})
        await update.message.reply_text("🤖 Auto trading: OFF")

    async def cmd_set(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)

        parts = (update.message.text or "").split()
        if len(parts) < 3:
            return await update.message.reply_text(
                "Uso:\n"
                "/set risk 0.5\n"
                "/set lev 8\n"
                "/set maxpos 2\n"
                "/set scan 60\n"
                "/set whitelist BTC/USDT,ETH/USDT\n"
                "/set whitelist ALL"
            )

        key = parts[1].lower()
        val = " ".join(parts[2:]).strip()

        patch = {}
        if key in ("risk", "risk_per_trade"):
            patch["risk_per_trade"] = float(val)
        elif key in ("lev", "leverage"):
            patch["leverage_default"] = int(val)
        elif key in ("maxpos", "max_positions"):
            patch["max_positions"] = int(val)
        elif key in ("scan", "scan_interval"):
            patch["scan_interval_seconds"] = int(val)
        elif key in ("whitelist", "wl"):
            if val.upper() == "ALL":
                patch["whitelist_symbols"] = None
            else:
                patch["whitelist_symbols"] = [x.strip().upper() for x in val.split(",") if x.strip()]
        else:
            return await update.message.reply_text("Key no soportada. Usa: risk | lev | maxpos | scan | whitelist")

        self.store.update(**patch)
        self.store.audit(str(update.effective_user.id), update.effective_user.full_name, "set", patch)
        st = self.store.load_state()
        await update.message.reply_text("✅ Actualizado.\n\n" + await self._panel_text(), parse_mode=ParseMode.HTML, reply_markup=self._kb(st))

    async def cmd_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        if not self.exchange:
            return await update.message.reply_text("⚠️ ExchangeAdapter no conectado. (Solo panel sin Binance)")
        try:
            b = await self.exchange.balance()
            await update.message.reply_text(f"📊 Balance:\n<pre>{b}</pre>", parse_mode=ParseMode.HTML)
        except Exception as e:
            await update.message.reply_text(f"❌ Error balance: {_short_exc(e)}")

    async def cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        if not self.exchange:
            return await update.message.reply_text("⚠️ ExchangeAdapter no conectado.")
        try:
            pos = await self.exchange.positions()
            lines = []
            for p in pos:
                sym = p.get("symbol")
                side = p.get("side")
                contracts = p.get("contracts") or p.get("amount") or p.get("size")
                entry = p.get("entryPrice") or p.get("entry") or p.get("average")
                pnl = p.get("unrealizedPnl") or p.get("pnl")
                if contracts and float(contracts) != 0:
                    lines.append(f"{sym} | {side} | size={contracts} | entry={entry} | pnl={pnl}")
            if not lines:
                lines = ["(sin posiciones)"]
            await update.message.reply_text("📌 Posiciones:\n<pre>" + "\n".join(lines[:80]) + "</pre>", parse_mode=ParseMode.HTML)
        except Exception as e:
            await update.message.reply_text(f"❌ Error posiciones: {_short_exc(e)}")

    async def cmd_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        if not self.exchange:
            return await update.message.reply_text("⚠️ ExchangeAdapter no conectado.")
        try:
            orders = await self.exchange.open_orders(None)
            lines = []
            for o in orders:
                sym = o.get("symbol")
                side = o.get("side")
                typ = o.get("type")
                price = o.get("price")
                amt = o.get("amount")
                oid = o.get("id")
                lines.append(f"{sym} | {side} | {typ} | amt={amt} | price={price} | id={oid}")
            if not lines:
                lines = ["(sin órdenes)"]
            await update.message.reply_text("📄 Órdenes:\n<pre>" + "\n".join(lines[:80]) + "</pre>", parse_mode=ParseMode.HTML)
        except Exception as e:
            await update.message.reply_text(f"❌ Error órdenes: {_short_exc(e)}")

    async def cmd_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        n = 80
        parts = (update.message.text or "").split()
        if len(parts) >= 2:
            try:
                n = max(10, min(200, int(parts[1])))
            except Exception:
                pass
        candidates = ["/app/logs/oraculo.log", "/app/oraculo.log", "/app/log.txt"]
        text = None
        for p in candidates:
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()[-n:]
                text = "".join(lines).strip()
                break
            except Exception:
                continue
        if not text:
            return await update.message.reply_text("🧾 Logs: no encontré archivo de log. (Implementa log file o usa Fly logs)")
        await update.message.reply_text("🧾 Logs:\n<pre>" + text[-3500:] + "</pre>", parse_mode=ParseMode.HTML)

    async def cmd_close(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)
        if not self.exchange:
            return await update.message.reply_text("⚠️ ExchangeAdapter no conectado.")
        parts = (update.message.text or "").split()
        if len(parts) < 2:
            return await update.message.reply_text("Uso: /close BTC/USDT")
        sym = parts[1].upper()
        uid = update.effective_user.id
        self._pending_confirm[(uid, "close")] = {"symbol": sym}
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ CONFIRMAR CLOSE", callback_data="do:close"),
             InlineKeyboardButton("❌ Cancelar", callback_data="do:cancel")]
        ])
        await update.message.reply_text(f"🧯 Confirmas cerrar MARKET {sym}?", reply_markup=kb)

    async def _do_close(self, update: Update):
        uid = update.effective_user.id
        payload = self._pending_confirm.pop((uid, "close"), None)
        if not payload:
            return await update.callback_query.answer("No hay acción pendiente", show_alert=True)
        sym = payload["symbol"]
        try:
            msg = await self.exchange.close_symbol_market(sym)
            self.store.audit(str(uid), update.effective_user.full_name, "close_symbol", payload)
            await update.callback_query.edit_message_text("✅ " + msg)
        except Exception as e:
            await update.callback_query.edit_message_text("❌ Close error: " + _short_exc(e))

    async def _confirm(self, update: Update, action: str):
        uid = update.effective_user.id
        self._pending_confirm[(uid, action)] = {"action": action}
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ CONFIRMAR", callback_data=f"do:{action}"),
             InlineKeyboardButton("❌ Cancelar", callback_data="do:cancel")]
        ])
        await update.callback_query.edit_message_text(f"⚠️ Confirmas ejecutar: {action.upper()} ?", reply_markup=kb)

    async def _do_action(self, update: Update, action: str):
        uid = update.effective_user.id
        payload = self._pending_confirm.pop((uid, action), None)
        if not payload:
            return await update.callback_query.answer("No hay acción pendiente", show_alert=True)

        if not self.exchange:
            return await update.callback_query.edit_message_text("⚠️ ExchangeAdapter no conectado.")

        try:
            if action == "closeall":
                pos = await self.exchange.positions()
                closed = 0
                for p in pos:
                    sym = str(p.get("symbol","")).upper()
                    contracts = p.get("contracts") or p.get("amount") or 0
                    try:
                        if float(contracts) != 0:
                            await self.exchange.close_symbol_market(sym)
                            closed += 1
                    except Exception:
                        continue
                self.store.audit(str(uid), update.effective_user.full_name, "closeall", {"closed": closed})
                return await update.callback_query.edit_message_text(f"✅ Close ALL ejecutado. Cerrados: {closed}")

            if action == "cancelall":
                res = await self.exchange.cancel_all(None)
                self.store.audit(str(uid), update.effective_user.full_name, "cancelall", {"count": len(res) if isinstance(res,list) else 0})
                return await update.callback_query.edit_message_text("✅ Cancel ALL ejecutado.")

            return await update.callback_query.edit_message_text("Acción no soportada.")

        except Exception as e:
            return await update.callback_query.edit_message_text("❌ Error: " + _short_exc(e))

    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return await self._deny(update)

        q = update.callback_query
        data = q.data or ""
        await q.answer()

        if data == "panel":
            st = self.store.load_state()
            return await q.edit_message_text(await self._panel_text(), parse_mode=ParseMode.HTML, reply_markup=self._kb(st))

        if data == "toggle_pause":
            st = self.store.load_state()
            newv = not st.paused
            self.store.update(paused=newv)
            self.store.audit(str(update.effective_user.id), update.effective_user.full_name, "toggle_pause", {"paused": newv})
            st = self.store.load_state()
            return await q.edit_message_text(await self._panel_text(), parse_mode=ParseMode.HTML, reply_markup=self._kb(st))

        if data == "toggle_auto":
            st = self.store.load_state()
            newv = not st.auto_trading
            self.store.update(auto_trading=newv)
            self.store.audit(str(update.effective_user.id), update.effective_user.full_name, "toggle_auto", {"auto_trading": newv})
            st = self.store.load_state()
            return await q.edit_message_text(await self._panel_text(), parse_mode=ParseMode.HTML, reply_markup=self._kb(st))

        if data == "balance":
            if not self.exchange:
                return await q.edit_message_text("⚠️ ExchangeAdapter no conectado.")
            try:
                b = await self.exchange.balance()
                return await q.edit_message_text(f"📊 Balance:\n<pre>{b}</pre>", parse_mode=ParseMode.HTML)
            except Exception as e:
                return await q.edit_message_text("❌ " + _short_exc(e))

        if data == "positions":
            if not self.exchange:
                return await q.edit_message_text("⚠️ ExchangeAdapter no conectado.")
            try:
                pos = await self.exchange.positions()
                lines = []
                for p in pos:
                    sym = p.get("symbol")
                    side = p.get("side")
                    contracts = p.get("contracts") or p.get("amount") or p.get("size")
                    entry = p.get("entryPrice") or p.get("entry") or p.get("average")
                    pnl = p.get("unrealizedPnl") or p.get("pnl")
                    if contracts:
                        try:
                            if float(contracts) == 0:
                                continue
                        except Exception:
                            pass
                    lines.append(f"{sym} | {side} | size={contracts} | entry={entry} | pnl={pnl}")
                if not lines:
                    lines = ["(sin posiciones)"]
                return await q.edit_message_text("📌 Posiciones:\n<pre>" + "\n".join(lines[:80]) + "</pre>", parse_mode=ParseMode.HTML)
            except Exception as e:
                return await q.edit_message_text("❌ " + _short_exc(e))

        if data == "orders":
            if not self.exchange:
                return await q.edit_message_text("⚠️ ExchangeAdapter no conectado.")
            try:
                orders = await self.exchange.open_orders(None)
                lines = []
                for o in orders:
                    sym = o.get("symbol")
                    side = o.get("side")
                    typ = o.get("type")
                    price = o.get("price")
                    amt = o.get("amount")
                    oid = o.get("id")
                    lines.append(f"{sym} | {side} | {typ} | amt={amt} | price={price} | id={oid}")
                if not lines:
                    lines = ["(sin órdenes)"]
                return await q.edit_message_text("📄 Órdenes:\n<pre>" + "\n".join(lines[:80]) + "</pre>", parse_mode=ParseMode.HTML)
            except Exception as e:
                return await q.edit_message_text("❌ " + _short_exc(e))

        if data == "logs":
            candidates = ["/app/logs/oraculo.log", "/app/oraculo.log", "/app/log.txt"]
            text = None
            for p in candidates:
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()[-120:]
                    text = "".join(lines).strip()
                    break
                except Exception:
                    continue
            if not text:
                return await q.edit_message_text("🧾 Logs: no encontré archivo. (Usa Fly logs)")
            return await q.edit_message_text("🧾 Logs:\n<pre>" + text[-3500:] + "</pre>", parse_mode=ParseMode.HTML)

        if data == "settings":
            st = self.store.load_state()
            msg = (
                "⚙️ <b>Ajustes (hot)</b>\n\n"
                "Comandos:\n"
                "<code>/set risk 0.5</code>\n"
                "<code>/set lev 8</code>\n"
                "<code>/set maxpos 2</code>\n"
                "<code>/set scan 60</code>\n"
                "<code>/set whitelist BTC/USDT,ETH/USDT</code>\n"
                "<code>/set whitelist ALL</code>\n\n"
                f"Actual:\n<pre>{asdict(st)}</pre>"
            )
            return await q.edit_message_text(msg, parse_mode=ParseMode.HTML)

        if data.startswith("confirm:"):
            action = data.split(":", 1)[1]
            return await self._confirm(update, action)

        if data.startswith("do:"):
            action = data.split(":", 1)[1]
            if action == "cancel":
                self._pending_confirm.pop((update.effective_user.id, "close"), None)
                self._pending_confirm.pop((update.effective_user.id, "closeall"), None)
                self._pending_confirm.pop((update.effective_user.id, "cancelall"), None)
                return await q.edit_message_text("❌ Cancelado.")
            if action == "close":
                return await self._do_close(update)
            return await self._do_action(update, action)

        return await q.answer("Acción no reconocida", show_alert=True)

    async def _unknown_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update):
            return
        await update.message.reply_text("Usa /panel")

    async def start(self):
        if not self.enabled:
            return
        if not self.token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN no configurado")

        app = ApplicationBuilder().token(self.token).build()
        self._app = app

        app.add_handler(CommandHandler("panel", self.cmd_panel))
        app.add_handler(CommandHandler("status", self.cmd_status))
        app.add_handler(CommandHandler("pause", self.cmd_pause))
        app.add_handler(CommandHandler("resume", self.cmd_resume))
        app.add_handler(CommandHandler("autoon", self.cmd_autoon))
        app.add_handler(CommandHandler("autooff", self.cmd_autooff))
        app.add_handler(CommandHandler("set", self.cmd_set))
        app.add_handler(CommandHandler("balance", self.cmd_balance))
        app.add_handler(CommandHandler("positions", self.cmd_positions))
        app.add_handler(CommandHandler("orders", self.cmd_orders))
        app.add_handler(CommandHandler("close", self.cmd_close))
        app.add_handler(CommandHandler("logs", self.cmd_logs))
        app.add_handler(CallbackQueryHandler(self.on_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._unknown_text))

        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        if self.log:
            self.log.info("Telegram panel ONLINE")

    async def stop(self):
        if not self._app:
            return
        try:
            await self._app.updater.stop()
        except Exception:
            pass
        try:
            await self._app.stop()
        except Exception:
            pass
        try:
            await self._app.shutdown()
        except Exception:
            pass
        self._app = None