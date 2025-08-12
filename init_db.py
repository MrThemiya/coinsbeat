import psycopg2
import os

# Railway PostgreSQL connection
conn = psycopg2.connect(os.environ["DATABASE_URL"])
cursor = conn.cursor()

# users.db tables
cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        region TEXT,
        package TEXT,
        price REAL,
        start_date TEXT,
        duration TEXT,
        wallet_address TEXT,
        last_airdrop_sent TEXT,
        messages_sent INTEGER DEFAULT 0,
        messages INTEGER DEFAULT 0,
        referrer_id BIGINT,
        auto_news INTEGER DEFAULT 1,
        paid INTEGER DEFAULT 0
    );
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS last_tweet (
        id SERIAL PRIMARY KEY,
        tweet_id TEXT
    );
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        user_id BIGINT,
        symbol TEXT,
        threshold REAL
    );
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS sent_news (
        tweet_id TEXT PRIMARY KEY,
        tweet TEXT,
        date_sent TEXT
    );
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS referrals (
        referrer_id BIGINT,
        referred_id BIGINT PRIMARY KEY
    );
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS airdrops (
        id TEXT PRIMARY KEY,
        name TEXT,
        network TEXT,
        category TEXT,
        description TEXT,
        url TEXT
    );
""")

# swap_users.db table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS swap_users (
        user_id BIGINT PRIMARY KEY,
        encrypted_privkey BYTEA,
        wallet_address TEXT
    );
""")

# price_cache.db table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS price_cache (
        symbol TEXT PRIMARY KEY,
        price REAL,
        timestamp BIGINT
    );
""")

# referrals.db tables
cursor.execute("""
    CREATE TABLE IF NOT EXISTS referral_data (
        user_id BIGINT PRIMARY KEY,
        messages_remaining INTEGER DEFAULT 0,
        expiry TIMESTAMP
    );
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS referral_tracking (
        referee_id BIGINT PRIMARY KEY,
        referrer_id BIGINT,
        timestamp TIMESTAMP
    );
""")

conn.commit()

cursor.close()
conn.close()

print("All tables created successfully!")