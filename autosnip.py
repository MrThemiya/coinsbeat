import asyncio
import time
import requests
from threading import Lock
from collections import defaultdict
import logging
import traceback
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from wallet import (
    decrypt_private_key,
    load_keypair,
    get_encrypted_key,
    AES_PASSWORD,
)

from swap import perform_swap, SYSTEM_SOL
from limits import check_access

# Configure dedicated logger
logger = logging.getLogger("autosnip")
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

# --- Manual Snipe Subscriptions ---
snipe_subscriptions = {}  # {user_id: {"mint": str, "amount": float}}
SUBSCRIPTION_LOCK = Lock()  # Lock for snipe_subscriptions access
SNIPE_LOOP_LOCK = Lock()  # Global lock for snipe_loop

# --- Auto Snipe ALL Subscriptions ---
snipe_all_subscribers = {}  # {user_id: amount_in_sol}

# --- User-specific locks ---
SNIP_LOCKS = defaultdict(Lock)

def create_session_with_retries():
    """Create a requests session with retry logic for transient errors."""
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session

def subscribe_to_snipe(user_id: int, mint: str, amount: float):
    """Subscribe a user to snipe a specific token."""
    with SUBSCRIPTION_LOCK:
        snipe_subscriptions[user_id] = {"mint": mint, "amount": amount}
    logger.info(f"User {user_id} subscribed to snipe {mint} for {amount} SOL")

def subscribe_user_to_all_new_tokens(user_id: int, amount: float):
    """Subscribe a user to auto-snipe all new tokens."""
    snipe_all_subscribers[user_id] = amount
    logger.info(f"User {user_id} subscribed to auto-snipe all new tokens for {amount} SOL")

def unsubscribe_user_from_all(user_id: int):
    """Unsubscribe a user from auto-sniping all new tokens."""
    if user_id in snipe_all_subscribers:
        del snipe_all_subscribers[user_id]
        logger.info(f"User {user_id} unsubscribed from auto-sniping all new tokens")

async def snipe_token_for_user(user_id: int, mint_address: str, amount_in_sol: float, context: str = "unknown"):
    """
    Perform a token snipe for a user.
    Returns the transaction signature if successful.
    """
    # Prevent duplicate snipes for this user
    lock = SNIP_LOCKS[user_id]
    logger.debug(f"Attempting to acquire snipe lock for user {user_id}, lock_id: {id(lock)}, context: {context}, stack: {''.join(traceback.format_stack()[-15:])}")
    if not lock.acquire(blocking=False):
        logger.warning(f"Duplicate snipe request ignored for user {user_id}, lock_id: {id(lock)}, context: {context}, stack: {''.join(traceback.format_stack()[-15:])}")
        return None

    try:
        # 🔐 Access check
        if not check_access(user_id, "auto_snipe"):
            logger.error(f"Access denied for user {user_id}: Not a Pro user")
            return None

        # 🔐 Load user's wallet
        encrypted = get_encrypted_key(user_id)
        if not encrypted:
            logger.error(f"User {user_id} has no wallet")
            return None

        try:
            privkey = decrypt_private_key(encrypted, AES_PASSWORD)
            keypair = load_keypair(privkey)
        except Exception as e:
            logger.error(f"Wallet loading failed for user {user_id}: {str(e)}")
            return None

        # 🚀 Perform snipe
        logger.info(f"Sniping {mint_address} for user {user_id} with {amount_in_sol} SOL (context: {context})")
        try:
            tx_sig = await perform_swap(user_id, SYSTEM_SOL, mint_address, amount_in_sol, "buy", AES_PASSWORD, context=context)
            logger.info(f"TX Success for user {user_id}: https://solscan.io/tx/{tx_sig}")
            return tx_sig
        except Exception as e:
            logger.error(f"Snipe failed for user {user_id}: {str(e)}")
            return None

    finally:
        lock.release()
        del SNIP_LOCKS[user_id]

async def snipe_loop():
    """Loop through manual snipe subscriptions."""
    while True:
        with SNIPE_LOOP_LOCK:
            with SUBSCRIPTION_LOCK:
                subscriptions = snipe_subscriptions.copy()  # Snapshot to avoid runtime changes
            for user_id, sub in subscriptions.items():
                await snipe_token_for_user(user_id, sub["mint"], sub["amount"], context="snipe_loop")
        await asyncio.sleep(1)

async def auto_snipe_all():
    """Watch Raydium for new tokens and auto-snipe for subscribers."""
    known_mints = set()
    session = create_session_with_retries()

    while True:
        try:
            response = session.get("https://api.raydium.io/pairs", timeout=10)
            response.raise_for_status()
            pairs = response.json()

            for pair in pairs:
                mint = pair.get("baseMint")
                if mint and mint not in known_mints:
                    known_mints.add(mint)
                    logger.info(f"New token detected: {mint}")

                    # Auto snipe for every Pro subscriber
                    for user_id, amount in list(snipe_all_subscribers.items()):
                        logger.info(f"Auto-sniping {mint} for user {user_id}")
                        await snipe_token_for_user(user_id, mint, amount, context="auto_snipe_all")

        except requests.exceptions.RequestException as e:
            logger.error(f"Error in auto_snipe_all: {str(e)}")

        await asyncio.sleep(10)