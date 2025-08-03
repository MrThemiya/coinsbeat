from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import psycopg2
import asyncio
import logging
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
from solders.transaction import Transaction, VersionedTransaction
from solders.system_program import transfer, TransferParams
from solders.keypair import Keypair
from news import get_latest_news
from walletui import create_wallet
from wallet import (
    decode_base58_private_key,
    encrypt_private_key,
    save_encrypted_key,
    load_keypair,
    AES_PASSWORD,
    get_encrypted_key,
    decrypt_private_key
)
from limits import check_access, can_send_message, increment_message_count, can_add_alert
from tokens import SYMBOL_TO_MINT
import os


# --- Wallet command handler ---
async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Please send me your Solana wallet address."
    )
    return


# --- Handle user-sent wallet address ---

async def receive_wallet_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import logging
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    text = update.message.text.strip()
    user_id = update.effective_user.id

    # Enforce monthly message limit
    if not can_send_message(user_id):
        await update.message.reply_text(
            "🚫 You have reached your monthly message limit. Please upgrade your package."
        )
        return
    increment_message_count(user_id)

    WITHDRAW_FEE = 0.00  # 0.003 SOL fee
    MIN_WITHDRAW_AMOUNT = 0.01  # Minimum 0.01 SOL withdraw allowed
    SYSTEM_SOL = "So11111111111111111111111111111111111111112"  # SOL token mint address

    # --- Handle withdraw flow: waiting for withdraw address ---
    if context.user_data.get("awaiting_withdraw_address"):
        context.user_data["withdraw_address"] = text
        context.user_data["awaiting_withdraw_address"] = False
        context.user_data["awaiting_withdraw_token_amount"] = True
        await update.message.reply_text(
            "💸 Now please provide the Token Mint address and Amount to proceed with the withdrawal:\n\nExample:\n`So11111111111111111111111111111111111111112 0.2`",
            parse_mode="Markdown"
        )
        return

    # --- Handle withdraw flow: waiting for token mint + amount ---
    if context.user_data.get("awaiting_withdraw_token_amount"):
        try:
            mint, amount_str = text.split()
            amount = float(amount_str)
            if amount <= 0:
                raise ValueError("Amount must be positive.")
        except ValueError as e:
            await update.message.reply_text(
                f"❌ Invalid format or amount: {e or 'Use format: `So11111111111111111111111111111111111111112 0.2`'}" ,
                parse_mode="Markdown"
            )
            context.user_data["awaiting_withdraw_token_amount"] = False
            return

        # Check minimum withdraw amount
        if amount < MIN_WITHDRAW_AMOUNT:
            await update.message.reply_text(f"❌ Minimum withdraw amount is {MIN_WITHDRAW_AMOUNT} SOL.")
            context.user_data["awaiting_withdraw_token_amount"] = False
            return

        # Check amount greater than fee
        if amount <= WITHDRAW_FEE:
            await update.message.reply_text(f"❌ Withdraw amount must exceed the fee ({WITHDRAW_FEE} SOL).")
            context.user_data["awaiting_withdraw_token_amount"] = False
            return

        # Only allow SOL withdraw
        if mint != SYSTEM_SOL:
            await update.message.reply_text("❌ Only SOL withdrawals are allowed at this stage.")
            context.user_data["awaiting_withdraw_token_amount"] = False
            return

        # Fetch current balance to validate
        encrypted = get_encrypted_key(user_id)
        if not encrypted:
            await update.message.reply_text("⚠️ Wallet not found. Use /create_wallet or /import_wallet.")
            context.user_data["awaiting_withdraw_token_amount"] = False
            return

        privkey_bytes = decrypt_private_key(encrypted, AES_PASSWORD)
        keypair = load_keypair(privkey_bytes)
        pubkey_obj = keypair.pubkey()

        async with AsyncClient("https://api.mainnet-beta.solana.com") as client:
            sol_balance_resp = await client.get_balance(pubkey_obj)
            sol_lamports = sol_balance_resp.value
            sol_balance = sol_lamports / 1_000_000_000
            total_required = amount + WITHDRAW_FEE

            if sol_balance < total_required:
                await update.message.reply_text(
                    f"❌ Insufficient balance. You have {sol_balance:.4f} SOL, but need {total_required:.4f} SOL (including {WITHDRAW_FEE} SOL fee)."
                )
                context.user_data["awaiting_withdraw_token_amount"] = False
                return

        # Proceed with withdrawal
        net_amount = amount - WITHDRAW_FEE
        net_amount_lamports = int(net_amount * 1_000_000_000)

        async def perform_withdrawal(source_keypair: Keypair, dest_address: str, amount_lamports: int):
            async with AsyncClient("https://api.mainnet-beta.solana.com") as client:
                from solders.instruction import Instruction
                from solders.message import Message
                from solders.transaction import Transaction
                from solders.system_program import transfer, TransferParams

                dest_pubkey = Pubkey.from_string(dest_address)
                # Create transfer instruction
                transfer_ix = transfer(
                    TransferParams(
                        from_pubkey=source_keypair.pubkey(),
                        to_pubkey=dest_pubkey,
                        lamports=amount_lamports
                    )
                )
                # Get recent blockhash
                recent_blockhash = await client.get_latest_blockhash()
                await asyncio.sleep(10)
                # Create message with instructions and payer
                message = Message([transfer_ix], payer=source_keypair.pubkey())
                # Create and sign transaction with keypairs, message, and blockhash
                transaction = Transaction([source_keypair], message, recent_blockhash.value.blockhash)
                # Send transaction
                tx_sig = await client.send_transaction(transaction)
                await asyncio.sleep(15)
                await client.confirm_transaction(tx_sig.value)
    
                return str(tx_sig.value)

        try:
            tx_sig = await perform_withdrawal(keypair, context.user_data["withdraw_address"], net_amount_lamports)
            await update.message.reply_text(
                f"✅ Withdrawal successful! (Fee: {WITHDRAW_FEE} SOL)\n🔗 https://solscan.io/tx/{tx_sig}",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Withdrawal failed: {str(e)}", exc_info=True)
            await update.message.reply_text(f"❌ Withdrawal failed: {str(e)}")
        finally:
            context.user_data["awaiting_withdraw_token_amount"] = False

        return
    # --- Handle auto snipe amount input ---
    if context.user_data.get('awaiting_auto_snipe_amount'):
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError
            from autosnip import subscribe_user_to_all_new_tokens

            # Access control: only pro users allowed for auto snipe
            if not check_access("auto_snipe", user_id):
                await update.message.reply_text(
                    "🚫 Auto Snipe is a Pro feature only. Please upgrade."
                )
                context.user_data['awaiting_auto_snipe_amount'] = False
                return

            subscribe_user_to_all_new_tokens(user_id, amount)
            context.user_data['awaiting_auto_snipe_amount'] = False
            await update.message.reply_text(
                f"✅ Auto Snipe enabled with `{amount} SOL`!",
                parse_mode="Markdown"
            )
        except:
            await update.message.reply_text("❌ Invalid amount. Please enter a valid number (e.g. `0.2`).")
        return

    # --- Handle UI-based Wallet Import (Base58 Private Key) ---
    if context.user_data.get('awaiting_import_key'):
        try:
            privkey_bytes = decode_base58_private_key(text)
            if len(privkey_bytes) != 64:
                raise ValueError
        except:
            await update.message.reply_text("❌ Invalid private key. Must be Base58-encoded 64-byte key.")
            return

        # Encrypt & Save
        encrypted = encrypt_private_key(privkey_bytes, AES_PASSWORD)
        save_encrypted_key(user_id, encrypted)
        keypair = load_keypair(privkey_bytes)
        pubkey = str(keypair.pubkey())

        # Save public key to DB
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        c = conn.cursor()
        c.execute("INSERT INTO users(user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING", (user_id,))
        c.execute("UPDATE users SET wallet_address=%s WHERE user_id=%s", (pubkey, user_id))
        conn.commit()
        conn.close()

        context.user_data['awaiting_import_key'] = False

        await update.message.reply_text(
            f"✅ Wallet imported successfully!\n\n*Public Address:*\n`{pubkey}`",
            parse_mode="Markdown"
        )
        await update.message.reply_text("⬇️ Back to Menu:", reply_markup=main_menu_keyboard())
        return

    # --- Handle standard wallet address saving ---
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    c.execute("INSERT INTO users(user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING", (user_id,))
    c.execute("UPDATE users SET wallet_address=%s WHERE user_id=%s", (text, user_id))
    conn.commit()
    conn.close()


    await update.message.reply_text(
        f"✅ Your wallet address `{text}` has been saved.",
        parse_mode="Markdown"
    )

    # --- Trigger upgrade flow if needed ---
    if context.user_data.get('awaiting_wallet_for_upgrade'):
        context.user_data['awaiting_wallet_for_upgrade'] = False
        from pay import start_upgrade
        await start_upgrade(update, context)
        return

    # --- Existing flow below ---

    # --- Handle auto snipe amount input ---
    if context.user_data.get('awaiting_auto_snipe_amount'):
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError
            from autosnip import subscribe_user_to_all_new_tokens

            # Access control: only pro users allowed for auto snipe
            if not check_access("auto_snipe", user_id):
                await update.message.reply_text(
                    "🚫 Auto Snipe is a Pro feature only. Please upgrade."
                )
                context.user_data['awaiting_auto_snipe_amount'] = False
                return

            subscribe_user_to_all_new_tokens(user_id, amount)
            context.user_data['awaiting_auto_snipe_amount'] = False
            await update.message.reply_text(
                f"✅ Auto Snipe enabled with `{amount} SOL`!",
                parse_mode="Markdown"
            )
        except:
            await update.message.reply_text("❌ Invalid amount. Please enter a valid number (e.g. `0.2`).")
        return

    # --- Handle UI-based Wallet Import (Base58 Private Key) ---
    if context.user_data.get('awaiting_import_key'):
        try:
            privkey_bytes = decode_base58_private_key(text)
            if len(privkey_bytes) != 64:
                raise ValueError
        except:
            await update.message.reply_text("❌ Invalid private key. Must be Base58-encoded 64-byte key.")
            return

        # Encrypt & Save
        encrypted = encrypt_private_key(privkey_bytes, AES_PASSWORD)
        save_encrypted_key(user_id, encrypted)
        keypair = load_keypair(privkey_bytes)
        pubkey = str(keypair.pubkey())

        # Save public key to DB
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        c = conn.cursor()
        c.execute("INSERT INTO users(user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING", (user_id,))
        c.execute("UPDATE users SET wallet_address=%s WHERE user_id=%s", (pubkey, user_id))
        conn.commit()
        conn.close()

        context.user_data['awaiting_import_key'] = False

        await update.message.reply_text(
            f"✅ Wallet imported successfully!\n\n*Public Address:*\n`{pubkey}`",
            parse_mode="Markdown"
        )
        await update.message.reply_text("⬇️ Back to Menu:", reply_markup=main_menu_keyboard())
        return

    # --- Handle standard wallet address saving ---
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    c.execute("INSERT INTO users(user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING", (user_id,))
    c.execute("UPDATE users SET wallet_address=%s WHERE user_id=%s", (text, user_id))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ Your wallet address `{text}` has been saved.",
        parse_mode="Markdown"
    )

    # --- Trigger upgrade flow if needed ---
    if context.user_data.get('awaiting_wallet_for_upgrade'):
        context.user_data['awaiting_wallet_for_upgrade'] = False
        from pay import start_upgrade
        await start_upgrade(update, context)
        return


# --- Main menu buttons ---
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🪙 Get Token Price", callback_data='price')],

        [InlineKeyboardButton("📈 Price Alerts", callback_data='price_alert_menu'),
         InlineKeyboardButton("🚀 Airdrop Alerts", callback_data='airdrop_alerts')],

        [InlineKeyboardButton("📰 News", callback_data='news'),
         InlineKeyboardButton("📡 Signals", url="https://t.me/Classic_Coincodecap")],

        [InlineKeyboardButton("💳 Wallet", callback_data='wallet_menu'),
         InlineKeyboardButton("💎 Package Info", callback_data='pcu_info')],

        [InlineKeyboardButton("⭐️ Upgrade", callback_data='upgrade'),
         InlineKeyboardButton("🎁 Referral", callback_data='referral'),
         InlineKeyboardButton("❓ Help", callback_data='help')],

        [InlineKeyboardButton("⚡ BUY & SELL NOW!", callback_data='buy_sell')],
    ]
    return InlineKeyboardMarkup(keyboard)


# --- Show main menu ---
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text( 
            "⭐️ Welcome to Coinsbeat, the one-stop solution for all your trading needs!\n\n"
            "🪙 Coin price: Check real-time Coin price\n"
            "📈 Set alert: Set Price alert & auto price change alert\n"
            "📰 News: Auto Breaking news alert\n"
            "🎁 Airdrop: Airdrop alerts\n"
            "💳 Wallets: Import or generate wallets.\n"
            "⭐️ Upgrade: No private key required to upgrade\n"
            "🔋 250 msg per month.Ref friends or Upgrade to get extra\n\n"
            "⚡️ Looking for a quick buy or sell? Simply paste the token CA and you're ready to go!",
            reply_markup=main_menu_keyboard()
        )
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "⭐️ Welcome to Coinsbeat, the one-stop solution for all your trading needs!\n\n"
            "🪙 Coin price: Check real-time Coin price\n"
            "📈 Set alert: Set Price alert & auto price change alert\n"
            "📰 News: Auto Breaking news alert\n"
            "🎁 Airdrop: Airdrop alerts\n"
            "💳 Wallets: Import or generate wallets.\n"
            "⭐️ Upgrade: No private key required to upgrade\n"
            "🔋 500 msg per month.Ref friends or Upgrade to get extra\n\n"
            "⚡️ Looking for a quick buy or sell? Simply paste the token CA and you're ready to go!",
            reply_markup=main_menu_keyboard()
        )


def wallet_submenu_keyboard(has_wallet: bool):
    if not has_wallet:
        keyboard = [
            [InlineKeyboardButton("🧠 Create Wallet", callback_data='create_wallet')],
            [InlineKeyboardButton("📥 Import Wallet", callback_data='import_wallet')],
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='back_to_menu')]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("💰 Balance", callback_data='balance')],
            [InlineKeyboardButton("🗑️ Delete Wallet", callback_data='delete_wallet')],
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='back_to_menu')]
        ]
    return InlineKeyboardMarkup(keyboard)


def price_alert_submenu():
    keyboard = [
        [InlineKeyboardButton("📈 Set Alert", callback_data='set_alert')],
        [InlineKeyboardButton("❌ Remove Alert", callback_data='remove_alert')],
        [InlineKeyboardButton("🔔 Track My Alerts", callback_data='track_alerts')],
        [InlineKeyboardButton("⬅️ Back to Menu", callback_data='back_to_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)


async def show_token_mint_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []

    for symbol, mint in SYMBOL_TO_MINT.items():
        keyboard.append([InlineKeyboardButton(f"{symbol}", callback_data=f"mint_{mint}")])

    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")])

    await update.callback_query.edit_message_text(
        "🪙 *Select a token to get its Mint Address:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )



async def pcu_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Acknowledge the callback query
    

    # Package information
    pcu_info = (
        "📦 *Free Plan*\n"
        "• Slow response\n"
        "• 250 messages limit\n"
        "• Price checker\n"
        "• 1 price alert limit\n"
        "• Free signals\n"
        "• Manual news\n\n"
        "💠 *Plus Plan*\n"
        "• Speed response\n"
        "• 1000 messages limit\n"
        "• Price checker\n"
        "• 5 price alert limit\n"
        "• Free signals\n"
        "• Manual news\n"
        "• Create / Import wallet\n"
        "• Swap Token without FEE \n"
        "• No withdrow fee\n\n"
        "🚀 *Pro Plan*\n"
        "• Speed response\n"
        "• No messages limit\n"
        "• Price checker\n"
        "• 20 price alert limit\n"
        "• Free signals\n"
        "• Real-time Auto News Alerts\n"
        "• Create / Import wallet\n"
        "• Speed Swap without fee\n"
        "• No withdrow fee\n"
        "• Airdrop Alert"
    )

    await query.edit_message_text(
        text=pcu_info,
        parse_mode="Markdown"
        
    )

# --- Handle button presses ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    print(f"Received callback data: {data}")

    # Enforce monthly message limit on button press
    if not can_send_message(user_id):
        await context.bot.send_message(
            chat_id=user_id,
            text="🚫 You have reached your monthly message limit. Please upgrade your package."
        )
        return
    increment_message_count(user_id)

    if data == 'create_wallet':
        await create_wallet(update.callback_query, context)
        return

    message = ""

    if data == 'price':
        message = "Send `/price <symbol>` command.\nExample: `/price btc`"

    elif data == 'set_alert':
        # Alert limit check
        if not can_add_alert(user_id):
            await context.bot.send_message(
                chat_id=user_id,
                text="🚫 You have reached your alert limit for your subscription package."
            )
            return
        await context.bot.send_message(
        chat_id=user_id,
        text="Send `/add <symbol> <price>` command.\nExample: `/add btc 110000`")
        return

    elif data == 'remove_alert':
        await context.bot.send_message(
         chat_id=user_id,
         text="Send `/remove <symbol>` command.\nExample: `/remove btc`"
        )
        return

    elif data == 'track_alerts':
        await context.bot.send_message(
         chat_id=user_id,
         text="Send `/track` command to see your active alerts."
        )
        return

    elif data == 'wallet':
        message = "Please send me your wallet address (BEP-20, ERC-20, or Solana)."
        return

    elif data == 'help':
        await query.edit_message_text(
           "🤖 *Bot Help\n\n"
            "• back to menu /start\n"
            "• Set price alerts with /add\n"
            "• Check wallet balance with /balance\n"
            "• Contact Support [info@coinsbeat.com]\n"
            "• Need full guide? [coinsbeat.com](https://coinsbeat.com/telegram-crypto-trading-bot/)"
        )
        return
    
    elif data == 'news':
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📰 Manual News", callback_data='manual_news')],
            [InlineKeyboardButton("🔔 Auto News Settings", callback_data='auto_news_settings')],
            [InlineKeyboardButton("⬅️ Back to Menu", callback_data='back_to_menu')]
        ])
        await context.bot.send_message(
        chat_id=user_id,
        text="📰 *News Options:*",
        reply_markup=keyboard,
        parse_mode="Markdown"
        )
        return
    
    elif data == 'manual_news':
        from news import get_latest_news
        text = get_latest_news()
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode="Markdown"
        )
        return
    
    elif data == 'auto_news_settings':
    # Access control: Pro users only
        user_id = update.effective_user.id  # Fetch correct user_id from callback query
        if not check_access(user_id, "news"):  # Correct order: user_id first, service second
            await context.bot.send_message(
               chat_id=user_id,
               text="🚫 Auto News is a *Pro* feature only. Please upgrade your package.",
               parse_mode="Markdown"
            )
            return
    # Add further auto news settings logic here if needed
        
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        c = conn.cursor()
        c.execute("SELECT auto_news FROM users WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        status = row[0] if row else 1  # Default enabled
        conn.close()

        if status == 1:
            keyboard = InlineKeyboardMarkup([
               [InlineKeyboardButton("❌ Disable Auto News", callback_data='disable_auto_news')],
               [InlineKeyboardButton("⬅️ Back", callback_data='news')]
            ])
            msg = "🔔 Auto News is currently *Enabled*."
        else:
            keyboard = InlineKeyboardMarkup([
               [InlineKeyboardButton("✅ Enable Auto News", callback_data='enable_auto_news')],
               [InlineKeyboardButton("⬅️ Back", callback_data='news')]
            ])
            msg = "🔕 Auto News is currently *Disabled*."

        await context.bot.send_message(
            chat_id=user_id,
            text=msg,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return
    elif data == 'disable_auto_news':
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        c = conn.cursor()
        c.execute("UPDATE users SET auto_news = 0 WHERE user_id = %s", (user_id,))
        conn.commit()
        conn.close()
        await context.bot.send_message(chat_id=user_id, text="❌ Auto News disabled.")
        return

    elif data == 'enable_auto_news':
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        c = conn.cursor()
        c.execute("UPDATE users SET auto_news = 1 WHERE user_id = %s", (user_id,))
        conn.commit()
        conn.close()
        await context.bot.send_message(chat_id=user_id, text="✅ Auto News enabled.")
        return








    elif data == "mint_list":
        await show_token_mint_buttons(update, context)
        return

    elif data.startswith("mint_"):
         mint = data.replace("mint_", "")
         await context.bot.send_message(
                chat_id=user_id,
                text=f"`{mint}`",
                parse_mode="Markdown"
        )
         return


    elif data == 'upgrade':
        message = "🔐 To upgrade, please send your Solana wallet address."
        context.user_data['awaiting_wallet_for_upgrade'] = True
           

    elif data == 'balance':
        from walletui import balance
        await balance(update, context)
        return

    elif data == 'import_wallet':
        context.user_data['awaiting_import_key'] = True
        await context.bot.send_message(
            chat_id=user_id,
            text="📥 Please send your *Solana phantom wallet* private key to import your wallet.",
            parse_mode="Markdown"
        )
        return

    elif data == 'wallet_menu':
        # Check if user has wallet
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        c = conn.cursor()
        c.execute("SELECT wallet_address FROM swap_users WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        conn.close()

        has_wallet = bool(row and row[0])

        await query.edit_message_text(
            "🔐 *Wallet Menu:*",
            reply_markup=wallet_submenu_keyboard(has_wallet),
            parse_mode="Markdown"
        )
        return

    elif data == 'delete_wallet':
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        c = conn.cursor()
        c.execute("UPDATE swap_users SET wallet_address = NULL WHERE user_id = %s", (user_id,))
        conn.commit()
        conn.close()

        await context.bot.send_message(
            chat_id=user_id,
            text="🗑️ Your wallet has been deleted."
        )
         

        await context.bot.send_message(
            chat_id=user_id,
            text="🔐 *Wallet Menu:*",
            reply_markup=wallet_submenu_keyboard(False),
            parse_mode="Markdown"
        )
        return

    elif data == 'price_alert_menu':
        await query.edit_message_text(
            "📈 *Price Alerts Menu:*",
            reply_markup=price_alert_submenu(),
            parse_mode="Markdown"
        )
        return

    elif data == 'referral':
        from referral import referral
        await referral(update, context)
        return

    elif data == 'news':
        news_text = get_latest_news()
        await context.bot.send_message(
            chat_id=user_id,
            text=news_text or "🚫 No news available right now.",
            parse_mode="Markdown"
        )
        return

    elif data == 'auto_snipe':
        # Access control: only pro users allowed
        if not check_access("auto_snipe", user_id):
            await context.bot.send_message(
                chat_id=user_id,
                text="🚫 Auto Snipe is a Pro feature only. Please upgrade."
            )
            return

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Enable Auto Snipe", callback_data='enable_auto_snipe')],
            [InlineKeyboardButton("🚫 Disable Auto Snipe", callback_data='disable_auto_snipe')],
            [InlineKeyboardButton("⬅️ Back to Menu", callback_data='back_to_menu')]
        ])

        await context.bot.send_message(
            chat_id=user_id,
            text="🎯 *Auto Snipe Options:*\n\nAutomatically snipe all newly listed Raydium tokens.\n\nChoose an option below:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return

    elif data == 'enable_auto_snipe':
        context.user_data['awaiting_auto_snipe_amount'] = True
        await context.bot.send_message(
            chat_id=user_id,
            text="💰 Please enter the amount of SOL to use for auto sniping.\n\n_Example: 0.2_",
            parse_mode="Markdown"
        )
        return

    elif data == 'disable_auto_snipe':
        from autosnip import unsubscribe_user_from_all
        unsubscribe_user_from_all(user_id)
        await context.bot.send_message(
            chat_id=user_id,
            text="🚫 Auto Snipe disabled successfully."
        )
        return

    elif data == "withdraw_start":
        context.user_data["awaiting_withdraw_address"] = True
        await context.bot.send_message(
            chat_id=user_id,
            text="📥 Please provide the receiving wallet address:",
            parse_mode="Markdown"
        )
        return

    elif data == 'airdrop_alerts':
    # Access control: Pro users only
        user_id = update.effective_user.id  # Fetch correct user_id from callback query
        if not check_access(user_id, "airdrop"):  # Correct order: user_id first, service second
            await context.bot.send_message(
                chat_id=user_id,
                text="🚫 Airdrop alerts are a Pro feature only. Please upgrade."
            )
            return

        from airdrop_alert import get_latest_airdrops
        text = get_latest_airdrops()
        from telegram.helpers import escape_markdown
        escaped_text = escape_markdown(text, version=2)
        await context.bot.send_message(
            chat_id=user_id,
            text=escaped_text,
            parse_mode="MarkdownV2"
        )
        return

    elif data == 'buy_sell':
    # Access control: plus and pro users only
        user_id = update.effective_user.id  # Fetch correct user_id from callback query
        if not check_access(user_id, "buy_sell"):  # Correct order: user_id first, service second
            await context.bot.send_message(
                chat_id=user_id,
                text="🚫 Buy & Sell feature is available for Plus and Pro users only. Please upgrade."
            )
            return
    # Add further buy/sell logic here if needed
        # You can trigger your buy/sell UI flow here
        keyboard = InlineKeyboardMarkup([
           [InlineKeyboardButton("🛒 Buy Token", callback_data='start_buy')],
           [InlineKeyboardButton("💰 Sell Token", callback_data='start_sell')],
           [InlineKeyboardButton("📋 Mint Addresses", callback_data='mint_list')],
           [InlineKeyboardButton("⬅️ Back to Menu", callback_data='back_to_menu')]
        ])

        await context.bot.send_message(
        chat_id=user_id,
        text="⚡ *Buy & Sell Menu:*\n\nChoose what you want to do.",
        reply_markup=keyboard,
        parse_mode="Markdown"
        )
        return
    
    elif data == 'start_buy':
        await context.bot.send_message(
          chat_id=user_id,
          text="🛒 Send `/buy <token_mint_address> <amount_in_SOL>`\n\n_Example:_\n`/buy 9n4nbM75f5Ui33ZbPYXn59EwSgE8CGsHtAeTH5YFeJ9E 0.2`",
          parse_mode="Markdown"
       )
        return

    elif data == 'start_sell':
        await context.bot.send_message(
          chat_id=user_id,
          text="💰 Send `/sell <token_mint_address> <amount_in_tokens>`\n\n_Example:_\n`/sell 9n4nbM75f5Ui33ZbPYXn59EwSgE8CGsHtAeTH5YFeJ9E 1000`",
          parse_mode="Markdown"
        )
        return


    elif data == 'back_to_menu':
        await query.edit_message_text(
            "⬇️ Main Menu:",
            reply_markup=main_menu_keyboard()
        )
        return

    # Default fallback: send message if set
    if message:
        await context.bot.send_message(
            chat_id=user_id,
            text=message,
            parse_mode="Markdown"
        )

 
