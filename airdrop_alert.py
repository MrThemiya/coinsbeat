import requests
import psycopg2
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from limits import check_access
import datetime
import os
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === API source ===
AIRDROP_SOURCE_URL = os.environ.get("AIRDROP_SOURCE_URL")
if not AIRDROP_SOURCE_URL:
    logger.error("AIRDROP_SOURCE_URL environment variable not set")
else:
    logger.info("AIRDROP_SOURCE_URL is set")

# === Initialize DB ===
def init_airdrop_db():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    try:
        # Add last_airdrop_sent column to users table if not exists
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_airdrop_sent TEXT")
    except psycopg2.Error as e:
        logger.error(f"Failed to alter users table: {e}")
    try:
        # Create airdrops table with created_at
        c.execute("""
            CREATE TABLE IF NOT EXISTS airdrops (
                id TEXT PRIMARY KEY,
                name TEXT,
                network TEXT,
                category TEXT,
                description TEXT,
                url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    except psycopg2.Error as e:
        logger.error(f"Failed to create airdrops table: {e}")
    conn.commit()
    conn.close()

# === Fetch from external API ===
def fetch_airdrops():
    try:
        r = requests.get(AIRDROP_SOURCE_URL)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Airdrop API fetch failed: {e}")
        return []

# === Save to DB ===
def fetch_and_store_airdrops():
    drops = fetch_airdrops()
    if not drops:
        return

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    for drop in drops:
        c.execute("""
            INSERT INTO airdrops (id, name, network, category, description, url)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                network = EXCLUDED.network,
                category = EXCLUDED.category,
                description = EXCLUDED.description,
                url = EXCLUDED.url
        """, (
            drop.get("id"),
            drop.get("name"),
            drop.get("network"),
            drop.get("category"),
            drop.get("description"),
            drop.get("url")
        ))
    conn.commit()
    conn.close()

# === Read from DB ===
def get_stored_airdrops(limit=5):
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    c.execute("SELECT id, name, network, category, description, url FROM airdrops ORDER BY created_at DESC LIMIT %s", (limit,))
    rows = c.fetchall()
    conn.close()

    drops = []
    for row in rows:
        drops.append({
            "id": row[0],
            "name": row[1],
            "network": row[2],
            "category": row[3],
            "description": row[4],
            "url": row[5]
        })
    return drops

def get_latest_airdrops():
    drops = get_stored_airdrops()
    if not drops:
        return "No airdrops available right now."

    return format_airdrop_message(drops)

# === Format message ===
def format_airdrop_message(drops):
    text = "*Latest Airdrops:*\n\n"
    for drop in drops:
        text += f"🔸 *{drop['name']}* ({drop['network']})\n"
        text += f"_{drop['category']}_\n"
        text += f"{drop['description']}\n"
        if drop['url']:
            text += f"[Visit Airdrop]({drop['url']})\n"
        text += "\n"
    return text

# === Daily sending ===
def get_users_to_notify():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    today = str(datetime.date.today())
    c.execute("SELECT user_id, last_airdrop_sent FROM users")
    users = c.fetchall()
    conn.close()
    return [uid for uid, last in users if last is None or str(last) != today]

def mark_airdrop_sent(user_id):
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    today = str(datetime.date.today())
    c.execute("UPDATE users SET last_airdrop_sent=%s WHERE user_id=%s", (today, user_id))
    conn.commit()
    conn.close()

async def send_daily_airdrop_alerts(context: ContextTypes.DEFAULT_TYPE):
    drops = get_stored_airdrops()
    if not drops:
        return

    text = format_airdrop_message(drops)

    for user_id in get_users_to_notify():
        if not isinstance(user_id, int):
            logger.error(f"Invalid user_id in notify list: {user_id}")
            continue
        if not check_access(user_id, "airdrop"):
            continue
        try:
            await context.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
            mark_airdrop_sent(user_id)
        except Exception as e:
            logger.error(f"Failed to send airdrop to {user_id}: {e}")

# === Manual command ===
async def manual_airdrop_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not isinstance(user_id, int):
        logger.error(f"Invalid user_id: {user_id} is not an integer")
        await update.message.reply_text("❌ Invalid user ID.")
        return
    if not check_access(user_id, "airdrop"):
        await update.message.reply_text("This feature is only for *Pro* users. Please upgrade.", parse_mode="Markdown")
        return

    drops = get_stored_airdrops()
    if not drops:
        await update.message.reply_text("No airdrops available at the moment.")
        return

    text = format_airdrop_message(drops)
    await update.message.reply_text(text, parse_mode="Markdown")

# === Register everything ===
def register_airdrop_handlers(application):
    init_airdrop_db()  # Ensure table is created on startup

    application.add_handler(CommandHandler("airdrop_alert", manual_airdrop_alert))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(fetch_and_store_airdrops, "interval", hours=8)  # Fetch API 3x/day
    scheduler.add_job(lambda: send_daily_airdrop_alerts(application), "interval", hours=24)  # Alert 1x/day
    scheduler.start()

    fetch_and_store_airdrops()  # Initial fetch



