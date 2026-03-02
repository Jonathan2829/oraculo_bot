import asyncio
import os
from dotenv import load_dotenv
import ccxt.async_support as ccxt

load_dotenv(".env", override=True)

async def main():
    ex = ccxt.binanceusdm({
        "apiKey": os.getenv("BINANCE_API_KEY"),
        "secret": os.getenv("BINANCE_API_SECRET"),
        "enableRateLimit": True,
    })

    try:
        print("Probando balance...")
        bal = await ex.fetch_balance()
        print("OK ✅")
        print("Total keys:", len(bal))
    except Exception as e:
        print("ERROR:")
        print(str(e))
    finally:
        await ex.close()

asyncio.run(main())