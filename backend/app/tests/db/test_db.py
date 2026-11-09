"""Tests for app.db: schema init, seeding and repo functions."""

import re

import pytest

from app.db import connect, db_path, init_db, now_iso, repo
from app.db.connection import DEFAULT_TICKERS


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    init_db(c)
    yield c
    c.close()


def test_db_path_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FINALLY_DB_PATH", str(tmp_path / "x.db"))
    assert db_path() == tmp_path / "x.db"


def test_db_path_default(monkeypatch):
    monkeypatch.delenv("FINALLY_DB_PATH", raising=False)
    assert db_path().parts[-2:] == ("db", "finally.db")


def test_now_iso_format():
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", now_iso())


def test_connect_creates_parent_dir(tmp_path):
    c = connect(tmp_path / "nested" / "dir" / "f.db")
    assert (tmp_path / "nested" / "dir" / "f.db").exists()
    assert c.isolation_level is None
    c.close()


def test_init_creates_tables(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "users_profile", "watchlist", "positions", "trades", "portfolio_snapshots", "chat_messages"
    } <= names


def test_seed(conn):
    assert repo.get_cash(conn) == 10000.0
    assert [w["ticker"] for w in repo.get_watchlist(conn)] == DEFAULT_TICKERS


def test_init_is_idempotent(conn):
    repo.set_cash(conn, 5.0)
    repo.remove_watchlist(conn, "AAPL")
    init_db(conn)
    assert repo.get_cash(conn) == 5.0
    assert len(repo.get_watchlist(conn)) == 9


def test_init_on_existing_file(tmp_path):
    path = tmp_path / "p.db"
    c = connect(path)
    init_db(c)
    repo.set_cash(c, 42.0)
    c.close()
    c = connect(path)
    init_db(c)
    assert repo.get_cash(c) == 42.0
    c.close()


def test_cash(conn):
    repo.set_cash(conn, 1234.5678)
    assert repo.get_cash(conn) == 1234.5678


def test_position_upsert_and_delete(conn):
    assert repo.get_position(conn, "AAPL") is None
    repo.upsert_position(conn, "AAPL", 10, 190.5)
    repo.upsert_position(conn, "AAPL", 15, 191.25)
    repo.upsert_position(conn, "MSFT", 0.5, 400.0)
    p = repo.get_position(conn, "AAPL")
    assert (p["quantity"], p["avg_cost"]) == (15, 191.25)
    assert p["updated_at"].endswith("Z")
    assert [p["ticker"] for p in repo.get_positions(conn)] == ["AAPL", "MSFT"]
    repo.delete_position(conn, "AAPL")
    assert repo.get_position(conn, "AAPL") is None
    assert len(repo.get_positions(conn)) == 1


def test_insert_trade(conn):
    t = repo.insert_trade(conn, "AAPL", "buy", 2.5, 190.5)
    assert set(t) == {"id", "ticker", "side", "quantity", "price", "executed_at"}
    row = conn.execute("SELECT * FROM trades WHERE id = ?", (t["id"],)).fetchone()
    assert (row["user_id"], row["ticker"], row["side"], row["quantity"], row["price"]) == (
        "default", "AAPL", "buy", 2.5, 190.5
    )


def test_snapshots_order_and_limit(conn):
    assert repo.get_snapshots(conn) == []
    for v in range(5):
        repo.insert_snapshot(conn, float(v))
    assert [s["total_value"] for s in repo.get_snapshots(conn)] == [0, 1, 2, 3, 4]
    assert [s["total_value"] for s in repo.get_snapshots(conn, limit=3)] == [2, 3, 4]
    assert set(repo.get_snapshots(conn)[0]) == {"total_value", "recorded_at"}


def test_watchlist_add_idempotent(conn):
    entry = repo.add_watchlist(conn, "PYPL")
    assert entry["ticker"] == "PYPL"
    assert repo.add_watchlist(conn, "PYPL") == entry
    assert repo.get_watchlist(conn)[-1]["ticker"] == "PYPL"
    assert len(repo.get_watchlist(conn)) == 11


def test_watchlist_remove(conn):
    assert repo.remove_watchlist(conn, "AAPL") is True
    assert repo.remove_watchlist(conn, "AAPL") is False
    assert repo.get_watchlist_entry(conn, "AAPL") is None
    assert repo.get_watchlist_entry(conn, "MSFT")["ticker"] == "MSFT"


def test_chat_messages_round_trip(conn):
    actions = {"watchlist_changes": [{"ticker": "PYPL", "action": "add", "status": "ok", "error": None}],
               "trades": []}
    u = repo.insert_chat_message(conn, "user", "hi", None)
    a = repo.insert_chat_message(conn, "assistant", "hello", actions)
    assert set(u) == {"id", "role", "content", "actions", "created_at"}
    msgs = repo.get_chat_messages(conn)
    assert [m["id"] for m in msgs] == [u["id"], a["id"]]
    assert msgs[0]["actions"] is None
    assert msgs[1]["actions"] == actions


def test_chat_messages_limit(conn):
    for i in range(5):
        repo.insert_chat_message(conn, "user", str(i), None)
    assert [m["content"] for m in repo.get_chat_messages(conn, limit=2)] == ["3", "4"]


def test_transaction_rollback(conn):
    conn.execute("BEGIN IMMEDIATE")
    repo.set_cash(conn, 1.0)
    conn.execute("ROLLBACK")
    assert repo.get_cash(conn) == 10000.0
