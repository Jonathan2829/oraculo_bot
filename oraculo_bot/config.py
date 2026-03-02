import os
import time
from dataclasses import dataclass
from typing import List, Tuple
from dotenv import load_dotenv

load_dotenv()

def _f(name: str, default: str = "") -> str:
    v = os.getenv(name, default)
    return v.strip() if isinstance(v, str) else ("" if v is None else str(v).strip())

def _b(name: str, default: bool) -> bool:
    val = _f(name, "true" if default else "false").lower()
    return val in ("true", "1", "yes", "y", "on")

def _i(name: str, default: int) -> int:
    raw = _f(name, str(default))
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"ENV inválido: {name} debe ser int, recibido: {raw!r}")

def _fl(name: str, default: float) -> float:
    raw = _f(name, str(default))
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"ENV inválido: {name} debe ser float, recibido: {raw!r}")

def _require(name: str) -> str:
    v = _f(name, "")
    if not v:
        raise ValueError(f"Falta ENV obligatorio: {name}")
    return v

def parse_session_ranges(session_str: str) -> List[Tuple[int, int]]:
    if not session_str:
        return []
    ranges = []
    for part in session_str.split(','):
        if '-' not in part:
            continue
        start_str, end_str = part.split('-')
        start = int(start_str)
        end = int(end_str)
        if start <= end:
            ranges.append((start, end))
        else:
            ranges.append((start, 24))
            ranges.append((0, end))
    return ranges

@dataclass(frozen=True)
class Settings:
    # Binance
    api_key: str
    api_secret: str
    market_type: str

    # Telegram
    tg_token: str
    tg_chat_id: str

    # Universe
    symbols: List[str]
    auto_universe: bool
    auto_universe_max_symbols: int
    price_max: float

    # Timeframes
    tf_trigger: str
    tf_trend: str
    tf_confirm: str

    # Capital y riesgo
    capital_usdt: float
    risk_per_trade: float
    max_sl_pct: float
    leverage: int
    daily_max_loss_usdt: float

    # Límites
    max_trades_per_hour: int
    max_concurrent_positions: int
    cooldown_after_loss_sec: int
    max_consecutive_losses: int

    # Timeouts
    entry_timeout_sec: int
    protective_timeout_sec: int
    max_holding_sec: int

    # Healthcheck
    healthcheck_interval_sec: int
    max_latency_ms: int

    # Momentum
    atr_pct_min: float
    vol_rel_min: float
    body_pct_min: float
    atr_expand_min: float
    rsi_long_min: int
    rsi_short_max: int
    rsi_neutral_low: int
    rsi_neutral_high: int

    # Estructura
    pivot_left: int
    pivot_right: int
    bos_lookback_pivots: int
    pullback_max_retrace: float
    score_min: int

    # SL/TP
    atr_period: int
    tp2_r_mult: float

    # Zonas + rechazo
    zone_width_k: float
    rejection_min_wick: float
    rejection_require_close_in: bool
    zone_sl_buffer: float

    # Régimen
    adx_threshold: int
    allow_range_trades: bool
    session_ranges: List[Tuple[int, int]]

    # Métricas
    max_drawdown_percent: float

    # Funding
    funding_lookback_days: int
    funding_percentile_high: int
    funding_percentile_low: int

    # Spread
    max_spread_pct: float

    # Escaneo
    scan_interval_seconds: int
    cooldown_minutes: int
    cooldown_per_side: bool

    # Auto trading
    auto_trading: bool

def load_settings() -> Settings:
    symbols_raw = _f("SYMBOLS", "")
    symbols = [s.strip() for s in symbols_raw.split(",") if s.strip()] if symbols_raw else ["ADA/USDT"]
    session_str = _f("SESSION_RANGES", "8-16,20-4")
    session_ranges = parse_session_ranges(session_str)

    return Settings(
        api_key=_require("BINANCE_API_KEY"),
        api_secret=_require("BINANCE_API_SECRET"),
        market_type=_f("BINANCE_MARKET_TYPE", "futures").lower(),

        tg_token=_require("TELEGRAM_BOT_TOKEN"),
        tg_chat_id=_require("TELEGRAM_CHAT_ID"),

        symbols=symbols,
        auto_universe=_b("AUTO_UNIVERSE", False),
        auto_universe_max_symbols=_i("AUTO_UNIVERSE_MAX_SYMBOLS", 60),
        price_max=_fl("PRICE_MAX", 1.0),

        tf_trigger=_f("TF_TRIGGER", "5m"),
        tf_trend=_f("TF_TREND", "15m"),
        tf_confirm=_f("TF_CONFIRM", "1h"),

        capital_usdt=_fl("CAPITAL_USDT", 100.0),
        risk_per_trade=_fl("RISK_PER_TRADE", 0.005),
        max_sl_pct=_fl("MAX_SL_PCT", 0.05),
        leverage=_i("LEVERAGE", 5),
        daily_max_loss_usdt=_fl("DAILY_MAX_LOSS_USDT", 20.0),

        max_trades_per_hour=_i("MAX_TRADES_PER_HOUR", 10),
        max_concurrent_positions=_i("MAX_CONCURRENT_POSITIONS", 4),
        cooldown_after_loss_sec=_i("COOLDOWN_AFTER_LOSS_SEC", 600),
        max_consecutive_losses=_i("MAX_CONSECUTIVE_LOSSES", 6),

        entry_timeout_sec=_i("ENTRY_TIMEOUT_SEC", 15),
        protective_timeout_sec=_i("PROTECTIVE_TIMEOUT_SEC", 5),
        max_holding_sec=_i("MAX_HOLDING_SEC", 3600),

        healthcheck_interval_sec=_i("HEALTHCHECK_INTERVAL_SEC", 30),
        max_latency_ms=_i("MAX_LATENCY_MS", 500),

        atr_pct_min=_fl("ATR_PCT_MIN", 0.0035),
        vol_rel_min=_fl("VOL_REL_MIN", 1.30),
        body_pct_min=_fl("BODY_PCT_MIN", 0.0020),
        atr_expand_min=_fl("ATR_EXPAND_MIN", 1.05),
        rsi_long_min=_i("RSI_LONG_MIN", 52),
        rsi_short_max=_i("RSI_SHORT_MAX", 48),
        rsi_neutral_low=_i("RSI_NEUTRAL_LOW", 48),
        rsi_neutral_high=_i("RSI_NEUTRAL_HIGH", 52),

        pivot_left=_i("PIVOT_LEFT", 2),
        pivot_right=_i("PIVOT_RIGHT", 2),
        bos_lookback_pivots=_i("BOS_LOOKBACK_PIVOTS", 6),
        pullback_max_retrace=_fl("PULLBACK_MAX_RETRACE", 0.55),
        score_min=_i("SCORE_MIN", 80),

        atr_period=_i("ATR_PERIOD", 14),
        tp2_r_mult=_fl("TP2_R_MULT", 1.6),

        zone_width_k=_fl("ZONE_WIDTH_K", 0.35),
        rejection_min_wick=_fl("REJECTION_MIN_WICK", 0.45),
        rejection_require_close_in=_b("REJECTION_REQUIRE_CLOSE_IN", True),
        zone_sl_buffer=_fl("ZONE_SL_BUFFER", 0.35),

        adx_threshold=_i("ADX_THRESHOLD", 25),
        allow_range_trades=_b("ALLOW_RANGE_TRADES", False),
        session_ranges=session_ranges,

        max_drawdown_percent=_fl("MAX_DRAWDOWN_PERCENT", 15.0),

        funding_lookback_days=_i("FUNDING_LOOKBACK_DAYS", 7),
        funding_percentile_high=_i("FUNDING_PERCENTILE_HIGH", 95),
        funding_percentile_low=_i("FUNDING_PERCENTILE_LOW", 5),

        max_spread_pct=_fl("MAX_SPREAD_PCT", 0.03),

        scan_interval_seconds=_i("SCAN_INTERVAL_SECONDS", 60),
        cooldown_minutes=_i("COOLDOWN_MINUTES", 30),
        cooldown_per_side=_b("COOLDOWN_PER_SIDE", True),

        auto_trading=_b("AUTO_TRADING", False),
    )