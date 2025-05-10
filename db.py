import sqlite3
from datetime import datetime

DB_PATH = "alerts.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        user_id TEXT NOT NULL,
        asset TEXT NOT NULL,
        target_price REAL NOT NULL,
        direction TEXT CHECK(direction IN ('above','below')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        triggered INTEGER DEFAULT 0
    )""")

def insert_alert(user_id, asset, price, direction):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO alerts (user_id, asset, target_price, direction)
        VALUES (?, ?, ?, ?)
    """, (str(user_id), asset, price, direction))
    conn.commit()
    conn.close()

def get_active_alerts(user_id: str | None = None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if user_id is None:
        # no filter → return every active alert
        cursor.execute(
            "SELECT id, user_id, asset, target_price, direction FROM alerts WHERE triggered=0"
        )
    else:
        # only that user’s alerts
        cursor.execute(
            "SELECT id, asset, target_price, direction FROM alerts WHERE user_id=? AND triggered=0",
            (user_id,)
        )
    rows = cursor.fetchall()
    conn.close()
    return rows


def mark_triggered(alert_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE alerts SET triggered=1 WHERE id=?", (alert_id,)
    )
    conn.commit()
    conn.close()


def delete_alert(alert_id, user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM alerts WHERE id=? AND user_id=?", 
        (alert_id, user_id)
    )
    conn.commit()
    conn.close()
