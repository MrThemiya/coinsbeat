import psycopg2
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes
import os

DB = "users.db"
BONUS_MESSAGES = 250

def init_referral_db():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    # Users table: add messages and referrer_id columns if missing
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            messages INTEGER DEFAULT 0,
            referrer_id INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            referrer_id INTEGER,
            referred_id INTEGER PRIMARY KEY
        )
    """)
    conn.commit()
    conn.close()

async def handle_referral_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if context.args:
        try:
            referrer_id = int(context.args[0])
        except:
            referrer_id = None

        if referrer_id and referrer_id != user_id:
            conn = psycopg2.connect(os.environ["DATABASE_URL"])
            c = conn.cursor()

            # Check if user already exists
            c.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            already_exists = c.fetchone()

            if not already_exists:
                # Add new user with referrer
                c.execute("INSERT INTO users (user_id, messages, referrer_id) VALUES (%s, %s, %s)",
                          (user_id, 0, referrer_id))
                # Add referral link if not exists
                c.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (%s, %s) ON CONFLICT (referred_id) DO NOTHING",
                          (referrer_id, user_id))
                # Add bonus messages to referrer
                c.execute("UPDATE users SET messages = messages + %s WHERE user_id = %s",
                          (BONUS_MESSAGES, referrer_id))
                conn.commit()
                await update.message.reply_text("✅ You joined via a referral! 🎉")
            conn.close()
        else:
            # Normal start without referral or self referral
            await update.message.reply_text("Welcome to the bot! Use the menu below to get started.")
    else:
        # No referral code, just greet
        await update.message.reply_text("Welcome to the bot! Use the menu below to get started.")

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bot_username = (await context.bot.get_me()).username

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    # Ensure user exists
    c.execute("INSERT INTO users (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING", (user_id,))
    conn.commit()

    # Get referral count
    c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = %s", (user_id,))
    total_referrals = c.fetchone()[0]

    # Get current messages
    c.execute("SELECT messages FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    current_messages = row[0] if row else 0
    conn.close()

    referral_link = f"https://t.me/{bot_username}?start={user_id}"

    await context.bot.send_message(
        chat_id=user_id,
        text=(
            f"🎁 *Referral System*\n\n"
            f"🔗 *Your Invite Link:*\n{referral_link}\n\n"
            f"👥 *Referrals:* {total_referrals}\n"
            f"💬 *Bonus Messages Earned:* {total_referrals * BONUS_MESSAGES}\n"
            f"📦 *Current Message Balance:* {current_messages}"
        ),
        parse_mode="Markdown"
    )

def register_referral_handlers(application):
    init_referral_db()
    application.add_handler(CommandHandler("referral", referral))

