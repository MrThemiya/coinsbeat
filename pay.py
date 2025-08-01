import psycopg2
import datetime
import requests
import time
from decimal import Decimal
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.helpers import escape_markdown
import os

# --- Config ---
  # Replace with your Telegram bot token
BOT_PAYMENT_WALLET_SOLANA = "7BSUBgKUF3Ju735r24BLvmES2gDeZnP6ukPJbno3PkyN"  # Solana wallet
USDT_SOLANA_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
 # 🔁 Replace with your real Helius API key
HELIUS_API_KEY = os.environ.get("HELIUS_API_KEY")
if not HELIUS_API_KEY:
    print("i need HELIUS_API_KEY")
else:
    print("i have HELIUS_API_KEY")

# --- Database setup ---
conn = psycopg2.connect(os.environ["DATABASE_URL"])
c = conn.cursor()
try:
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        region TEXT,
        package TEXT,
        price REAL,
        start_date TEXT,
        duration TEXT,
        wallet_address TEXT,
        paid INTEGER DEFAULT 0
    )
    """)
    conn.commit()
except psycopg2.ProgrammingError as e:
    if "already exists" not in str(e):
        print(f"[ERROR] Database setup failed: {e}")
    conn.rollback()

# --- /upgrade ---
async def start_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🌏 Asia / Africa", callback_data="region_asia")],
        [InlineKeyboardButton("🌍 Other Regions", callback_data="region_other")],
    ]
    if update.message:
        await update.message.reply_text("Please select your geographic region:", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.edit_message_text("Please select your geographic region:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- Region select ---
async def select_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    region = query.data.replace("region_", "")
    context.user_data['region'] = region

    prices = {
        "plus_monthly": 5, "pro_monthly": 15
    } if region == "asia" else {
        "plus_monthly": 10, "pro_monthly": 25,
        "plus_yearly": 100, "pro_yearly": 180
    }
    context.user_data['prices'] = prices

    c.execute("INSERT INTO users (user_id, region) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET region = EXCLUDED.region", (user_id, region))
    conn.commit()

    buttons = [
        [InlineKeyboardButton(f"🟢 Plus Monthly - ${prices['plus_monthly']}", callback_data="package_plus_monthly")],
        [InlineKeyboardButton(f"🔵 Pro Monthly - ${prices['pro_monthly']}", callback_data="package_pro_monthly")],
    ]
    if region != "asia":
        buttons += [
            [InlineKeyboardButton(f"🟢 Plus Yearly - ${prices['plus_yearly']}", callback_data="package_plus_yearly")],
            [InlineKeyboardButton(f"🔵 Pro Yearly - ${prices['pro_yearly']}", callback_data="package_pro_yearly")],
        ]

    await query.edit_message_text("Please select a subscription package:", reply_markup=InlineKeyboardMarkup(buttons))

# --- Package select ---
async def select_package(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    parts = query.data.split("_")  # e.g. ['package', 'plus', 'monthly']
    package, duration = parts[1], parts[2]

    prices = context.user_data.get("prices", {})
    price_key = f"{package}_{duration}"
    price = prices.get(price_key)
    if price is None:
        await query.edit_message_text("Invalid selection. Please try again.")
        return

    # Save selection temporarily
    context.user_data['selected_package'] = package
    context.user_data['selected_duration'] = duration
    context.user_data['selected_price'] = price

    c.execute("SELECT wallet_address FROM users WHERE user_id=%s", (user_id,))
    row = c.fetchone()
    wallet_address = row[0] if row and row[0] else "Not set"

    # Escape wallet address for Markdown
    wallet_address_display = escape_markdown(wallet_address) if wallet_address else "Not set"

    tx_id = f"https://solscan.io/account/{wallet_address_display}#transfers"

    await query.edit_message_text(
        f"You selected: *{package.title()}* ({duration})\n"
        f"💵 Amount to pay: *${price} USDT*\n\n"
        f"🔸 *Pay Here Solana USDT*: `{escape_markdown(BOT_PAYMENT_WALLET_SOLANA)}`\n\n"
        f"Your wallet: `{wallet_address_display}`\n\n"
        f"After payment, send `/i_paid` with the TX ID(Signature) to confirm\n\n"
        f"Click to get TX ID easily: ({tx_id})\n\n"
        "Example, `/i_paid` 2nkcFPTtRbbQA8jBughSDgghy47kjhkh",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )

# --- Check Solana payment ---
def check_solana_payment(from_wallet, to_wallet, amount_usdt, tx_id=None):
    import time
    import requests
    from decimal import Decimal

    USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
    all_transactions = []
    before = None
    while True:
        url = f"https://api.helius.xyz/v0/addresses/{to_wallet}/transactions?api-key={HELIUS_API_KEY}"
        if before:
            url += f"&before={before}"
        try:
            res = requests.get(url, timeout=10)
            print("[DEBUG] Helius Status:", res.status_code)
            if res.status_code != 200:
                print("[Helius API ERROR]", res.status_code, res.text)
                break
            transactions = res.json()
            if not transactions:
                break
            all_transactions.extend(transactions)
            before = transactions[-1].get("signature") if transactions else None
            if len(transactions) < 100:  # Assuming 100 is the default limit
                break
        except Exception as e:
            print("[Helius Error]", e)
            print("URL:", url)
            break

    if tx_id:
        url = f"https://api.helius.xyz/v0/transactions?api-key={HELIUS_API_KEY}"
        payload = {"transactions": [tx_id]}
        try:
            res = requests.post(url, json=payload, timeout=10)
            print("[DEBUG] Helius Transaction API Status:", res.status_code)
            if res.status_code != 200:
                print("[Helius API ERROR]", res.status_code, res.text)
                return False
            all_transactions = res.json()
        except Exception as e:
            print("[Helius Error]", e)
            print("URL:", url)
            return False

    print(f"[DEBUG] Found {len(all_transactions)} transactions")
    for tx in all_transactions:
        if not isinstance(tx, dict):
            print("[DEBUG] Skipping invalid transaction format")
            continue
        if tx.get("type") != "TRANSFER":
            print("[DEBUG] Skipping non-TRANSFER transaction")
            continue

        token_transfers = tx.get("tokenTransfers", [])
        if not token_transfers:
            print("[DEBUG] No tokenTransfers found, checking nativeTransfers...")
            continue

        for token in token_transfers:
            print("[DEBUG] Token Transfer:", token)
            mint = token.get("mint")
            sender = token.get("fromUserAccount", "").lower()
            receiver = token.get("toUserAccount", "").lower()
            amount = Decimal(str(token.get("tokenAmount", "0")))
            timestamp = tx.get("timestamp", 0)

            if timestamp > 1e12:
                timestamp = timestamp / 1000

            if (
                mint == USDT_MINT and
                sender == from_wallet.lower() and
                receiver == to_wallet.lower()
            ):
                print(f"[MATCH] USDT Tx match: {amount} USDT at {timestamp}")
                current_time = time.time()
                if amount >= Decimal(str(amount_usdt)):
                    if current_time - timestamp <= 86400:
                        print("[DEBUG] Payment valid: Amount sufficient and within 24 hours")
                        return True
                    else:
                        print(f"[DEBUG] Payment invalid: Transaction too old (age: {current_time - timestamp} seconds)")
                else:
                    print(f"[DEBUG] Payment invalid: Amount {amount} < {amount_usdt}")

    print("[DEBUG] No valid payment transaction found")
    return False

def test_tx(amount, price, tx_timestamp):
    # timestamp check - if millis, convert to seconds
    if tx_timestamp > 1e12:
        tx_timestamp = tx_timestamp / 1000
    
    now = time.time()
    amount_dec = Decimal(str(amount))
    price_dec = Decimal(str(price))
    
    print(f"Amount: {amount_dec}, Price: {price_dec}, Tx time: {tx_timestamp}, Now: {now}")
    
    if amount_dec >= price_dec and (now - tx_timestamp) <= 86400:
        print("Payment accepted")
        return True
    else:
        print("Payment rejected: Amount too low or tx too old")
        return False

# Example call
test_tx(5.000001, 5, 1690300000000)  # timestamp in millis example

# --- /i_paid ---
async def i_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tx_id = context.args[0] if context.args else None  # Get transaction ID if provided

    c.execute("SELECT wallet_address FROM users WHERE user_id=%s", (user_id,))
    row = c.fetchone()
    if not row or not row[0]:
        await update.message.reply_text("You have not set a wallet. Use /wallet to set it.")
        return

    wallet_address = row[0]
    package = context.user_data.get("selected_package")
    duration = context.user_data.get("selected_duration")
    price = context.user_data.get("selected_price")

    if not all([package, duration, price]):
        await update.message.reply_text("No package info found. Please start with /upgrade.")
        return

    paid = check_solana_payment(wallet_address, BOT_PAYMENT_WALLET_SOLANA, price, tx_id)

    if paid:
        start_date = datetime.datetime.now().strftime("%Y-%m-%d")
        c.execute("""
            UPDATE users SET package=%s, price=%s, start_date=%s, duration=%s, paid=1
            WHERE user_id=%s
        """, (package, price, start_date, duration, user_id))
        conn.commit()
        await update.message.reply_text("✅ Payment confirmed! You are now subscribed.")
    else:
        await update.message.reply_text("❌ Payment not detected. Please check your transaction and try again.")

# --- Register handlers ---
def register_payment_handlers(application):
    application.add_handler(CommandHandler("upgrade", start_upgrade))
    application.add_handler(CallbackQueryHandler(select_region, pattern="^region_"))
    application.add_handler(CallbackQueryHandler(select_package, pattern="^package_"))
    application.add_handler(CommandHandler("i_paid", i_paid))

# --- Check expirations ---
async def check_expirations(context: ContextTypes.DEFAULT_TYPE):
    current_date = datetime.datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT user_id, start_date, duration FROM users WHERE paid = 1")
    for row in c.fetchall():
        user_id, start_date, duration = row
        start = datetime.datetime.strptime(start_date, "%Y-%m-%d")
        end = start + datetime.timedelta(days=int(duration))
        if end.strftime("%Y-%m-%d") == current_date:
            c.execute("UPDATE users SET paid = 0 WHERE user_id = %s", (user_id,))
            conn.commit()
            await context.bot.send_message(chat_id=user_id, text="⚠️ Your subscription has expired!")
