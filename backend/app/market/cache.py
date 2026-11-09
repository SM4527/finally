from __future__ import annotations

import threading
import time

from .models import PriceUpdate


class PriceCache:
    """Latest price per ticker. `version` bumps only when something visible changed."""

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._lock = threading.Lock()
        self._version = 0

    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate:
        """Record a new price. previous_price is the last cached price (or the same price
        for the first update). Bumps `version` only if price or timestamp changed."""
        price = round(float(price), 2)
        ts = time.time() if timestamp is None else float(timestamp)
        with self._lock:
            prev = self._prices.get(ticker)
            if prev is not None and prev.price == price and prev.timestamp == ts:
                return prev
            update = PriceUpdate(
                ticker=ticker,
                price=price,
                previous_price=prev.price if prev else price,
                timestamp=ts,
            )
            self._prices[ticker] = update
            self._version += 1
            return update

    def remove(self, ticker: str) -> None:
        with self._lock:
            if self._prices.pop(ticker, None) is not None:
                self._version += 1

    def get(self, ticker: str) -> PriceUpdate | None:
        with self._lock:
            return self._prices.get(ticker)

    def get_price(self, ticker: str) -> float | None:
        update = self.get(ticker)
        return update.price if update else None

    def snapshot(self) -> dict[str, PriceUpdate]:
        """Shallow copy, safe to iterate while writers continue."""
        with self._lock:
            return dict(self._prices)

    @property
    def version(self) -> int:
        return self._version

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._prices

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)
