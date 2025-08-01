import psycopg2
from datetime import datetime, timedelta
import os

# Use Railway PostgreSQL
conn = psycopg2.connect(os.environ["DATABASE_URL"])
c = conn.cursor()

# --- Get current user's package (free, plus, pro)
def get_user_package(user_id: int) -> str:
    c.execute("SELECT package FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    return row[0] if row and row[0] else "free"

# --- Get how many messages user has sent this month
def get_user_message_count(user_id: int) -> int:
    c.execute("SELECT messages_sent FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    return row[0] if row else 0

# --- Add 1 to message counter
def increment_message_count(user_id: int):
    c.execute("INSERT INTO users (user_id, messages_sent) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,))
    c.execute("UPDATE users SET messages_sent = messages_sent + 1 WHERE user_id = %s", (user_id,))
    conn.commit()

# --- Message limit based on package
def get_message_limit(package: str) -> int:
    limits = {
        "free": 250,
        "plus": 1000,
        "pro": 5000
    }
    return limits.get(package, 250)

# --- Check if user can send a message (not exceeded monthly limit)
def can_send_message(user_id: int) -> bool:
    package = get_user_package(user_id)
    count = get_user_message_count(user_id)
    limit = get_message_limit(package)
    return count < limit

# --- Price alert limit based on package
def get_alert_limit(package: str) -> int:
    limits = {
        "free": 1,
        "plus": 5,
        "pro": 20
    }
    return limits.get(package, 1)

# --- Get current alert count from alerts table
def get_user_alert_count(user_id: int) -> int:
    c.execute("SELECT COUNT(*) FROM alerts WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    return row[0] if row else 0

# --- Check if user can set another alert
def can_add_alert(user_id: int) -> bool:
    package = get_user_package(user_id)
    current_alerts = get_user_alert_count(user_id)
    return current_alerts < get_alert_limit(package)

# --- Check if user has permission to access a given service
def check_access(service: str, user_id: int) -> bool:
    package = get_user_package(user_id)

    access_rules = {
        "buy_sell": ["plus", "pro"],
        "auto_snipe": ["pro"],
        "airdrop": ["pro"],
        "news": ["pro"]
    }

    allowed_packages = access_rules.get(service, ["free", "plus", "pro"])
    return package in allowed_packages

# --- Optional: Reset message counters monthly (run this once a month)
def reset_message_counters():
    c.execute("UPDATE users SET messages_sent = 0")
    conn.commit()
