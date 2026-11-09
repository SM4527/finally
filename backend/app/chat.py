"""Chat service: builds the prompt, calls the LLM, executes its actions, stores history."""

import json

from app import portfolio, watchlist
from app.db import repo
from app.llm import ChatReply, Trade, WatchlistChange, get_chat_reply
from app.market import PriceCache
from app.market.interface import MarketDataSource
from app.market.massive import MassiveAuthError

HISTORY_LIMIT = 20
ACTION_ERRORS = (ValueError, KeyError, ConnectionError, MassiveAuthError)

SYSTEM_PROMPT = """You are FinAlly, an AI trading assistant inside a simulated trading workstation.
The user trades a virtual portfolio with fake money using market orders that fill instantly.

You can:
- Analyze portfolio composition, risk concentration and P&L.
- Suggest trades with brief reasoning.
- Execute trades when the user asks or agrees, by listing them in "trades".
- Manage the watchlist proactively, by listing changes in "watchlist_changes".

Rules:
- Be concise and data-driven. Quote numbers from the portfolio context.
- Only list a trade when the user asked for it or agreed to it. Quantities must be > 0.
- Use plain ticker symbols such as AAPL.
- Leave "trades" and "watchlist_changes" empty when there is nothing to do.
- Always respond with valid JSON matching the required schema."""


def _context(conn, cache: PriceCache) -> str:
    """Current portfolio and watchlist as JSON for the prompt."""
    data = {
        "portfolio": portfolio.portfolio_summary(conn, cache),
        "watchlist": watchlist.list_watchlist(conn, cache)["watchlist"],
    }
    return "Current portfolio context (prices in USD):\n" + json.dumps(data)


def build_messages(conn, cache: PriceCache, message: str) -> list[dict]:
    """System prompt, portfolio context, last 20 messages, then the new user message."""
    history = repo.get_chat_messages(conn, limit=HISTORY_LIMIT)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": _context(conn, cache)},
        *({"role": m["role"], "content": m["content"]} for m in history),
        {"role": "user", "content": message},
    ]


def _error_text(exc: Exception) -> str:
    if isinstance(exc, KeyError):
        return f"{exc.args[0]} is not on the watchlist"
    if isinstance(exc, (ConnectionError, MassiveAuthError)):
        return "Market data unavailable, try again in a moment"
    return str(exc)


async def _apply_watchlist_change(conn, cache, source, change: WatchlistChange) -> dict:
    result = {"ticker": change.ticker.strip().upper(), "action": change.action,
              "status": "ok", "error": None}
    try:
        if change.action == "add":
            result["ticker"] = (await watchlist.add_ticker(conn, source, cache, change.ticker))["ticker"]
        else:
            await watchlist.remove_ticker(conn, source, change.ticker)
    except ACTION_ERRORS as exc:
        result.update(status="error", error=_error_text(exc))
    return result


async def _apply_trade(conn, cache, source, trade: Trade) -> dict:
    result = {"ticker": trade.ticker.strip().upper(), "side": trade.side,
              "quantity": trade.quantity, "status": "ok", "price": None, "error": None}
    try:
        done = await portfolio.execute_trade(conn, cache, source, trade.ticker, trade.side, trade.quantity)
        result.update(ticker=done["trade"]["ticker"], price=done["trade"]["price"])
    except ACTION_ERRORS as exc:
        result.update(status="error", error=_error_text(exc))
    return result


async def execute_actions(conn, cache, source, reply: ChatReply) -> dict:
    """All watchlist changes first, then trades in order; each one fails independently."""
    changes = [await _apply_watchlist_change(conn, cache, source, c) for c in reply.watchlist_changes]
    trades = [await _apply_trade(conn, cache, source, t) for t in reply.trades]
    return {"watchlist_changes": changes, "trades": trades}


async def handle_chat(conn, cache: PriceCache, source: MarketDataSource, message: str) -> dict:
    """The POST /api/chat flow. Raises LLMUnavailable (-> 503)."""
    reply = await get_chat_reply(build_messages(conn, cache, message))
    actions = await execute_actions(conn, cache, source, reply)
    repo.insert_chat_message(conn, "user", message, None)
    repo.insert_chat_message(conn, "assistant", reply.message, actions)
    return {"message": reply.message, **actions}


def chat_history(conn) -> dict:
    """The GET /api/chat response: last 50 messages, oldest first."""
    return {"messages": repo.get_chat_messages(conn, limit=50)}
