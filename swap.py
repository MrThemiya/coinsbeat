import base64
import requests
from solders.transaction import Transaction, VersionedTransaction
from solders.message import Message
from solders.signature import Signature
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.types import TokenAccountOpts, TxOpts
from spl.token.instructions import get_associated_token_address, create_associated_token_account
from tenacity import retry, stop_after_attempt, wait_exponential
from requests.exceptions import RequestException
from time import sleep
from solana.rpc.api import Client
from solders.address_lookup_table_account import AddressLookupTableAccount
import logging
from spl.token.async_client import AsyncToken
from wallet import decrypt_private_key, get_encrypted_key, load_keypair
from fee import create_fee_instruction
from limits import check_access
import os

# Set up logging
logger = logging.getLogger(__name__)
logger.info("Loaded swap.py from e:\\Program\\cryptobot\\swap.py")

# --- Config ---
RPC_URL = os.environ.get("RPC_URL")
if not RPC_URL:
    print("i need RPC_URL")
else:
    print("i have RPC_URL")  # Your QuickNode RPC

QUOTE_API = os.environ.get("QUOTE_API")
if not QUOTE_API:
    print("i need QUOTE_API")
else:
    print("i have QUOTE_API")

TX_API = os.environ.get("TX_API")
if not TX_API:
    print("i need TX_API")
else:
    print("i have TX_API")

SYSTEM_SOL = "So11111111111111111111111111111111111111112"
MINIMUM_SOL_BALANCE = 0.005  # Estimated transaction fees

# --- Fetch Token Decimals ---
async def get_token_decimals(client: AsyncClient, mint: str, payer: Keypair) -> int:
    try:
        token = AsyncToken(client, Pubkey.from_string(mint), Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"), payer)
        mint_info = await token.get_mint_info()
        return mint_info.decimals
    except Exception as e:
        logger.error(f"Failed to get decimals for {mint}: {e}")
        raise Exception(f"❌ Not supported PUPMP.FUN tokens: {e}")

# --- Deserialize Transaction ---
def deserialize_transaction_b64(b64_tx: str) -> VersionedTransaction:
    try:
        tx_bytes = base64.b64decode(b64_tx)
        return VersionedTransaction.from_bytes(tx_bytes)
    except Exception as e:
        raise Exception(f"❌ Failed to deserialize transaction: {e}")

# --- Check Wallet Balance ---
async def check_balance(client: AsyncClient, public_key: str) -> float:
    try:
        response = await client.get_balance(Pubkey.from_string(public_key))
        return response.value / 1e9
    except Exception as e:
        raise Exception(f"❌ Failed to check balance: {e}")

# --- Check Token Balance ---
async def check_token_balance(client: AsyncClient, owner: Pubkey, mint: str, payer: Keypair) -> float:
    try:
        ata = get_associated_token_address(owner, Pubkey.from_string(mint))
        token = AsyncToken(client, Pubkey.from_string(mint), Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"), payer)
        balance_response = await token.get_balance(ata)
        return balance_response.value.ui_amount or 0.0
    except Exception as e:
        raise Exception(f"❌ Failed to check token balance for {mint}: {e}")

# --- Check Token Account with Retry ---
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
async def ensure_token_account(client: AsyncClient, owner: Pubkey, mint: str, payer: Keypair) -> Pubkey:
    ata = get_associated_token_address(owner, Pubkey.from_string(mint))
    logger.info(f"Checking ATA existence for mint {mint} at {ata}")
    account_info = await client.get_account_info(ata, commitment="confirmed")
    logger.info(f"ATA check response for {ata}: {account_info}")
    if account_info.value is None:
        raise Exception(f"❌ Token account for {mint} does not exist. Create it first.")
    logger.info(f"ATA confirmed for {mint} at {ata}")
    return ata

# --- Create Token Account ---
async def create_token_account(client: AsyncClient, payer: Keypair, owner: Pubkey, mint: str) -> None:
    ata = get_associated_token_address(owner, Pubkey.from_string(mint))
    account_info = await client.get_account_info(ata, commitment="confirmed")
    if account_info.value is None:
        logger.info(f"Creating ATA for mint {mint} at {ata}")
        try:
            blockhash_resp = await client.get_latest_blockhash()
            recent_blockhash = blockhash_resp.value.blockhash
            logger.info(f"Using blockhash: {recent_blockhash}")

            instruction = create_associated_token_account(payer.pubkey(), owner, Pubkey.from_string(mint))

            tx = Transaction.new_with_payer([instruction], payer.pubkey())
            tx.sign([payer], recent_blockhash)

            txid = await client.send_transaction(tx, opts=TxOpts(skip_preflight=True))
            logger.info(f"ATA creation transaction sent: {txid.value}")
            await client.confirm_transaction(txid.value, commitment="finalized")
            logger.info(f"Created token account for {mint}: {ata}")

            sleep(1)
        except Exception as e:
            logger.error(f"Failed to create token account for {mint}: {e}")
            raise Exception(f"❌ Failed to create token account for {mint}: {e}")

# --- Fetch Address Lookup Tables ---
async def get_address_lookup_table_accounts(client: AsyncClient, keys: list[str]) -> list[AddressLookupTableAccount]:
    lookup_table_accounts = []
    account_infos = await client.get_multiple_accounts([Pubkey.from_string(key) for key in keys])
    for i, account_info in enumerate(account_infos.value):
        if account_info:
            lookup_table_accounts.append(AddressLookupTableAccount(
                key=Pubkey.from_string(keys[i]),
                state=AddressLookupTableAccount.deserialize(account_info.data)
            ))
    return lookup_table_accounts

# --- Perform Swap ---
async def perform_swap(user_id: int, input_mint: str, output_mint: str, amount: float, aes_password: bytes) -> str:
    logger.info(f"perform_swap called with user_id={user_id}, input_mint={input_mint}, output_mint={output_mint}, amount={amount}")
    if not isinstance(user_id, int):
        raise ValueError(f"Invalid user_id: {user_id} is not an integer")
    if not check_access(user_id, "buy_sell"):  # Changed "swap" to "buy_sell" to match access rules
        raise Exception("❌ Swap available only for Plus or Pro users.")

    encrypted = get_encrypted_key(user_id)
    if not encrypted:
        raise Exception("⚠️ Wallet not found. Use /create_wallet or /import_wallet first.")

    client = AsyncClient(RPC_URL)
    try:
        privkey_bytes = decrypt_private_key(encrypted, aes_password)
        logger.info(f"Decrypted private key (first 10 bytes): {privkey_bytes[:10]}...")
        keypair = load_keypair(privkey_bytes)
        logger.info(f"Loaded public key: {keypair.pubkey()}")

        public_key = str(keypair.pubkey())
        logger.info(f"Public Key: {public_key}")

        # Fetch decimals for input and output mints
        input_decimals = await get_token_decimals(client, input_mint, keypair) if input_mint != SYSTEM_SOL else 9
        output_decimals = await get_token_decimals(client, output_mint, keypair) if output_mint != SYSTEM_SOL else 9

        # Convert amount to lamports based on input decimals
        lamports = int(amount * (10 ** input_decimals))

        # --- Check Balances ---
        balance = await check_balance(client, public_key)
        logger.info(f"Wallet Balance: {balance} SOL")

        # Check SOL balance based on swap direction
        required_balance = MINIMUM_SOL_BALANCE if input_mint != SYSTEM_SOL else amount + MINIMUM_SOL_BALANCE
        if balance < required_balance:
            raise Exception(f"❌ Insufficient SOL balance: {balance} SOL. Required: {required_balance} SOL")

        # Check token balance for token-to-SOL swaps
        if input_mint != SYSTEM_SOL:
            token_balance = await check_token_balance(client, keypair.pubkey(), input_mint, keypair)
            logger.info(f"Token Balance: {token_balance} {input_mint}")
            if token_balance < amount:
                raise Exception(f"❌ Insufficient token balance: {token_balance} {input_mint}. Required: {amount}")

        if output_mint != SYSTEM_SOL:
            await create_token_account(client, keypair, keypair.pubkey(), output_mint)
            await ensure_token_account(client, keypair.pubkey(), output_mint, keypair)

        # --- Step 1: Get Quote ---
        sleep(0.1)  # Respect 10 req/s limit
        quote_params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(lamports),
            "slippageBps": 50,
            "maxAccounts": 54,
            "onlyDirectRoutes": "true",
            "asLegacyTransaction": "false"
        }

        try:
            quote_res = requests.get(QUOTE_API, params=quote_params, headers={"Accept": "application/json"})
            logger.info(f"Quote Response: {quote_res.status_code} {quote_res.text}")
            logger.info(f"Quote Headers: {quote_res.headers}")
            quote_res.raise_for_status()
            quote_data = quote_res.json()
        except RequestException as e:
            raise Exception(f"❌ Failed to fetch quote: {e}")

        if not quote_data:
            raise Exception("❌ Quote failed: No data returned")

        # --- Step 2: Get Transaction ---
        tx_payload = {
            "userPublicKey": public_key,
            "quoteResponse": quote_data,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": "auto"
        }
        logger.info(f"Transaction Payload: {tx_payload}")

        try:
            sleep(0.1)  # Respect rate limit
            tx_res = requests.post(TX_API, json=tx_payload, headers={"Content-Type": "application/json", "Accept": "application/json"})
            logger.info(f"Swap Response: {tx_res.status_code} {tx_res.text}")
            logger.info(f"Swap Headers: {tx_res.headers}")
            tx_res.raise_for_status()
            tx_data = tx_res.json()
        except RequestException as e:
            raise Exception(f"❌ Failed to get transaction: {e}")

        if "error" in tx_data:
            raise Exception(f"❌ Jupiter API error: {tx_data.get('error', 'Unknown error')}")

        tx_b64 = tx_data.get("swapTransaction")
        logger.info(f"Transaction Base64: {tx_b64}")
        if not tx_b64:
            raise Exception(f"❌ No transaction returned by Jupiter: {tx_data.get('error', 'Unknown error')}")

        # --- Step 3: Deserialize and add fee ---
        tx = deserialize_transaction_b64(tx_b64)
        lookup_table_keys = tx_data.get("addressLookupTableAddresses", [])
        lookup_table_accounts = await get_address_lookup_table_accounts(client, lookup_table_keys)

        fee_instr = await create_fee_instruction(keypair.pubkey(), lamports)
        if fee_instr:
            pass

        # --- Step 4: Sign and Send ---
        message = tx.message
        signed_tx = VersionedTransaction(message, [keypair])
        logger.info(f"Signed Transaction: {signed_tx}")

        @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
        async def send_transaction_with_retry(client, tx):
            raw_tx = bytes(tx)
            txid = await client.send_raw_transaction(raw_tx, opts=TxOpts(skip_preflight=True, max_retries=3))
            logger.info(f"Transaction ID: {txid.value}")
            await client.confirm_transaction(txid.value, commitment="confirmed")
            return str(txid.value)

        result = await send_transaction_with_retry(client, signed_tx)
        return f"✅ Swap submitted: https://solscan.io/tx/{result}"
    except Exception as e:
        logger.error(f"Swap failed: {e}")
        raise
    finally:
        await client.close()


