import requests
import psycopg2
from telegram import Update
from telegram.ext import ContextTypes, Application
import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
import logging
import re
from promo import send_weekly_promo
from telegram.helpers import escape_markdown
import os

# === Setup logging ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === TwitterAPI.io Config ===
API_KEY = os.environ.get("TWITTER_API_KEY")
if not API_KEY:
    print("i needTWITTER_API_KEY")
else:
    print("i have TWITTER_API_KEY")
BASE_URL = "https://api.twitterapi.io"
HEADERS = {"X-API-Key": API_KEY}

# === Clean tweet text (remove URLs) ===
def clean_text(text):
    return re.sub(r'https?://\S+', '', text).strip()

# === Get Recent Tweets from API ===
def get_all_recent_tweets():
    logger.info("Fetching tweets from API...")
    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS last_tweet (id INTEGER PRIMARY KEY, tweet_id TEXT)")
        c.execute("SELECT tweet_id FROM last_tweet WHERE id = 1")
        result = c.fetchone()
        latest_tweet_id = result[0] if result else None

        params = {"userName": "Ashcryptoreal", "count": 2}
        response = requests.get(f"{BASE_URL}/twitter/user/last_tweets", headers=HEADERS, params=params)
        response.raise_for_status()
        tweets_data = response.json()

        tweet_list = tweets_data.get("data", {}).get("tweets", [])
        if not tweet_list:
            logger.info("🚫 API returned empty tweet list.")
            return []

        filtered = []
        KEYWORDS = ["BREAKING"]

        for tweet in tweet_list:
            if tweet.get("retweeted_tweet") or tweet.get("quoted_tweet"):
                continue
            tweet_id = tweet["id"]
            text = clean_text(tweet["text"])
            if any(keyword.lower() in text.lower() for keyword in KEYWORDS):
                filtered.append((tweet_id, text))

        if filtered:
            latest_tweet_id = filtered[0][0]
            c.execute("INSERT INTO last_tweet (id, tweet_id) VALUES (1, %s) ON CONFLICT (id) DO UPDATE SET tweet_id = EXCLUDED.tweet_id", (str(latest_tweet_id),))
            conn.commit()

        conn.close()
        return filtered
    except Exception as e:
        logger.error(f"❌ Failed to fetch tweets: {e}")
        return []

# === DB Init ===
def init_news_db():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()

    # sent_news and last_tweet tables
    c.execute("CREATE TABLE IF NOT EXISTS sent_news (tweet_id TEXT PRIMARY KEY, tweet TEXT, date_sent TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS last_tweet (id INTEGER PRIMARY KEY, tweet_id TEXT)")

    # Check and add columns to users table
    c.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'users'")
    columns = [row[0] for row in c.fetchall()]

    if 'auto_news' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN auto_news INTEGER DEFAULT 1")

    if 'package' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN package TEXT DEFAULT 'free'")

    conn.commit()
    conn.close()

# === Daily Cleanup ===
def clear_old_news(days=1):
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    c.execute("DELETE FROM sent_news WHERE date_sent < %s", (cutoff,))
    conn.commit()
    conn.close()

# === Manual Trigger ===
async def manual_news_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Manual news triggered...")
    all_tweets = get_all_recent_tweets()
    today = datetime.date.today().isoformat()

    if all_tweets:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS sent_news (tweet_id TEXT PRIMARY KEY, tweet TEXT, date_sent TEXT)")
        for tweet_id, text in all_tweets:
            c.execute("INSERT INTO sent_news (tweet_id, tweet, date_sent) VALUES (%s, %s, %s) ON CONFLICT (tweet_id) DO NOTHING", (tweet_id, text, today))
        conn.commit()
        conn.close()

    msg = get_latest_news()
    try:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode="Markdown")
        logger.info("✅ Manual news sent.")
    except Exception as e:
        logger.error(f"❌ Failed to send manual news: {e}")

# === Get Saved News ===
def get_latest_news():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    today = datetime.date.today().isoformat()
    c.execute("SELECT tweet FROM sent_news WHERE date_sent = %s", (today,))
    saved_tweets = [row[0] for row in c.fetchall()]
    conn.close()

    if not saved_tweets:
        return "🚫 No news available in the database."

    msg = "📰 *Crypto News (last 24h):*\n\n"
    for t in saved_tweets:
        msg += f"🔹 {t}\n\n"
    return msg

# === Get Users ===
def get_all_users():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, auto_news INTEGER DEFAULT 1, package TEXT DEFAULT 'free')")
    c.execute("SELECT user_id FROM users WHERE auto_news = 1 AND package = 'pro'")
    users = [row[0] for row in c.fetchall()]
    conn.close()
    return users

# === Auto News Alert ===
async def send_auto_news_alerts(context: ContextTypes.DEFAULT_TYPE):
    logger.info("🔁 Running auto news alert...")
    all_tweets = get_all_recent_tweets()
    today = datetime.date.today().isoformat()
    if not all_tweets:
        logger.info("No new tweets found.")
        return

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS sent_news (tweet_id TEXT PRIMARY KEY, tweet TEXT, date_sent TEXT)")
    c.execute("SELECT tweet_id FROM sent_news WHERE date_sent = %s", (today,))
    already_sent_ids = set(row[0] for row in c.fetchall())

    new_tweets = [(tweet_id, text) for tweet_id, text in all_tweets if tweet_id not in already_sent_ids]
    if not new_tweets:
        conn.close()
        logger.info("No fresh tweets to send.")
        return

    for tweet_id, text in new_tweets:
        c.execute("INSERT INTO sent_news (tweet_id, tweet, date_sent) VALUES (%s, %s, %s) ON CONFLICT (tweet_id) DO NOTHING", (tweet_id, text, today))
    conn.commit()
    conn.close()

    msg = "📰 *New Crypto News:*\n\n"
    for _, text in new_tweets:
        msg += f"🔹 {text}\n\n"
    escaped_msg = escape_markdown(msg, version=2)

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE auto_news = 1 AND package = 'pro'")
    users = [row[0] for row in c.fetchall()]
    conn.close()

    for user_id in users:
        try:
            await context.bot.send_message(chat_id=user_id, text=escaped_msg, parse_mode="MarkdownV2")
            logger.info(f"✅ News sent to user {user_id}")
        except Exception as e:
            logger.error(f"❌ Failed to send news to {user_id}: {e}")

# === Scheduler ===
def register_news_scheduler(application):
    logger.info("🕒 Registering news scheduler...")
    init_news_db()
    scheduler = AsyncIOScheduler()

    # Use a function to run the async task with the application context
    async def run_send_auto_news_alerts(app):
        await send_auto_news_alerts(app)

    scheduler.add_job(lambda: asyncio.run(run_send_auto_news_alerts(application)), "interval", hours=1)
    scheduler.add_job(clear_old_news, "cron", hour=0)
    scheduler.add_job(lambda: asyncio.run(send_weekly_promo(application)), "cron", day_of_week='sun', hour=10)
    scheduler.start()
    logger.info("✅ News scheduler started.")
    # Initial run
    asyncio.run(run_send_auto_news_alerts(application))
