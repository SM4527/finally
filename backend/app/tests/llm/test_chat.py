from unittest.mock import AsyncMock

import pytest

from app import chat
from app.llm import ChatReply, LLMUnavailable, Trade, WatchlistChange


def reply(trades=(), changes=(), message="ok"):
    return ChatReply(message=message, trades=list(trades), watchlist_changes=list(changes))


@pytest.fixture
def llm_reply(monkeypatch):
    mock = AsyncMock(return_value=reply())
    monkeypatch.setattr(chat, "get_chat_reply", mock)
    return mock


def test_watchlist_changes_run_before_trades(client, llm_reply):
    llm_reply.return_value = reply(
        trades=[Trade(ticker="pypl", side="buy", quantity=2)],
        changes=[WatchlistChange(ticker=" pypl ", action="add")],
    )
    body = client.post("/api/chat", json={"message": "add and buy PYPL"}).json()
    assert body["watchlist_changes"] == [{"ticker": "PYPL", "action": "add", "status": "ok", "error": None}]
    assert body["trades"] == [{"ticker": "PYPL", "side": "buy", "quantity": 2, "status": "ok",
                               "price": 100.0, "error": None}]
    assert client.get("/api/portfolio").json()["positions"][0]["ticker"] == "PYPL"


def test_failures_are_independent(client, llm_reply):
    llm_reply.return_value = reply(
        trades=[Trade(ticker="AAPL", side="sell", quantity=5),
                Trade(ticker="AAPL", side="buy", quantity=1),
                Trade(ticker="AAPL", side="buy", quantity=1000)],
        changes=[WatchlistChange(ticker="NOPE", action="add"),
                 WatchlistChange(ticker="ZZZZ", action="remove"),
                 WatchlistChange(ticker="MSFT", action="remove")],
    )
    body = client.post("/api/chat", json={"message": "go"}).json()
    assert [c["status"] for c in body["watchlist_changes"]] == ["error", "error", "ok"]
    assert body["watchlist_changes"][0]["error"] == "Unknown ticker NOPE"
    assert body["watchlist_changes"][1]["error"] == "ZZZZ is not on the watchlist"
    assert [t["status"] for t in body["trades"]] == ["error", "ok", "error"]
    assert body["trades"][0]["price"] is None and "hold" in body["trades"][0]["error"]
    assert "Insufficient cash" in body["trades"][2]["error"]
    assert client.get("/api/portfolio").json()["cash_balance"] == 9900.0


def test_messages_stored_and_returned(client, llm_reply):
    llm_reply.return_value = reply(trades=[Trade(ticker="AAPL", side="buy", quantity=1)], message="Bought")
    client.post("/api/chat", json={"message": "buy one"})
    messages = client.get("/api/chat").json()["messages"]
    assert [(m["role"], m["content"]) for m in messages] == [("user", "buy one"), ("assistant", "Bought")]
    assert messages[0]["actions"] is None
    assert messages[1]["actions"]["trades"][0]["status"] == "ok"
    assert messages[1]["actions"]["watchlist_changes"] == []


def test_prompt_has_context_and_history(client, llm_reply):
    client.post("/api/chat", json={"message": "first"})
    client.post("/api/chat", json={"message": "second"})
    messages = llm_reply.call_args.args[0]
    assert messages[0]["role"] == "system" and "FinAlly" in messages[0]["content"]
    assert '"cash_balance": 10000.0' in messages[1]["content"] and "AAPL" in messages[1]["content"]
    assert messages[2:] == [{"role": "user", "content": "first"}, {"role": "assistant", "content": "ok"},
                            {"role": "user", "content": "second"}]


def test_history_limited_to_20(client, llm_reply):
    for i in range(12):
        client.post("/api/chat", json={"message": f"m{i}"})
    messages = llm_reply.call_args.args[0]
    assert len(messages) == 2 + 20 + 1


def test_llm_unavailable_returns_503(client, llm_reply):
    llm_reply.side_effect = LLMUnavailable("rate limited")
    resp = client.post("/api/chat", json={"message": "hi"})
    assert resp.status_code == 503
    assert "busy" in resp.json()["detail"]
    assert client.get("/api/chat").json()["messages"] == []


def test_empty_message_returns_400(client, llm_reply):
    assert client.post("/api/chat", json={"message": "  "}).status_code == 400
    assert client.post("/api/chat", json={}).status_code == 400


def test_mock_mode_end_to_end(client, monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    body = client.post("/api/chat", json={"message": "buy please"}).json()
    assert body["trades"][0]["ticker"] == "AAPL" and body["trades"][0]["status"] == "ok"
    body = client.post("/api/chat", json={"message": "now sell"}).json()
    assert body["trades"][0]["side"] == "sell" and body["trades"][0]["status"] == "ok"
    assert client.get("/api/portfolio").json()["positions"] == []
    body = client.post("/api/chat", json={"message": "hello"}).json()
    assert body["trades"] == [] and body["watchlist_changes"] == []
