import asyncio
import signal
import time

from oraculo_bot.config import load_settings
from oraculo_bot.logger import setup_logger

from oraculo_bot.storage.db import init_db
from oraculo_bot.exchange.binance_client import BinanceClient
from oraculo_bot.data.market_data import MarketData

from oraculo_bot.notifier.telegram import TelegramNotifier
from oraculo_bot.universe import build_universe
from oraculo_bot.strategy.signal_engine import compute_signal

from oraculo_bot.core.scheduler import Scheduler
from oraculo_bot.core.reconciler import Reconciler
from oraculo_bot.risk.dynamic_funding import FundingFilter
from oraculo_bot.risk.metrics_tracker import MetricsTracker

from oraculo_bot.execution.order_manager import OrderManager
from oraculo_bot.execution.trade_state import TradeStateMachine
from oraculo_bot.execution.position_manager import PositionManager
from oraculo_bot.risk.risk_manager import RiskManager
from oraculo_bot.storage.trade_store import TradeStore
from oraculo_bot.storage.daily_tracker import DailyTracker

# ✅ NUEVO: runtime + panel
from oraculo_bot.core.runtime import RuntimeStore, RuntimeState
from oraculo_bot.telegram.panel import TelegramPanel, ExchangeAdapter


async def healthcheck_loop(ex, settings, log):
    md = MarketData(ex)
    while True:
        try:
            latency = await md.ping()
            if latency > settings.max_latency_ms:
                log.warning(f"Latencia alta: {latency:.0f} ms > {settings.max_latency_ms}")
        except Exception as e:
            log.error(f"Healthcheck error: {e}")
        await asyncio.sleep(getattr(settings, "healthcheck_interval_sec", 30))


async def main():
    settings = load_settings()
    log = setup_logger()

    log.info("Oráculo Pro iniciando...")
    log.info(f"Auto trading (settings): {getattr(settings, 'auto_trading', False)}")

    # --- Graceful shutdown ---
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _stop():
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            # Windows puede fallar con add_signal_handler
            pass

    # --- DB ---
    db = init_db(getattr(settings, "db_path", None))

    # --- Exchange ---
    ex = BinanceClient(settings.api_key, settings.api_secret, settings.market_type)
    market_data = MarketData(ex)

    # --- Stores / Managers ---
    trade_store = TradeStore(db)
    daily_tracker = DailyTracker(db)
    notifier = TelegramNotifier(settings.tg_token, settings.tg_chat_id)

    funding_filter = FundingFilter(
        lookback_days=settings.funding_lookback_days,
        p_high=settings.funding_percentile_high,
        p_low=settings.funding_percentile_low,
        db=db,
    )
    metrics_tracker = MetricsTracker(settings)

    order_mgr = OrderManager(ex)
    state_machine = TradeStateMachine(trade_store)
    risk_mgr = RiskManager(settings, trade_store, daily_tracker)

    position_mgr = PositionManager(ex, order_mgr, trade_store, settings, risk_mgr)
    position_mgr.set_metrics_tracker(metrics_tracker)

    reconciler = Reconciler(ex, trade_store)

    scheduler = Scheduler(
        settings,
        market_data,
        order_mgr,
        trade_store,
        state_machine,
        position_mgr,
        risk_mgr,
        notifier,
        funding_filter,
    )

    # --- Universe ---
    symbols = list(getattr(settings, "symbols", []) or [])
    if getattr(settings, "auto_universe", False):
        log.info("Construyendo universo automático...")
        try:
            await ex.load_markets()
            symbols = await build_universe(ex, settings.price_max, settings.auto_universe_max_symbols)
            log.info(f"Universe OK: {len(symbols)} símbolos")
        except Exception as e:
            log.error(f"Auto universe falló: {e}")
            symbols = list(getattr(settings, "symbols", []) or [])

    # --- ✅ Runtime config (hot reload) ---
    runtime_store = RuntimeStore(db)
    runtime_store.ensure_defaults(RuntimeState())

    # --- ✅ Telegram Panel ---
    exchange_adapter = ExchangeAdapter(ex)
    panel = TelegramPanel(runtime_store, exchange_adapter=exchange_adapter, logger=log)
    asyncio.create_task(panel.start())

    # --- Background tasks ---
    asyncio.create_task(healthcheck_loop(ex, settings, log))

    try:
        while not stop_event.is_set():
            try:
                # --- Cargar runtime state ---
                rt = runtime_store.load_state()

                if rt.paused:
                    log.info("⏸ Bot pausado por Telegram. Durmiendo...")
                    await asyncio.sleep(5)
                    continue

                # Aplicar valores dinámicos
                auto_trading_enabled = rt.auto_trading
                scan_interval = rt.scan_interval_seconds
                whitelist = rt.whitelist_symbols

                # Filtrar símbolos por whitelist
                if whitelist:
                    whitelist_set = {s.upper() for s in whitelist}
                    symbols_to_scan = [s for s in symbols if s.upper() in whitelist_set]
                else:
                    symbols_to_scan = symbols

                # Reconciliación
                await reconciler.run_once()

                # Métricas / límites (max drawdown, etc.)
                try:
                    balance_info = await ex.fetch_balance()
                    usdt_total = 0.0
                    if isinstance(balance_info, dict):
                        # intenta estructura común
                        if "USDT" in balance_info and isinstance(balance_info["USDT"], dict):
                            usdt_total = float(balance_info["USDT"].get("total") or 0)
                        elif "total" in balance_info and isinstance(balance_info["total"], dict):
                            usdt_total = float(balance_info["total"].get("USDT") or 0)

                    if usdt_total > 0:
                        metrics_tracker.update_balance(usdt_total)

                        today = time.localtime().tm_yday
                        if today != metrics_tracker.last_reset_day:
                            metrics_tracker.reset_daily()

                        stop_reason = metrics_tracker.check_limits()
                        if stop_reason:
                            log.critical(f"Métrica crítica: {stop_reason}. Apagando auto trading.")
                            auto_trading_enabled = False
                            runtime_store.update(auto_trading=False)
                            await notifier.send(f"⛔ Auto trading desactivado por: {stop_reason}")

                except Exception as e:
                    log.error(f"Error actualizando balance: {e}")

                # --- Core loop ---
                if auto_trading_enabled:
                    await scheduler.run_once(symbols_to_scan)
                else:
                    # Solo alertas (modo observación)
                    for sym in symbols_to_scan[:10]:
                        sig = await compute_signal(sym, settings, market_data, funding_filter)
                        if sig:
                            msg = (
                                f"<b>ALERTA</b>\n"
                                f"{sym} | {sig['side']} | Score {sig['score']}\n"
                                f"Entry: {sig['entry']:.6f}\n"
                                f"SL: {sig['sl']:.6f}\n"
                                f"TP1: {sig['tp1']:.6f}"
                            )
                            await notifier.send(msg)
                        await asyncio.sleep(0.1)

                # Esperar intervalo dinámico o señal de stop
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=max(5, int(scan_interval)))
                except asyncio.TimeoutError:
                    pass

            except Exception:
                log.exception("Error en loop principal")
                await asyncio.sleep(5)

    except asyncio.CancelledError:
        log.info("Shutdown recibido (CancelledError). Cerrando limpio...")

    finally:
        log.info("Cerrando exchange y panel...")

        # 1) Cierra exchange
        try:
            await ex.close()
        except Exception:
            pass

        # 2) Stop panel (según tu instrucción: después del exchange)
        try:
            await panel.stop()
        except Exception:
            pass

        log.info("✅ Shutdown completo.")


if __name__ == "__main__":
    asyncio.run(main())