import os
from solders.keypair import Keypair
from base58 import b58encode, b58decode
from cryptography.fernet import Fernet
import psycopg2

# Get AES_PASSWORD from environment
AES_PASSWORD = os.environ.get("AES_PASSWORD") 

def generate_wallet():
    return Keypair()

def decode_base58_private_key(b58_string: str) -> bytes:
    return b58decode(b58_string)

def encrypt_private_key(privkey_bytes: bytes, aes_password: bytes) -> bytes:
    f = Fernet(aes_password)
    return f.encrypt(privkey_bytes)

def decrypt_private_key(encrypted: bytes, aes_password: bytes) -> bytes:
    f = Fernet(aes_password)
    return f.decrypt(encrypted)

def load_keypair(privkey_bytes: bytes) -> Keypair:
    return Keypair.from_bytes(privkey_bytes)

def save_encrypted_key(user_id: int, encrypted: bytes):
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    c.execute("INSERT INTO swap_users(user_id, encrypted_privkey) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET encrypted_privkey = %s", 
              (user_id, encrypted, encrypted))
    conn.commit()
    conn.close()

def get_encrypted_key(user_id: int) -> bytes:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    c = conn.cursor()
    c.execute("SELECT encrypted_privkey FROM swap_users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None