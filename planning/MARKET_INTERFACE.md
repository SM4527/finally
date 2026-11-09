# Market Data Interface

The unified Python API the backend uses for stock prices. One abstract interface sits in front of two implementations:

- `SimulatorDataSource`: used by default. See MARKET_SIMULATOR.md.
- `MassiveDataSource`: used when `MASSIVE_API_KEY` is set. See MASSIVE_API.md.

Everything downstream (SSE, trades, portfolio valuation, the LLM context) reads from one `PriceCache` and never knows which source is running.

The code below was run against Python 3.13 and `massive` 2.9.1 before it was written here. The Massive path was checked with faked HTTP responses, not a live key.

## 1. Design

```
                 create_market_data_source(cache)
                   MASSIVE_API_KEY set? ──yes──> MassiveDataSource ──┐
                                      └──no───> SimulatorDataSource ─┤ writes
                                                                     v
 SSE /api/stream/prices  <── reads ──  PriceCache  ── reads ──>  trade service,
 (when cache.version changes)          {ticker: PriceUpdate}     portfolio, watchlist, LLM
```

Principles:

1. **Push to a cache, never pull from the source.** Sources write the latest price into `PriceCache` on their own schedule: the simulator every 500 ms, Massive every 15 s. Readers never wait on the network.
2. **The source owns the set of tracked tickers.** The API layer tells it what to track (`watchlist ∪ positions`) through `add_ticker` and `remove_ticker`.
3. **`add_ticker` is synchronous in effect.** When it returns, the ticker has a price in the cache, so "add PYPL and buy 5" works in one chat turn. It raises `ValueError` for a symbol the source does not know.
4. **The cache rounds to 2 dp and ignores unchanged prices.** `version` bumps only on a real change, so the SSE loop can skip idle ticks (for example Massive outside market hours).
5. **Single process, single event loop.** All writes happen on the event loop (Massive's blocking HTTP runs in `asyncio.to_thread`, but its results are written back on the loop), so no locks are needed.

## 2. Module Layout

```
backend/app/market/
├── __init__.py        # public exports
├── models.py          # PriceUpdate
├── cache.py           # PriceCache
├── base.py            # MarketDataSource (ABC)
├── factory.py         # create_market_data_source()
├── massive_client.py  # MassiveDataSource
├── simulator.py       # GBMSimulator + SimulatorDataSource (MARKET_SIMULATOR.md)
├── seed_prices.py     # per-ticker GBM params (MARKET_SIMULATOR.md)
└── stream.py          # SSE router for /api/stream/prices
```

Dependency: `uv add massive`. The simulator uses only the standard library.

## 3. `PriceUpdate` — `models.py`

An immutable value for one ticker. `to_dict()` is exactly the per-ticker object in the SSE payload (PLAN.md Section 6). `change` and `change_percent` are relative to the previous tick.

```python
"""Price data model shared by every market data source."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """One ticker's latest price relative to its previous price."""

    ticker: str
    price: float
    previous_price: float
    timestamp: float  # Unix seconds

    @property
    def change(self) -> float:
        return round(self.price - self.previous_price, 2)

    @property
    def change_percent(self) -> float:
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 3)

    @property
    def direction(self) -> Literal["up", "down", "flat"]:
        if self.price > self.previous_price:
            return "up"
        if self.price < self.previous_price:
            return "down"
        return "flat"

    def to_dict(self) -> dict:
        """JSON shape used by the SSE stream."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "direction": self.direction,
        }
```

## 4. `PriceCache` — `cache.py`

```python
"""In-memory latest-price cache shared by the data source and its readers."""

import time

from .models import PriceUpdate


class PriceCache:
    """Latest price per ticker. One writer (the data source), many readers."""

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self.version = 0  # bumped on every change; SSE compares it to skip idle ticks

    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate:
        """Store a new price (rounded to 2 dp). The first price is its own previous price."""
        price = round(price, 2)
        old = self._prices.get(ticker)
        if old is not None and old.price == price:
            return old
        update = PriceUpdate(
            ticker=ticker,
            price=price,
            previous_price=old.price if old else price,
            timestamp=timestamp if timestamp is not None else time.time(),
        )
        self._prices[ticker] = update
        self.version += 1
        return update

    def get(self, ticker: str) -> PriceUpdate | None:
        return self._prices.get(ticker)

    def get_price(self, ticker: str) -> float | None:
        update = self._prices.get(ticker)
        return update.price if update else None

    def get_all(self) -> dict[str, PriceUpdate]:
        return dict(self._prices)

    def remove(self, ticker: str) -> None:
        if self._prices.pop(ticker, None) is not None:
            self.version += 1
```

Notes:

- The first price for a ticker has `previous_price == price` (direction `"flat"`).
- `timestamp` is the time the price was received (Unix seconds), not the exchange time. That keeps Massive's nanosecond and millisecond units out of the rest of the app.
- The trade service reads `cache.get_price(ticker)`. `None` means "No price yet for X" (HTTP 400).

## 5. `MarketDataSource` — `base.py`

```python
"""Abstract interface implemented by the simulator and the Massive client."""

from abc import ABC, abstractmethod


class MarketDataSource(ABC):
    """Produces prices for a set of tickers and writes them to a PriceCache."""

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing prices for the tickers. Called once at startup."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the background task. Safe to call more than once."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Track a ticker; it has a price in the cache when this returns.

        Raises ValueError if the source does not know the symbol.
        """

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Stop tracking a ticker and drop it from the cache."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Tickers currently tracked."""
```

Contract both implementations satisfy:

| Method | Behaviour |
|---|---|
| `start(tickers)` | Seeds the cache for every ticker (the simulator from seed prices, Massive with one blocking poll), then starts the background task |
| `stop()` | Cancels the task. Idempotent. |
| `add_ticker(t)` | No-op if already tracked. Otherwise the cache has a price on return, or it raises `ValueError("Unknown ticker T")` and nothing changes |
| `remove_ticker(t)` | Stops tracking and removes the ticker from the cache. A no-op if the ticker was not tracked |
| `get_tickers()` | Sorted list of tracked tickers |

Tickers arrive already uppercased, trimmed and format-validated (PLAN.md Section 8). That is the API layer's job, not the source's.

## 6. Factory — `factory.py`

```python
"""Select the market data source from the environment."""

import os

from .base import MarketDataSource
from .cache import PriceCache


def create_market_data_source(cache: PriceCache) -> MarketDataSource:
    """Massive if MASSIVE_API_KEY is set and non-empty, otherwise the simulator."""
    api_key = os.getenv("MASSIVE_API_KEY", "").strip()
    if api_key:
        from .massive_client import MassiveDataSource

        return MassiveDataSource(cache, api_key)
    from .simulator import SimulatorDataSource

    return SimulatorDataSource(cache)
```

The imports are lazy, so the simulator path never imports `massive`. Call `load_dotenv()` before this runs (local runs). In Docker the variables come from `--env-file`.

## 7. Massive Implementation — `massive_client.py`

```python
"""Market data source backed by the Massive (formerly Polygon.io) REST API."""

import asyncio
import logging
from datetime import date, timedelta

from massive import RESTClient
from massive.exceptions import BadResponse

from .base import MarketDataSource
from .cache import PriceCache

logger = logging.getLogger(__name__)


def snapshot_price(snap) -> float | None:
    """Best available price from a TickerSnapshot: last trade, then minute, day, previous day."""
    if snap.last_trade and snap.last_trade.price:
        return snap.last_trade.price
    for bar in (snap.min, snap.day, snap.prev_day):
        if bar and bar.close:
            return bar.close
    return None


class MassiveDataSource(MarketDataSource):
    """Polls Massive for all tracked tickers and writes prices to the cache.

    Paid plans use the multi-ticker snapshot (one call per poll). The free plan has
    no snapshots, so it falls back to end-of-day prices from grouped daily bars.
    """

    def __init__(self, cache: PriceCache, api_key: str, poll_interval: float = 15.0) -> None:
        self._cache = cache
        self._client = RESTClient(api_key=api_key)
        self._poll_interval = poll_interval
        self._tickers: set[str] = set()
        self._task: asyncio.Task | None = None
        self._snapshots_allowed = True

    async def start(self, tickers: list[str]) -> None:
        self._tickers = set(tickers)
        await self._poll_once()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def add_ticker(self, ticker: str) -> None:
        if ticker in self._tickers:
            return
        price = await asyncio.to_thread(self._fetch_single, ticker)
        self._tickers.add(ticker)
        self._cache.update(ticker, price)

    async def remove_ticker(self, ticker: str) -> None:
        self._tickers.discard(ticker)
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return sorted(self._tickers)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._poll_interval)
            try:
                await self._poll_once()
            except Exception:
                logger.exception("Massive poll failed; retrying next interval")

    async def _poll_once(self) -> None:
        if not self._tickers:
            return
        prices = await asyncio.to_thread(self._fetch_prices, sorted(self._tickers))
        for ticker, price in prices.items():
            if ticker in self._tickers:
                self._cache.update(ticker, price)

    def _fetch_prices(self, tickers: list[str]) -> dict[str, float]:
        if self._snapshots_allowed:
            try:
                snaps = self._client.get_snapshot_all("stocks", tickers=tickers)
                prices = {s.ticker: snapshot_price(s) for s in snaps}
                return {t: p for t, p in prices.items() if p is not None}
            except BadResponse as e:
                if "NOT_AUTHORIZED" not in str(e):
                    raise
                logger.info("Snapshots not in plan; using end-of-day grouped daily bars")
                self._snapshots_allowed = False
        return self._fetch_eod(set(tickers))

    def _fetch_eod(self, wanted: set[str]) -> dict[str, float]:
        day = date.today()
        for _ in range(5):
            bars = self._client.get_grouped_daily_aggs(day.isoformat())
            if bars:
                return {b.ticker: b.close for b in bars if b.ticker in wanted}
            day -= timedelta(days=1)
        return {}

    def _fetch_single(self, ticker: str) -> float:
        try:
            if self._snapshots_allowed:
                price = snapshot_price(self._client.get_snapshot_ticker("stocks", ticker))
            else:
                price = self._previous_close(ticker)
        except BadResponse as e:
            raise ValueError(f"Unknown ticker {ticker}") from e
        if price is None:
            raise ValueError(f"Unknown ticker {ticker}")
        return price

    def _previous_close(self, ticker: str) -> float | None:
        bars = self._client.get_previous_close_agg(ticker)  # [] for an unknown ticker
        return bars[0].close if bars else None
```

How it works:

- **Paid plans:** each poll makes one `get_snapshot_all` call for all tracked tickers. The price is the first available of the last trade, the minute close, the day close and the previous close.
- **Free plan:** the first snapshot call returns 403 `NOT_AUTHORIZED`. The source logs it once, switches to `get_grouped_daily_aggs` (one call returns every US stock's end-of-day bar), and walks back over weekends and holidays. Prices then stay flat during the session, which is expected for end-of-day data.
- **Poll interval:** 15 s, which is 4 calls/min. That fits the free tier's 5 calls/min and leaves room for one `add_ticker` each minute. Paid users can lower `poll_interval`.
- **Failures:** the client already retries 429 and 5xx. A poll that still fails is logged and the next one retries; the last prices stay in the cache.
- **`add_ticker`** uses a single-ticker snapshot (paid) or previous close (free). `BadResponse` or an empty result raises `ValueError`, which becomes a 400 "Unknown ticker X".
- The API key is passed explicitly, because the client's default reads the environment at import time (MASSIVE_API.md, Gotcha 1).

## 8. Using It

### 8.1 Lifespan (`main.py`)

```python
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from app.market import PriceCache, create_market_data_source

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    cache = PriceCache()
    source = create_market_data_source(cache)
    await source.start(tracked_tickers())  # watchlist ∪ positions, from the DB
    app.state.price_cache = cache
    app.state.market_source = source
    snapshot_task = start_snapshot_task(cache)
    yield
    snapshot_task.cancel()
    await source.stop()
```

Route handlers get them through small dependencies:

```python
from fastapi import Request


def get_price_cache(request: Request) -> PriceCache:
    return request.app.state.price_cache


def get_market_source(request: Request) -> MarketDataSource:
    return request.app.state.market_source
```

### 8.2 SSE stream (`stream.py`)

```python
import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

router = APIRouter()


async def price_events(request: Request, cache: PriceCache):
    """Yield one SSE event holding every ticker whenever the cache changes."""
    yield "retry: 1000\n\n"
    last_version = -1
    while not await request.is_disconnected():
        if cache.version != last_version:
            last_version = cache.version
            payload = {t: u.to_dict() for t, u in cache.get_all().items()}
            yield f"data: {json.dumps(payload)}\n\n"
        await asyncio.sleep(0.5)


@router.get("/api/stream/prices")
async def stream_prices(request: Request, cache: PriceCache = Depends(get_price_cache)):
    return StreamingResponse(
        price_events(request, cache),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

### 8.3 Keeping the tracked set equal to `watchlist ∪ positions`

The tracked-ticker rules (PLAN.md Section 6) live in the API/service layer:

```python
# POST /api/watchlist
await source.add_ticker(ticker)          # ValueError -> 400 "Unknown ticker X"
db_add_watchlist(ticker)                 # only after the source accepted it

# DELETE /api/watchlist/{ticker}
db_remove_watchlist(ticker)
if not db_has_position(ticker):
    await source.remove_ticker(ticker)

# after a sell that closes a position
if not db_on_watchlist(ticker):
    await source.remove_ticker(ticker)
```

A buy needs a cached price, and a ticker only has one if it is tracked. The LLM's "add then buy" works because watchlist changes run before trades (PLAN.md Section 9).

### 8.4 Reading prices elsewhere

```python
price = cache.get_price("AAPL")                          # trade fill, or None
live = {t: u.price for t, u in cache.get_all().items()}  # portfolio valuation, LLM context
```

## 9. Testing

- **Cache:** rounding, the first price is flat, an unchanged price does not bump `version`, and `remove` bumps `version`.
- **`PriceUpdate`:** `change`, `change_percent` and `direction`, including `previous_price == 0`.
- **Factory:** an unset, empty or whitespace key selects the simulator, and a key selects Massive (use `monkeypatch.setenv`).
- **Massive:** replace methods on `source._client` with fakes built from the client's own models (`TickerSnapshot.from_dict(...)`, `GroupedDailyAgg.from_dict(...)`). Cover the paid price order, the fallback after `BadResponse('{"status":"NOT_AUTHORIZED"}')`, walking back over empty days, an unknown ticker raising `ValueError` and leaving the tracked set unchanged, and dropping prices for tickers not tracked. Never call the live API in tests.
- **Interface conformance:** a parametrized test runs the same `start / add / remove / get_tickers / stop` scenario against both sources.
