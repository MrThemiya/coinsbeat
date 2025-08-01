import psycopg2
import asyncio
import logging
from datetime import datetime, timedelta
import os

logger = logging.getLogger(__name__)

TRACKED_SYMBOLS = ['btc', 'eth', 'sol']

conn_alerts = psycopg2.connect(os.environ["DATABASE_URL"])
c_alerts = conn_alerts.cursor()

conn_prices = psycopg2.connect(os.environ["DATABASE_URL"])
c_prices = conn_prices.cursor()

# --- Store previously sent alert levels ---
sent_alerts = {
    '15m': {s: set() for s in TRACKED_SYMBOLS},
    '1h': {s: set() for s in TRACKED_SYMBOLS},
    '24h': {s: set() for s in TRACKED_SYMBOLS},
    '7d': {s: set() for s in TRACKED_SYMBOLS},
}

# --- Load price from DB ---
def get_cached_price(symbol):
    c_prices.execute("SELECT price FROM price_cache WHERE symbol=%s", (symbol,))
    row = c_prices.fetchone()
    return row[0] if row else None

# --- Get all unique user IDs ---
def get_all_user_ids():
    c_alerts.execute("SELECT DISTINCT user_id FROM alerts")
    return [row[0] for row in c_alerts.fetchall()]

# --- Track price history for all timeframes ---
price_history = {
    '15m': {},
    '1h': {},
    '24h': {},
    '7d': {},
}

# --- Analyze price changes and return message list ---
def check_price_change(symbol, current_price):
    now = datetime.now()
    messages = []

    timeframes = {
        '15m': timedelta(minutes=15),
        '1h': timedelta(hours=1),
        '24h': timedelta(hours=24),
        '7d': timedelta(days=7)
    }

    for tf, delta in timeframes.items():
        old = price_history[tf].get(symbol)
        if not old:
            price_history[tf][symbol] = (now, current_price)
            continue

        old_time, old_price = old
        if now - old_time >= delta:
            price_history[tf][symbol] = (now, current_price)
            continue

        change = ((current_price - old_price) / old_price) * 100
        change = round(change, 2)

        for level in [5, 10, 20]:
            if abs(change) >= level and level not in sent_alerts[tf][symbol]:
                direction = "⬆️ Pumped" if change > 0 else "⬇️ Crashed"
                msg = (
                    f"*{symbol.upper()}* {direction} by {abs(change)}% in the last {tf}!\n"
                    f"Current Price: ${current_price}"
                )
                messages.append((tf, level, msg))

    return messages

# --- Main auto alert loop ---
async def auto_price_watcher(app):
    while True:
        try:
            for symbol in TRACKED_SYMBOLS:
                current_price = get_cached_price(symbol)
                if not current_price:
                    continue

                alerts = check_price_change(symbol, current_price)

                for tf, level, message in alerts:
                    sent_alerts[tf][symbol].add(level)
                    for user_id in get_all_user_ids():
                        await app.bot.send_message(chat_id=user_id, text=message, parse_mode="Markdown")

        except Exception as e:
            logger.error(f"Alert loop error: {e}")

        await asyncio.sleep(60)  # check every minute
