"""Data access functions. They never open transactions; the caller does."""

import json
import sqlite3
import uuid

from .connection import now_iso


def get_cash(conn: sqlite3.Connection, user_id: str = "default") -> float:
    """Return the user's cash balance."""
    row = conn.execute("SELECT cash_balance FROM users_profile WHERE id = ?", (user_id,)).fetchone()
    return row["cash_balance"]


def set_cash(conn: sqlite3.Connection, cash: float, user_id: str = "default") -> None:
    """Set the user's cash balance."""
    conn.execute("UPDATE users_profile SET cash_balance = ? WHERE id = ?", (cash, user_id))


def get_positions(conn: sqlite3.Connection, user_id: str = "default") -> list[dict]:
    """All positions ordered by ticker."""
    rows = conn.execute(
        "SELECT ticker, quantity, avg_cost, updated_at FROM positions"
        " WHERE user_id = ? ORDER BY ticker",
        (user_id,),
    )
    return [dict(r) for r in rows]


def get_position(conn: sqlite3.Connection, ticker: str, user_id: str = "default") -> dict | None:
    """One position, or None if not held."""
    row = conn.execute(
        "SELECT ticker, quantity, avg_cost, updated_at FROM positions"
        " WHERE user_id = ? AND ticker = ?",
        (user_id, ticker),
    ).fetchone()
    return dict(row) if row else None


def upsert_position(
    conn: sqlite3.Connection, ticker: str, quantity: float, avg_cost: float, user_id: str = "default"
) -> None:
    """Insert or replace the quantity and average cost of a position."""
    conn.execute(
        "INSERT INTO positions (user_id, ticker, quantity, avg_cost, updated_at)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT (user_id, ticker) DO UPDATE SET"
        " quantity = excluded.quantity, avg_cost = excluded.avg_cost,"
        " updated_at = excluded.updated_at",
        (user_id, ticker, quantity, avg_cost, now_iso()),
    )


def delete_position(conn: sqlite3.Connection, ticker: str, user_id: str = "default") -> None:
    """Delete a position row."""
    conn.execute("DELETE FROM positions WHERE user_id = ? AND ticker = ?", (user_id, ticker))


def insert_trade(
    conn: sqlite3.Connection,
    ticker: str,
    side: str,
    quantity: float,
    price: float,
    user_id: str = "default",
) -> dict:
    """Append a trade and return it."""
    trade = {
        "id": str(uuid.uuid4()),
        "ticker": ticker,
        "side": side,
        "quantity": quantity,
        "price": price,
        "executed_at": now_iso(),
    }
    conn.execute(
        "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at)"
        " VALUES (:id, :user_id, :ticker, :side, :quantity, :price, :executed_at)",
        {**trade, "user_id": user_id},
    )
    return trade


def insert_snapshot(conn: sqlite3.Connection, total_value: float, user_id: str = "default") -> None:
    """Record a portfolio value snapshot."""
    conn.execute(
        "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), user_id, total_value, now_iso()),
    )


def get_snapshots(conn: sqlite3.Connection, limit: int = 1000, user_id: str = "default") -> list[dict]:
    """The most recent `limit` snapshots, oldest first."""
    rows = conn.execute(
        "SELECT total_value, recorded_at FROM portfolio_snapshots WHERE user_id = ?"
        " ORDER BY recorded_at DESC, rowid DESC LIMIT ?",
        (user_id, limit),
    )
    return [dict(r) for r in rows][::-1]


def get_watchlist(conn: sqlite3.Connection, user_id: str = "default") -> list[dict]:
    """Watchlist entries in the order they were added."""
    rows = conn.execute(
        "SELECT ticker, added_at FROM watchlist WHERE user_id = ? ORDER BY added_at, rowid",
        (user_id,),
    )
    return [dict(r) for r in rows]


def get_watchlist_entry(conn: sqlite3.Connection, ticker: str, user_id: str = "default") -> dict | None:
    """One watchlist entry, or None."""
    row = conn.execute(
        "SELECT ticker, added_at FROM watchlist WHERE user_id = ? AND ticker = ?",
        (user_id, ticker),
    ).fetchone()
    return dict(row) if row else None


def add_watchlist(conn: sqlite3.Connection, ticker: str, user_id: str = "default") -> dict:
    """Add a ticker; return the existing entry if it is already present."""
    conn.execute(
        "INSERT OR IGNORE INTO watchlist (user_id, ticker, added_at) VALUES (?, ?, ?)",
        (user_id, ticker, now_iso()),
    )
    return get_watchlist_entry(conn, ticker, user_id)


def remove_watchlist(conn: sqlite3.Connection, ticker: str, user_id: str = "default") -> bool:
    """Remove a ticker; False if it was not on the list."""
    cur = conn.execute("DELETE FROM watchlist WHERE user_id = ? AND ticker = ?", (user_id, ticker))
    return cur.rowcount > 0


def insert_chat_message(
    conn: sqlite3.Connection,
    role: str,
    content: str,
    actions: dict | None,
    user_id: str = "default",
) -> dict:
    """Store a chat message and return it."""
    msg = {
        "id": str(uuid.uuid4()),
        "role": role,
        "content": content,
        "actions": actions,
        "created_at": now_iso(),
    }
    conn.execute(
        "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            msg["id"],
            user_id,
            role,
            content,
            None if actions is None else json.dumps(actions),
            msg["created_at"],
        ),
    )
    return msg


def get_chat_messages(conn: sqlite3.Connection, limit: int = 50, user_id: str = "default") -> list[dict]:
    """The most recent `limit` messages, oldest first, with actions decoded."""
    rows = conn.execute(
        "SELECT id, role, content, actions, created_at FROM chat_messages WHERE user_id = ?"
        " ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (user_id, limit),
    )
    messages = [dict(r) for r in rows][::-1]
    for m in messages:
        m["actions"] = None if m["actions"] is None else json.loads(m["actions"])
    return messages
