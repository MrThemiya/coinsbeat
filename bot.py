import os
import logging
import psycopg2
import requests
import asyncio
from telegram import BotCommand
from datetime import datetime, time
from autoalert import auto_price_watcher
from telegram import Update
from pay import register_payment_handlers, check_expirations
from UI import menu, button_handler, pcu_info_callback
from referral import register_referral_handlers
from fetch_prices import SYMBOLS, DEX_URLS, fetch_prices
from fetch_prices import get_cached_price
from walletui import register_swap_handlers, import_wallet
from UI import receive_wallet_address
from airdrop_alert import register_airdrop_handlers
from news import register_news_scheduler
from limits import can_send_message, increment_message_count, can_add_alert

from telegram.ext import MessageHandler, filters, CommandHandler, ApplicationBuilder, ContextTypes, CallbackQueryHandler

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# PostgreSQL database setup
conn = psycopg2.connect(os.environ["DATABASE_URL"])
c = conn.cursor()
c.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        user_id INTEGER,
        symbol TEXT,
        threshold REAL
    )
""")
conn.commit()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if context.args:
        try:
            referrer_id = int(context.args[0])
        except (ValueError, IndexError):
            referrer_id = None

        if referrer_id and referrer_id != user_id:
            conn = psycopg2.connect(os.environ["DATABASE_URL"])
            c = conn.cursor()
            try:
                # Check if new user
                c.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
                already_exists = c.fetchone()

                if not already_exists:
                    # Add new user with referral
                    c.execute("INSERT INTO users (user_id, messages, referrer_id) VALUES (%s, %s, %s)",
                              (user_id, 0, referrer_id))
                    c.execute("""
                        INSERT INTO referrals (referrer_id, referred_id)
                        VALUES (%s, %s)
                        ON CONFLICT (referred_id) DO NOTHING
                    """, (referrer_id, user_id))
                    BONUS_MESSAGES = 250
                    c.execute("UPDATE users SET messages = messages + %s WHERE user_id = %s",
                              (BONUS_MESSAGES, referrer_id))
                    conn.commit()
                    await update.message.reply_text(f"Bot started! Referred by {referrer_id}. You and referrer got {BONUS_MESSAGES} bonus messages!")
                else:
                    await update.message.reply_text("Bot started! You’re already registered.")
            except psycopg2.Error as e:
                print(f"Database error: {e}")
                await update.message.reply_text("Error processing referral. Try again later.")
            finally:
                conn.close()
        else:
            await update.message.reply_text("Bot started! Invalid or self-referral detected.")
    else:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        c = conn.cursor()
        try:
            c.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            already_exists = c.fetchone()
            if not already_exists:
                c.execute("INSERT INTO users (user_id, messages, referrer_id) VALUES (%s, %s, %s)",
                          (user_id, 0, None))
                conn.commit()
                await update.message.reply_text("Bot started! Welcome as a new user!")
            else:
                await update.message.reply_text("Bot started!")
        except psycopg2.Error as e:
            print(f"Database error: {e}")
            await update.message.reply_text("Error registering user. Try again later.")
        finally:
            conn.close()

    # Menu එක පෙන්නන්න
    await menu(update, context)

ADMIN_ID = 1400222917  # replace with your Telegram ID

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(" Unauthorized.")
        return

    message = " ".join(context.args)
    if not message:
        await update.message.reply_text(" Usage: /broadcast Your message here")
        return

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    user_ids = [row[0] for row in c.fetchall()]
    conn.close()

    sent, failed = 0, 0
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=message)
            sent += 1
        except Exception as e:
            print(f"Failed to send to {uid}: {e}")
            failed += 1

    await update.message.reply_text(f"Broadcast sent to {sent} users.\n Failed: {failed}")

async def set_bot_commands(app):
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("price", "Get current token price"),
        BotCommand("price_alert_menu", "Set price alert"),
        BotCommand("upgrade", "View subscription plans"),
        BotCommand("help", "Help using the bot"),
    ]
    await app.bot.set_my_commands(commands)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not can_send_message(user_id):
        await update.message.reply_text("❌ Monthly message limit reached. Upgrade to Plus or Pro to continue.")
        return
    increment_message_count(user_id)

    if not context.args:
        await update.message.reply_text("Please provide a token symbol. Ex: /price btc")
        return

    symbol = context.args[0].lower()
    if symbol not in SYMBOLS:
        await update.message.reply_text("Unsupported symbol. Try: btc, eth, bnb, pepe, sol")
        return

    try:
        price = get_cached_price(symbol)
        if price is None:
            prices = await fetch_prices()
            price = prices.get(symbol)

        if price is None:
            await update.message.reply_text(f"Price for {symbol.upper()} not found.")
        else:
            await update.message.reply_text(f"{symbol.upper()} price: ${price}")
    except Exception as e:
        logger.error(f"Price error: {e}")
        await update.message.reply_text("Failed to fetch price.")

async def add_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not can_send_message(user_id):
        await update.message.reply_text("❌ Monthly message limit reached. Upgrade to Plus or Pro to continue.")
        return
    increment_message_count(user_id)

    if len(context.args) != 2:
        await update.message.reply_text("Usage: /add <symbol> <price>")
        return

    if not can_add_alert(user_id):
        await update.message.reply_text("⚠️ Alert limit reached. Upgrade your package for more alerts.")
        return

    symbol, threshold = context.args[0].lower(), context.args[1]
    if symbol not in SYMBOLS:
        await update.message.reply_text("Invalid symbol. Try btc, eth, etc.")
        return

    try:
        threshold = float(threshold)
        c.execute("INSERT INTO alerts (user_id, symbol, threshold) VALUES (%s, %s, %s)",
                  (user_id, symbol, threshold))
        conn.commit()
        await update.message.reply_text(f"Alert added for {symbol.upper()} at ${threshold}.")
    except ValueError:
        await update.message.reply_text("Threshold must be a number.")

async def remove_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not can_send_message(user_id):
        await update.message.reply_text("❌ Monthly message limit reached. Upgrade your package to continue.")
        return
    increment_message_count(user_id)

    if not context.args:
        await update.message.reply_text("Usage: /remove <symbol>")
        return

    symbol = context.args[0].lower()
    c.execute("DELETE FROM alerts WHERE user_id=%s AND symbol=%s",
              (user_id, symbol))
    conn.commit()
    await update.message.reply_text(f"Alert removed for {symbol.upper()}.")

async def track_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not can_send_message(user_id):
        await update.message.reply_text("❌ Monthly message limit reached. Upgrade to Plus or Pro to continue.")
        return
    increment_message_count(user_id)

    c.execute("SELECT symbol, threshold FROM alerts WHERE user_id=%s",
              (user_id,))
    rows = c.fetchall()

    if not rows:
        await update.message.reply_text("You have no active alerts.")
        return

    msg = "Your alerts:\n"
    for symbol, threshold in rows:
        msg += f"- {symbol.upper()} @ ${threshold}\n"
    await update.message.reply_text(msg)

async def alert_checker(app):
    while True:
        try:
            c.execute("SELECT DISTINCT symbol FROM alerts")
            symbols = [row[0] for row in c.fetchall()]
            if not symbols:
                await asyncio.sleep(60)
                continue

            prices = await fetch_prices()

            c.execute("SELECT user_id, symbol, threshold FROM alerts")
            alerts = c.fetchall()

            for user_id, symbol, threshold in alerts:
                current_price = prices.get(symbol)
                if current_price is not None:
                    if (threshold >= current_price and threshold <= current_price + 100) or \
                       (threshold <= current_price and threshold >= current_price - 100):
                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        text = (
                            f"⚠️ Alert!\n"
                            f"{symbol.upper()} price reached ${current_price} (set threshold: ${threshold})\n"
                            f"🕒 Time: {now}"
                        )
                        await app.bot.send_message(chat_id=user_id, text=text)
                        c.execute("DELETE FROM alerts WHERE user_id=%s AND symbol=%s AND threshold=%s",
                                  (user_id, symbol, threshold))
                        conn.commit()

        except Exception as e:
            logger.error(f"Alert checker error: {e}")

        await asyncio.sleep(60)

async def on_startup(app):
    app.create_task(alert_checker(app))
    app.create_task(auto_price_watcher(app))
    await set_bot_commands(app)

async def handle_user_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_import_key'):
        context.user_data['awaiting_import_key'] = False
        context.args = [update.message.text.strip()]
        await import_wallet(update, context)
    else:
        await receive_wallet_address(update, context)

async def main():
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(on_startup)
        .build()
    )

    register_payment_handlers(application)
    register_referral_handlers(application)
    register_swap_handlers(application)
    register_news_scheduler(application)
    register_airdrop_handlers(application)

    application.add_handler(CommandHandler("import_wallet", import_wallet))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CallbackQueryHandler(pcu_info_callback, pattern="^pcu_info$"))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(CommandHandler("wallet", receive_wallet_address))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_text))
    application.add_handler(CommandHandler("broadcast", broadcast))

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("add", add_alert))
    application.add_handler(CommandHandler("remove", remove_alert))
    application.add_handler(CommandHandler("track", track_alerts))
    daily_time = time(hour=0, minute=0)
    print(f"Scheduling check_expirations at {daily_time}")
    application.job_queue.run_daily(check_expirations, time=daily_time)
    application.add_error_handler(lambda update, context: logger.error(f"Error: {context.error}"))

    print("Bot is running...")
    await application.run_polling()

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    print(f"datetime module: {datetime}, time class: {time}")
    asyncio.run(main())
    
