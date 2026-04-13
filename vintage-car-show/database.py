import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "event.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(default_employee_id: str, default_employee_password: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            buyer_name TEXT NOT NULL,
            buyer_mobile TEXT NOT NULL,
            buyer_whatsapp TEXT NOT NULL,
            buyer_age INTEGER NOT NULL,
            people_count INTEGER NOT NULL,
            amount_total INTEGER NOT NULL,
            payment_status TEXT NOT NULL DEFAULT 'pending',
            razorpay_order_id TEXT,
            razorpay_payment_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS attendees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            full_name TEXT NOT NULL,
            mobile TEXT NOT NULL,
            age INTEGER NOT NULL,
            qr_token TEXT NOT NULL UNIQUE,
            is_used INTEGER NOT NULL DEFAULT 0,
            scanned_by TEXT,
            scanned_at TIMESTAMP,
            FOREIGN KEY (booking_id) REFERENCES bookings (id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS employees (
            employee_id TEXT PRIMARY KEY,
            password TEXT NOT NULL
        )
        """
    )

    cursor.execute("SELECT employee_id FROM employees WHERE employee_id = ?", (default_employee_id,))
    exists = cursor.fetchone()
    if not exists:
        cursor.execute(
            "INSERT INTO employees (employee_id, password) VALUES (?, ?)",
            (default_employee_id, default_employee_password),
        )

    conn.commit()
    conn.close()
