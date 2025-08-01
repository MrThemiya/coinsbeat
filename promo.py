import psycopg2
import logging
from telegram.ext import ContextTypes
import os

# === Setup Logging ===
logger = logging.getLogger(__name__)

# === Get All Users ===
def get_all_users():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
    c.execute("SELECT user_id FROM users")
    users = [row[0] for row in c.fetchall()]
    conn.close()
    return users

# === Send Weekly Promo Message ===
async def send_weekly_promo(context: ContextTypes.DEFAULT_TYPE):
    logger.info("📢 Sending weekly promotional message...")
    
    promo_msg = (
        "💎 *Access Premium* at the cheapest price: *just $*!\n"
        "🚀 Limited-time offer – upgrade now while it lasts!"
    )

    for user_id in get_all_users():
        try:
            await context.bot.send_message(chat_id=user_id, text=promo_msg, parse_mode="Markdown")
            logger.info(f"✅ Promo sent to user {user_id}")
        except Exception as e:
            logger.error(f"❌ Failed to send promo to {user_id}: {e}")
