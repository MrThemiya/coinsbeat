from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CommandHandler
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
from solana.rpc.types import TokenAccountOpts
import logging
import psycopg2
import os
from wallet import (
    generate_wallet,
    save_encrypted_key,
    encrypt_private_key,
    get_encrypted_key,
    AES_PASSWORD,
    decode_base58_private_key,
    decrypt_private_key,
    load_keypair
)
from swap import perform_swap, SYSTEM_SOL
from tokens import TOKEN_MINTS
from autosnip import subscribe_to_snipe, subscribe_user_to_all_new_tokens, unsubscribe_user_from_all

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- /create_wallet ---
async def create_wallet(update_or_callback_query, context):
    """
    Handles the /create_wallet command to generate and save a new Solana wallet.
    """
    try:
        user_id = update_or_callback_query.effective_user.id
    except AttributeError:  # Handle cases where it might be a callback query
        user_id = update_or_callback_query.from_user.id

    # Check if user already has a wallet
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, wallet_address TEXT)")
    c.execute("SELECT wallet_address FROM users WHERE user_id=%s", (user_id,))
    row = c.fetchone()
    if row and row[0]:
        await update_or_callback_query.message.reply_text(
            "⚠️ You already have a wallet. Please delete it first before creating a new one."
        )
        conn.close()
        return

    # Create new wallet
    keypair = generate_wallet()
    privkey_bytes = bytes(keypair)
    encrypted = encrypt_private_key(privkey_bytes, AES_PASSWORD)
    save_encrypted_key(user_id, encrypted)

    # Save public address to users table
    c.execute("INSERT INTO users(user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING", (user_id,))
    c.execute("UPDATE users SET wallet_address = %s WHERE user_id = %s", (str(keypair.pubkey()), user_id))
    conn.commit()
    conn.close()

    await update_or_callback_query.message.reply_text(
        f"🎉 Wallet created!\n\n*Public Address:*\n`{keypair.pubkey()}`",
        parse_mode="Markdown"
    )

# --- /import_wallet ---
async def import_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /import_wallet command to import an existing Solana wallet
    from a Base58-encoded private key.
    """
    user_id = update.effective_user.id

    if len(context.args) != 1:
        await update.message.reply_text("Usage: /import_wallet <base58_private_key>")
        return

    try:
        privkey_b58_string = context.args[0]
        privkey_bytes = decode_base58_private_key(privkey_b58_string)
        if len(privkey_bytes) not in [32, 64]:
            raise ValueError(f"Decoded private key has unexpected length: {len(privkey_bytes)} bytes. Expected 32 or 64.")
    except Exception as e:
        logger.error(f"Error decoding or validating private key for user {user_id}: {e}")
        await update.message.reply_text("❌ Invalid private key. Must be a valid Base58-encoded 32-byte secret key or 64-byte keypair.")
        return

    try:
        encrypted = encrypt_private_key(privkey_bytes, AES_PASSWORD)
        save_encrypted_key(user_id, encrypted)
        keypair = load_keypair(privkey_bytes)

        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        c = conn.cursor()
        c.execute("INSERT INTO users(user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING", (user_id,))
        c.execute("UPDATE users SET wallet_address = %s WHERE user_id = %s", (str(keypair.pubkey()), user_id))
        conn.commit()
        conn.close()

        await update.message.reply_text(
            f"✅ Wallet imported!\n\n*Public Address:*\n`{keypair.pubkey()}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error importing wallet for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Failed to import wallet: {e}")

# --- /buy ---
async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /buy command to swap SOL for a specified token.
    Usage: /buy <token_mint_address> <amount_in_SOL>
    """
    user_id = update.effective_user.id

    if len(context.args) != 2:
        await update.message.reply_text("Usage: /buy <token_mint_address> <amount_in_SOL>")
        return

    try:
        token_mint = context.args[0]
        amount_sol = float(context.args[1])
        if amount_sol <= 0:
            raise ValueError("Amount must be a positive number.")
    except ValueError as e:
        await update.message.reply_text(f"❌ Invalid amount: {e}")
        return

    try:
        logger.info(f"AES_PASSWORD type: {type(AES_PASSWORD)}, value: {AES_PASSWORD}")
        logger.info(f"Calling perform_swap with args: user_id={user_id}, input_mint={SYSTEM_SOL}, output_mint={token_mint}, amount={amount_sol}, aes_password={AES_PASSWORD}")
        tx_sig = await perform_swap(user_id, SYSTEM_SOL, token_mint, amount_sol, AES_PASSWORD)
        await update.message.reply_text(
            f"✅ Buy transaction sent!\n🔗 https://solscan.io/tx/{tx_sig}"
        )
    except Exception as e:
        logger.error(f"Buy transaction failed for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Transaction failed: {e}")

# --- /sell ---
async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /sell command to swap a specified token for SOL.
    Usage: /sell <token_mint_address> <amount_in_tokens>
    """
    user_id = update.effective_user.id

    if len(context.args) != 2:
        await update.message.reply_text("Usage: /sell <token_mint_address> <amount_in_tokens>")
        return

    try:
        token_mint = context.args[0]
        amount_tokens = float(context.args[1])
        if amount_tokens <= 0:
            raise ValueError("Amount must be a positive number.")
    except ValueError as e:
        await update.message.reply_text(f"❌ Invalid amount: {e}")
        return

    try:
        logger.info(f"AES_PASSWORD type: {type(AES_PASSWORD)}, value: {AES_PASSWORD}")
        logger.info(f"Calling perform_swap with args: user_id={user_id}, input_mint={token_mint}, output_mint={SYSTEM_SOL}, amount={amount_tokens}, aes_password={AES_PASSWORD}")
        tx_sig = await perform_swap(user_id, token_mint, SYSTEM_SOL, amount_tokens, AES_PASSWORD)
        await update.message.reply_text(
            f"✅ Sell transaction sent!\n🔗 https://solscan.io/tx/{tx_sig}"
        )
    except Exception as e:
        logger.error(f"Sell transaction failed for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Transaction failed: {e}")

# --- /balance ---
async def balance(update, context):
    """
    Handles the /balance command to display SOL and SPL token balances for the user's wallet.
    """
    user_id = update.effective_user.id
    encrypted = get_encrypted_key(user_id)

    if not encrypted:
        logger.warning(f"User {user_id} has no wallet")
        await update.effective_message.reply_text("⚠️ You must /create_wallet or /import_wallet first.")
        return

    try:
        logger.info(f"Decrypting key for user {user_id}")
        privkey_bytes = decrypt_private_key(encrypted, AES_PASSWORD)
        logger.info(f"Private key length: {len(privkey_bytes)} bytes")

        logger.info("Loading keypair")
        keypair = load_keypair(privkey_bytes)
        pubkey_obj = keypair.pubkey()
        logger.info(f"Public key: {str(pubkey_obj)}")

        logger.info("Connecting to Solana RPC")
        async with AsyncClient("https://api.mainnet-beta.solana.com") as client:
            logger.info("Fetching SOL balance")
            sol_balance_resp = await client.get_balance(pubkey_obj)
            logger.info(f"SOL balance response type: {type(sol_balance_resp)}, value: {sol_balance_resp}")
            sol_lamports = sol_balance_resp.value
            sol = sol_lamports / 1_000_000_000

            logger.info("Fetching token accounts")
            opts = TokenAccountOpts(program_id=Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"))
            token_accounts_resp = await client.get_token_accounts_by_owner_json_parsed(owner=pubkey_obj, opts=opts)
            logger.info(f"Token accounts response type: {type(token_accounts_resp)}, value: {token_accounts_resp}")

            token_lines = []
            for acc in token_accounts_resp.value:
                parsed_data = acc.account.data.parsed
                if not isinstance(parsed_data, dict):
                    logger.warning(f"Skipping account, parsed_data is not dict: {type(parsed_data)}")
                    continue

                info = parsed_data.get("info", {})
                mint = info.get("mint")
                token_amount = info.get("tokenAmount", {})
                amount = int(token_amount.get("amount", 0))
                decimals = int(token_amount.get("decimals", 0))
                balance = amount / (10 ** decimals)
                if balance > 0:
                    symbol = TOKEN_MINTS.get(mint, mint[:6] + "...")
                    token_lines.append(f"• `{symbol}`: {balance:.4f}")

            token_text = "\n".join(token_lines) if token_lines else "_No SPL tokens found_"

            logger.info("Sending balance response to user")
            await update.effective_message.reply_text(
                f"📍 *Wallet Address:*\n`{str(pubkey_obj)}`\n\n"
                f"💰 *SOL:* {sol:.4f} SOL\n\n"
                f"📦 *Tokens:*\n{token_text}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📤 Withdraw", callback_data="withdraw_start")]
                ])
            )

    except Exception as e:
        logger.error(f"Failed to fetch balance for user {user_id}: {str(e)}", exc_info=True)
        await update.effective_message.reply_text(f"❌ Failed to fetch balance: {str(e)}")

# --- /snipe ---
async def snipe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /snipe command to subscribe to token sniping.
    Usage: /snipe <token_mint> <amount_in_sol>
    """
    user_id = update.effective_user.id
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /snipe <token_mint> <amount_in_sol>")
        return

    mint = context.args[0]
    try:
        amount = float(context.args[1])
        if amount <= 0:
            raise ValueError("Amount must be a positive number.")
    except ValueError as e:
        await update.message.reply_text(f"❌ Invalid amount: {e}")
        return

    subscribe_to_snipe(user_id, mint, amount)
    await update.message.reply_text(
        f"🎯 Subscribed to snipe token:\nMint: `{mint}`\nAmount: `{amount} SOL`",
        parse_mode="Markdown"
    )

# --- Register All Commands ---
def register_swap_handlers(application):
    """
    Registers all command handlers with the Telegram application builder.
    """
    application.add_handler(CommandHandler("create_wallet", create_wallet))
    application.add_handler(CommandHandler("import_wallet", import_wallet))
    application.add_handler(CommandHandler("buy", buy))
    application.add_handler(CommandHandler("sell", sell))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("snipe", snipe_command))