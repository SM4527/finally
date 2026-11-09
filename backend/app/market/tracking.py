from __future__ import annotations

from .interface import MarketDataSource


async def track(source: MarketDataSource, ticker: str) -> None:
    """Ensure the source tracks `ticker`. Propagates ValueError (unknown symbol)."""
    await source.add_ticker(ticker)


async def untrack_if_unused(
    source: MarketDataSource,
    ticker: str,
    *,
    on_watchlist: bool,
    has_position: bool,
) -> bool:
    """Remove from the source only if neither the watchlist nor a position needs it.
    Returns True if the ticker was removed."""
    if on_watchlist or has_position:
        return False
    await source.remove_ticker(ticker)
    return True
