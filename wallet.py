import os
import base58
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
from solders.keypair import Keypair
import psycopg2



AES_PASSWORD = os.environ.get("AES_PASSWORD")
if not AES_PASSWORD:
    print("i need AES_PASSWORD")
else:
    print("i AES_PASSWORD")

# Use Railway PostgreSQL
conn = psycopg2.connect(os.environ["DATABASE_URL"])
c = conn.cursor()

# --- DB Setup ---
c.execute("""
CREATE TABLE IF NOT EXISTS swap_users (
    user_id INTEGER PRIMARY KEY,
    encrypted_privkey BYTEA,
    wallet_address TEXT
)
""")
conn.commit()

# --- AES ---
def encrypt_private_key(key_bytes: bytes, password: bytes) -> bytes:
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(password), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    padder = padding.PKCS7(128).padder()
    padded_key = padder.update(key_bytes) + padder.finalize()
    encrypted = encryptor.update(padded_key) + encryptor.finalize()
    return iv + encrypted

def decrypt_private_key(encrypted_data: bytes, password: bytes) -> bytes:
    iv = encrypted_data[:16]
    encrypted = encrypted_data[16:]
    cipher = Cipher(algorithms.AES(password), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded_key = decryptor.update(encrypted) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded_key) + unpadder.finalize()

# --- DB Ops ---
def save_encrypted_key(user_id: int, encrypted_key: bytes):
    c.execute("INSERT OR REPLACE INTO swap_users(user_id, encrypted_privkey) VALUES (%s, %s)", (user_id, encrypted_key))
    conn.commit()

def get_encrypted_key(user_id: int) -> bytes | None:
    c.execute("SELECT encrypted_privkey FROM swap_users WHERE user_id=%s", (user_id,))
    row = c.fetchone()
    return row[0] if row else None

# --- Wallet Ops ---
def generate_wallet() -> Keypair:
    return Keypair()

def load_keypair(privkey_bytes: bytes) -> Keypair:
    return Keypair.from_bytes(privkey_bytes)

def decode_base58_private_key(b58: str) -> bytes:
    return base58.b58decode(b58)
