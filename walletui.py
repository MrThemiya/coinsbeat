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
from autosnip import subscribe_to_snipe

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def create_wallet(update_or_callback_query, context):
    """Generate and save a new Solana wallet."""
    try:
        user_id = update_or_callback_query.effective_user.id
    except AttributeError:
        user_id = update_or_callback_query.from_user.id

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    try:
        c.execute("""
            CREATE TABLE IF NOT EXISTS swap_users (
                user_id INTEGER PRIMARY KEY,
                encrypted_privkey BYTEA,
                wallet_address TEXT
            )
        """)
        c.execute("SELECT wallet_address FROM swap_users WHERE user_id = %s", (user_id,))
        if c.fetchone() and c.fetchone()[0]:
            await update_or_callback_query.message.reply_text(
                "⚠️ You already have a wallet. Please delete it first before creating a new one."
            )
            return
    finally:
        conn.close()

    keypair = generate_wallet()
    privkey_bytes = bytes(keypair)
    encrypted = encrypt_private_key(privkey_bytes, AES_PASSWORD)
    save_encrypted_key(user_id, encrypted)

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO swap_users (user_id, encrypted_privkey, wallet_address) VALUES (%s, %s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET encrypted_privkey = %s, wallet_address = %s",
            (user_id, encrypted, str(keypair.pubkey()), encrypted, str(keypair.pubkey()))
        )
        conn.commit()
    finally:
        conn.close()

    await update_or_callback_query.message.reply_text(
        f"🎉 Wallet created!\n\n*Public Address:*\n`{keypair.pubkey()}`",
        parse_mode="Markdown"
    )

async def import_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Import an existing Solana wallet from a Base58-encoded private key."""
    user_id = update.effective_user.id

    if len(context.args) != 1:
        await update.message.reply_text("Usage: /import_wallet <base58_private_key>")
        return

    try:
        privkey_bytes = decode_base58_private_key(context.args[0])
        if len(privkey_bytes) not in [32, 64]:
            raise ValueError(f"Decoded private key has unexpected length: {len(privkey_bytes)} bytes. Expected 32 or 64.")
    except Exception as e:
        logger.error(f"Error decoding private key for user {user_id}: {e}")
        await update.message.reply_text("❌ Invalid private key. Must be a valid Base58-encoded 32-byte secret key or 64-byte keypair.")
        return

    try:
        encrypted = encrypt_private_key(privkey_bytes, AES_PASSWORD)
        save_encrypted_key(user_id, encrypted)
        keypair = load_keypair(privkey_bytes)

        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        c = conn.cursor()
        try:
            c.execute(
                "INSERT INTO swap_users (user_id, encrypted_privkey, wallet_address) VALUES (%s, %s, %s) "
                "ON CONFLICT (user_id) DO UPDATE SET encrypted_privkey = %s, wallet_address = %s",
                (user_id, encrypted, str(keypair.pubkey()), encrypted, str(keypair.pubkey()))
            )
            conn.commit()
        finally:
            conn.close()

        await update.message.reply_text(
            f"✅ Wallet imported!\n\n*Public Address:*\n`{keypair.pubkey()}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error importing wallet for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Failed to import wallet: {e}")

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Swap SOL for a specified token."""
    user_id = update.effective_user.id

    if len(context.args) != 2:
        await update.message.reply_text("Usage: /buy <token_mint_address> <amount_in_SOL>")
        return

    try:
        token_mint, amount_sol = context.args[0], float(context.args[1])
        if amount_sol <= 0:
            raise ValueError("Amount must be a positive number.")
    except ValueError as e:
        await update.message.reply_text(f"❌ Invalid amount: {e}")
        return

    try:
        logger.info(f"perform_swap args: user_id={user_id}, input_mint={SYSTEM_SOL}, output_mint={token_mint}, amount={amount_sol}")
        tx_sig = await perform_swap(user_id, SYSTEM_SOL, token_mint, amount_sol, AES_PASSWORD)
        await update.message.reply_text(f"✅ Buy transaction sent!\n🔗 https://solscan.io/tx/{tx_sig}")
    except Exception as e:
        logger.error(f"Buy failed for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Transaction failed: {e}")

async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Swap a specified token for SOL."""
    user_id = update.effective_user.id

    if len(context.args) != 2:
        await update.message.reply_text("Usage: /sell <token_mint_address> <amount_in_tokens>")
        return

    try:
        token_mint, amount_tokens = context.args[0], float(context.args[1])
        if amount_tokens <= 0:
            raise ValueError("Amount must be a positive number.")
    except ValueError as e:
        await update.message.reply_text(f"❌ Invalid amount: {e}")
        return

    try:
        logger.info(f"perform_swap args: user_id={user_id}, input_mint={token_mint}, output_mint={SYSTEM_SOL}, amount={amount_tokens}")
        tx_sig = await perform_swap(user_id, token_mint, SYSTEM_SOL, amount_tokens, AES_PASSWORD)
        await update.message.reply_text(f"✅ Sell transaction sent!\n🔗 https://solscan.io/tx/{tx_sig}")
    except Exception as e:
        logger.error(f"Sell failed for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Transaction failed: {e}")

async def balance(update, context):
    """Display SOL and SPL token balances for the user's wallet."""
    user_id = update.effective_user.id
    encrypted = get_encrypted_key(user_id)

    if not encrypted:
        logger.warning(f"No wallet for user {user_id}")
        await update.effective_message.reply_text("⚠️ You must /create_wallet or /import_wallet first.")
        return

    try:
        privkey_bytes = decrypt_private_key(encrypted, AES_PASSWORD)
        keypair = load_keypair(privkey_bytes)
        pubkey_obj = keypair.pubkey()

        async with AsyncClient("https://api.mainnet-beta.solana.com") as client:
            sol_balance_resp = await client.get_balance(pubkey_obj)
            sol = sol_balance_resp.value / 1_000_000_000

            opts = TokenAccountOpts(program_id=Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"))
            token_accounts_resp = await client.get_token_accounts_by_owner_json_parsed(owner=pubkey_obj, opts=opts)

            token_lines = [
                f"• `{TOKEN_MINTS.get(acc.account.data.parsed['info']['mint'], acc.account.data.parsed['info']['mint'][:6] + '...')}`: {int(acc.account.data.parsed['info']['tokenAmount']['amount']) / (10 ** int(acc.account.data.parsed['info']['tokenAmount']['decimals'])):.4f}"
                for acc in token_accounts_resp.value
                if isinstance(acc.account.data.parsed, dict) and int(acc.account.data.parsed['info']['tokenAmount']['amount']) > 0
            ]
            token_text = "\n".join(token_lines) if token_lines else "_No SPL tokens found_"

            await update.effective_message.reply_text(
                f"📍 *Wallet Address:*\n`{str(pubkey_obj)}`\n\n"
                f"💰 *SOL:* {sol:.4f} SOL\n\n"
                f"📦 *Tokens:*\n{token_text}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📤 Withdraw", callback_data="withdraw_start")]])
            )
    except Exception as e:
        logger.error(f"Balance fetch failed for user {user_id}: {e}", exc_info=True)
        await update.effective_message.reply_text(f"❌ Failed to fetch balance: {e}")

async def snipe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Subscribe to token sniping."""
    user_id = update.effective_user.id
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /snipe <token_mint> <amount_in_sol>")
        return

    try:
        mint, amount = context.args[0], float(context.args[1])
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

def register_swap_handlers(application):
    """Register all command handlers with the Telegram application."""
    application.add_handler(CommandHandler("create_wallet", create_wallet))
    application.add_handler(CommandHandler("import_wallet", import_wallet))
    application.add_handler(CommandHandler("buy", buy))
    application.add_handler(CommandHandler("sell", sell))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("snipe", snipe_command))