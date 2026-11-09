"""SQLite connection, schema creation and default seed data."""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CASH = 10000.0
DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


def db_path() -> Path:
    """Database file: env FINALLY_DB_PATH, else <repo>/db/finally.db."""
    return Path(os.environ.get("FINALLY_DB_PATH") or REPO_ROOT / "db" / "finally.db")


def now_iso() -> str:
    """Current UTC time as ISO 8601 with a Z suffix, second precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open an autocommit connection; callers manage transactions explicitly."""
    path = Path(path or db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create missing tables and seed the default user and watchlist if absent."""
    conn.executescript(SCHEMA_PATH.read_text())
    if conn.execute("SELECT 1 FROM users_profile WHERE id = 'default'").fetchone():
        return
    now = now_iso()
    conn.execute("BEGIN")
    conn.execute(
        "INSERT INTO users_profile (id, cash_balance) VALUES ('default', ?)", (DEFAULT_CASH,)
    )
    conn.executemany(
        "INSERT OR IGNORE INTO watchlist (ticker, added_at) VALUES (?, ?)",
        [(t, now) for t in DEFAULT_TICKERS],
    )
    conn.execute("COMMIT")
