import psycopg2
from datetime import datetime
from fetch_prices import fetch_prices  # ✅ centralized import
import asyncio
import os

def init_db():
    try:
        with psycopg2.connect(os.environ["DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS token_prices (
                        symbol TEXT PRIMARY KEY,
                        price REAL,
                        last_updated TEXT
                    )
                """)
                conn.commit()
    except psycopg2.Error as e:
        print(f"Database initialization error: {e}")
        raise

async def update_prices_loop():
    while True:
        try:
            prices = await fetch_prices()  # ✅ uses centralized fetch_prices
            now = datetime.utcnow().isoformat()
            with psycopg2.connect(os.environ["DATABASE_URL"]) as conn:
                with conn.cursor() as cur:
                    for symbol, price in prices.items():
                        cur.execute(
                            "INSERT INTO token_prices (symbol, price, last_updated) VALUES (%s, %s, %s) ON CONFLICT (symbol) DO UPDATE SET price = EXCLUDED.price, last_updated = EXCLUDED.last_updated",
                            (symbol, price, now)
                        )
                    conn.commit()
        except psycopg2.Error as e:
            print(f"Database error in update_prices_loop: {e}")
        except Exception as e:
            print(f"Price update error: {e}")
        await asyncio.sleep(15)

def get_price_from_db(symbol):
    try:
        with psycopg2.connect(os.environ["DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT price FROM token_prices WHERE symbol=%s", (symbol,))
                row = cur.fetchone()
                return row[0] if row else None
    except psycopg2.Error as e:
        print(f"Database error in get_price_from_db: {e}")
        return None