"""
db/connection.py — SQLite connection helper.
"""
import sqlite3
from config import DB_PATH

def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection with row_factory set to dict-like access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
