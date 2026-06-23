"""
Shared SQLite storage for leveling + invite tracking.

⚠️ If running on Railway without a persistent Volume, this file lives on
the container's temporary disk and will be WIPED on every redeploy. For a
real server, attach a Railway Volume and set DB_PATH to a path inside it
(e.g. /data/bot_data.db) — see README.
"""

import sqlite3
import os

DB_PATH = os.environ.get("DB_PATH", "bot_data.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS levels (
            user_id INTEGER PRIMARY KEY,
            xp INTEGER NOT NULL DEFAULT 0,
            level INTEGER NOT NULL DEFAULT 0,
            last_message_at REAL NOT NULL DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS invites (
            user_id INTEGER PRIMARY KEY,
            invite_count INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()
