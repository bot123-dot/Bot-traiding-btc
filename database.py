import sqlite3
import hashlib
import os
from datetime import datetime

DB_PATH = "bitmind.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        plan TEXT DEFAULT 'free',
        created_at TEXT,
        stripe_customer_id TEXT,
        mp_customer_id TEXT
    )''')
    conn.commit()
    conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_user(email, password):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (email, password, created_at) VALUES (?, ?, ?)",
                  (email, hash_password(password), datetime.now().isoformat()))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_user(email, password):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email=? AND password=?",
              (email, hash_password(password)))
    user = c.fetchone()
    conn.close()
    return user

def get_user_plan(email):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT plan FROM users WHERE email=?", (email,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else "free"

def update_user_plan(email, plan):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET plan=? WHERE email=?", (plan, email))
    conn.commit()
    conn.close()

init_db()
