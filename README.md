# ORÁCULO PRO - Bot de Trading Automático (Futures Binance) - Versión 2026

## Características
- Escaneo multi-timeframe (5m/15m/1h) con detección de estructura (pivotes, BOS)
- Zonas de oferta/demanda con rechazo en 5m
- Momentum en 5m (ATR, volumen relativo, cuerpo vela, RSI)
- Filtros de régimen (tendencia/rango), sesión, funding dinámico, spread
- Ejecución automática con SL/TP (STOP_MARKET / TAKE_PROFIT_MARKET) con parámetros robustos
- Gestión de posición avanzada (TP parcial, break-even, trailing)
- Gestión de riesgo: límite diario en tiempo real, cooldowns, máx posiciones concurrentes, límite por sector, stop por racha de pérdidas
- Persistencia en SQLite con transacciones atómicas y PnL real
- Reintentos robustos con tenacity
- Reportes de rendimiento

## Instalación (Windows)
1) Crear entorno virtual
python -m venv .venv
.venv\Scripts\activate

2) Instalar dependencias
pip install -r requirements.txt

3) Variables de entorno
copy .env.example .env
(edita .env con tus claves)

4) Inicializar BD
python -c "from oraculo_bot.storage.db import Database; Database().init_db()"

5) Ejecutar
python -m oraculo_bot.main

## Reporte
python tools\report.py