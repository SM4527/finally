from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from .cache import PriceCache


class MarketDataSource(ABC):
    """Produces prices for a set of tracked tickers and writes them into a PriceCache.

    Contract (both implementations, verified by test_interface_conformance.py):
      * Tickers passed in are already normalized (uppercase, trimmed, valid). See tickers.py.
      * start() begins background production and returns once the source is running.
      * add_ticker() is idempotent. On success the ticker has a price in the cache before
        the call returns. Raises ValueError if the source does not know the symbol.
      * remove_ticker() is idempotent; it stops tracking and removes the ticker from the cache.
      * stop() cancels background work and is safe to call more than once.
      * The source never decides *whether* a ticker should be tracked. Callers apply the
        watchlist ∪ positions rule (tracking.py).
    """

    def __init__(self, cache: PriceCache) -> None:
        self.cache = cache

    @abstractmethod
    async def start(self, tickers: Iterable[str]) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None: ...

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None: ...

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Currently tracked tickers, sorted."""
