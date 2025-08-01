import psycopg2
from datetime import datetime
from fetch_prices import fetch_prices  # ✅ centralized import
import asyncio
import os

conn = psycopg2.connect(os.environ["DATABASE_URL"])
c = conn.cursor()

# Create table for cached prices
c.execute("""
CREATE TABLE IF NOT EXISTS token_prices (
    symbol TEXT PRIMARY KEY,
    price REAL,
    last_updated TEXT
)
""")
conn.commit()

async def update_prices_loop():
    while True:
        try:
            prices = await fetch_prices()  # ✅ uses centralized fetch_prices
            now = datetime.utcnow().isoformat()
            for symbol, price in prices.items():
                c.execute(
                    "INSERT INTO token_prices (symbol, price, last_updated) VALUES (%s, %s, %s) ON CONFLICT (symbol) DO UPDATE SET price = EXCLUDED.price, last_updated = EXCLUDED.last_updated",
                    (symbol, price, now)
                )
            conn.commit()
        except Exception as e:
            print(f"Price update error: {e}")
        await asyncio.sleep(15)

def get_price_from_db(symbol):
    c.execute("SELECT price FROM token_prices WHERE symbol=%s", (symbol,))
    row = c.fetchone()
    return row[0] if row else None

