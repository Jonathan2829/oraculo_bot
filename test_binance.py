import asyncio
from oraculo_bot.exchange.binance_client import BinanceClient


async def main():
    # ✅ MODO PUBLICO: sin keys
    client = BinanceClient(market_type="futures", testnet=False)

    try:
        print("Cargando mercados...")
        markets = await client.load_markets()
        print("Markets cargados:", len(markets))

        print("Descargando OHLCV BTC/USDT...")
        ohlcv = await client.fetch_ohlcv("BTC/USDT", "1m", limit=5)
        print("Velas recibidas:", len(ohlcv))
        print("Primera vela:", ohlcv[0])

        print("OK ✅ Market data funciona")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())