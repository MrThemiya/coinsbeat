import os
import base58
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
from solders.keypair import Keypair
import psycopg2

# Check AES_PASSWORD
AES_PASSWORD = os.environ.get("AES_PASSWORD")
if not AES_PASSWORD:
    print("i need AES_PASSWORD")
else:
    print("i AES_PASSWORD")

# --- AES ---
def encrypt_private_key(key_bytes: bytes, password: str) -> bytes:
    # Convert password to bytes
    key = password.encode('utf-8') if isinstance(password, str) else password
    if not isinstance(key, bytes):
        raise ValueError("Password must be convertible to bytes")

    # Generate IV (Initialization Vector)
    iv = os.urandom(16)

    # Create cipher
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()

    # Pad private_key to multiple of 16 (AES block size)
    padder = padding.PKCS7(128).padder()
    padded_key = padder.update(key_bytes) + padder.finalize()

    # Encrypt
    encrypted = encryptor.update(padded_key) + encryptor.finalize()

    # Return IV + ciphertext
    return iv + encrypted

def decrypt_private_key(encrypted_data: bytes, password: str) -> bytes:
    # Convert password to bytes
    key = password.encode('utf-8') if isinstance(password, str) else password
    if not isinstance(key, bytes):
        raise ValueError("Password must be convertible to bytes")

    # Extract IV and encrypted data
    iv = encrypted_data[:16]
    encrypted = encrypted_data[16:]

    # Create cipher
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()

    # Decrypt and unpad
    padded_key = decryptor.update(encrypted) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded_key) + unpadder.finalize()

# --- Wallet Ops ---
def generate_wallet() -> Keypair:
    return Keypair()

def load_keypair(privkey_bytes: bytes) -> Keypair:
    return Keypair.from_bytes(privkey_bytes)

def decode_base58_private_key(b58: str) -> bytes:
    return base58.b58decode(b58)

# --- DB Ops ---
def save_encrypted_key(user_id: int, encrypted_key: bytes):
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    try:
        c.execute("INSERT INTO swap_users (user_id, encrypted_privkey) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET encrypted_privkey = %s", 
                  (user_id, encrypted_key, encrypted_key))
        conn.commit()
    finally:
        conn.close()

def get_encrypted_key(user_id: int) -> bytes | None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    try:
        c.execute("SELECT encrypted_privkey FROM swap_users WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        return row[0] if row else None
    finally:
        conn.close()
