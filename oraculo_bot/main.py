import asyncio
import time
from oraculo_bot.config import load_settings
from oraculo_bot.logger import setup_logger
from oraculo_bot.exchange.binance_client import BinanceClient
from oraculo_bot.data.market_data import MarketData
from oraculo_bot.storage.db import Database
from oraculo_bot.storage.trade_store import TradeStore
from oraculo_bot.storage.daily_tracker import DailyTracker
from oraculo_bot.execution.order_manager import OrderManager
from oraculo_bot.execution.trade_state import TradeStateMachine
from oraculo_bot.execution.position_manager import PositionManager
from oraculo_bot.risk.risk_manager import RiskManager
from oraculo_bot.risk.dynamic_funding import FundingFilter
from oraculo_bot.risk.metrics_tracker import MetricsTracker
from oraculo_bot.core.scheduler import Scheduler
from oraculo_bot.core.reconciler import Reconciler
from oraculo_bot.notifier.telegram import TelegramNotifier
from oraculo_bot.universe import build_universe
from oraculo_bot.strategy.signal_engine import compute_signal

log = setup_logger()

async def healthcheck_loop(ex, settings):
    md = MarketData(ex)
    while True:
        try:
            latency = await md.ping()
            if latency > settings.max_latency_ms:
                log.warning(f"Latencia alta: {latency:.0f} ms > {settings.max_latency_ms}")
        except Exception as e:
            log.error(f"Healthcheck error: {e}")
        await asyncio.sleep(settings.healthcheck_interval_sec)

async def main():
    settings = load_settings()
    log.info("Oráculo Pro iniciando...")

    db = Database()
    db.init_db()

    ex = BinanceClient(settings.api_key, settings.api_secret, settings.market_type)
    market_data = MarketData(ex)
    trade_store = TradeStore(db)
    daily_tracker = DailyTracker(db)
    notifier = TelegramNotifier(settings.tg_token, settings.tg_chat_id)

    funding_filter = FundingFilter(
        lookback_days=settings.funding_lookback_days,
        p_high=settings.funding_percentile_high,
        p_low=settings.funding_percentile_low,
        db=db
    )
    metrics_tracker = MetricsTracker(settings)

    order_mgr = OrderManager(ex)
    state_machine = TradeStateMachine(trade_store)
    risk_mgr = RiskManager(settings, trade_store, daily_tracker)
    position_mgr = PositionManager(ex, order_mgr, trade_store, settings, risk_mgr)
    position_mgr.set_metrics_tracker(metrics_tracker)

    reconciler = Reconciler(ex, trade_store)

    scheduler = Scheduler(settings, market_data, order_mgr, trade_store,
                          state_machine, position_mgr, risk_mgr, notifier,
                          funding_filter=funding_filter)

    symbols = settings.symbols
    if settings.auto_universe:
        log.info("Construyendo universo automático...")
        try:
            await ex.load_markets()
            symbols = await build_universe(ex, settings.price_max, settings.auto_universe_max_symbols)
            log.info(f"Universe: {len(symbols)} símbolos")
        except Exception as e:
            log.error(f"Auto universe falló: {e}")
            symbols = settings.symbols

    auto_trading_enabled = settings.auto_trading
    log.info(f"Auto trading: {auto_trading_enabled}")

    asyncio.create_task(healthcheck_loop(ex, settings))

    try:
        while True:
            try:
                await reconciler.run_once()

                try:
                    balance_info = await ex.fetch_balance()
                    usdt_balance = balance_info.get('USDT', {}).get('total', 0)
                    if usdt_balance > 0:
                        metrics_tracker.update_balance(usdt_balance)
                        today = time.localtime().tm_yday
                        if today != metrics_tracker.last_reset_day:
                            metrics_tracker.reset_daily()
                        stop_reason = metrics_tracker.check_limits()
                        if stop_reason:
                            log.critical(f"Métrica crítica: {stop_reason}. Apagando auto trading.")
                            auto_trading_enabled = False
                            await notifier.send(f"⛔ Auto trading desactivado por: {stop_reason}")
                except Exception as e:
                    log.error(f"Error actualizando balance: {e}")

                if auto_trading_enabled:
                    await scheduler.run_once(symbols)
                else:
                    for sym in symbols[:10]:
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

                await asyncio.sleep(settings.scan_interval_seconds)

            except Exception:
                log.exception("Error en loop principal")
                await asyncio.sleep(5)
    finally:
        await ex.close()

if __name__ == "__main__":
    asyncio.run(main())