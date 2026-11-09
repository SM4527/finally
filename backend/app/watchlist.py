"""Watchlist services: keeps the database and the tracked tickers in step."""

from app.db import repo
from app.market import PriceCache, track, untrack_if_unused
from app.market.interface import MarketDataSource
from app.tickers import normalize_ticker


def entry_view(cache: PriceCache, entry: dict) -> dict:
    """One watchlist item: {ticker, price, added_at}; price is None until the first tick."""
    return {
        "ticker": entry["ticker"],
        "price": cache.get_price(entry["ticker"]),
        "added_at": entry["added_at"],
    }


def list_watchlist(conn, cache: PriceCache) -> dict:
    """The GET /api/watchlist response."""
    return {"watchlist": [entry_view(cache, e) for e in repo.get_watchlist(conn)]}


async def add_ticker(conn, source: MarketDataSource, cache: PriceCache, ticker: str) -> dict:
    """Track the ticker, then add it to the watchlist. Raises ValueError (-> 400)."""
    ticker = normalize_ticker(ticker)
    existing = repo.get_watchlist_entry(conn, ticker)
    if existing is None:
        await track(source, ticker)
        existing = repo.add_watchlist(conn, ticker)
    return entry_view(cache, existing)


async def remove_ticker(conn, source: MarketDataSource, ticker: str) -> None:
    """Remove from the watchlist; untrack unless a position is held. KeyError if absent."""
    ticker = normalize_ticker(ticker)
    if not repo.remove_watchlist(conn, ticker):
        raise KeyError(ticker)
    has_position = repo.get_position(conn, ticker) is not None
    await untrack_if_unused(source, ticker, on_watchlist=False, has_position=has_position)
