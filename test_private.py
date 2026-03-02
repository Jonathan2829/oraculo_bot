import asyncio, os
from dotenv import load_dotenv
from oraculo_bot.exchange.binance_client import BinanceClient

async def main():
    load_dotenv()
    client = BinanceClient(
        api_key=os.getenv("BINANCE_API_KEY",""),
        api_secret=os.getenv("BINANCE_API_SECRET",""),
        market_type=os.getenv("BINANCE_MARKET_TYPE","futures"),
        testnet=(os.getenv("BINANCE_TESTNET","false").lower()=="true")
    )
    try:
        print("Probando balance...")
        bal = await client.fetch_balance()
        print("Balance OK. keys:", list(bal.keys())[:10])
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())
