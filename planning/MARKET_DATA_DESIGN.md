# Market Data Backend — Detailed Design

Status: design, ready to implement. Owner: Backend / Market Data agent.
Source of truth for requirements: `planning/PLAN.md` (Sections 3, 6, 8, 12). This document turns those requirements into concrete modules, interfaces and code. Where this document and PLAN.md disagree, PLAN.md wins; please fix this document.

---

## 1. Scope

This document covers everything between "a price exists somewhere" and "the browser receives an SSE event":

1. **Unified interface** — `MarketDataSource`, the abstract contract both implementations satisfy.
2. **PriceCache** — the single in-memory store of latest prices that everything downstream reads.
3. **Simulator** — GBM with correlated moves and random events (default).
4. **Massive client** — REST polling of the Massive (formerly Polygon.io) snapshot API (when `MASSIVE_API_KEY` is set).
5. **Factory** — env-driven selection.
6. **SSE endpoint** — `GET /api/stream/prices`.
7. **Ticker normalization and tracked-ticker rules** — `watchlist ∪ positions`.
8. **Lifespan wiring**.
9. **Tests**.

Out of scope: trade execution, portfolio math, LLM. They only *consume* this layer through `PriceCache.get_price()` and `MarketDataSource.add_ticker()/remove_ticker()`.

---

## 2. Module Layout

```
backend/
├── pyproject.toml
└── app/
    ├── main.py                    # FastAPI app + lifespan (Section 10)
    ├── tickers.py                 # normalize_ticker / validation (Section 8)
    └── market/
        ├── __init__.py            # re-exports the public API
        ├── models.py              # PriceUpdate dataclass
        ├── cache.py               # PriceCache
        ├── interface.py           # MarketDataSource ABC
        ├── seed.py                # seed prices, volatilities, sectors
        ├── simulator.py           # SimulatorDataSource (GBM)
        ├── massive.py             # MassiveDataSource (REST poller)
        ├── factory.py             # create_market_data_source()
        ├── tracking.py            # watchlist ∪ positions helpers
        └── stream.py              # SSE router: /api/stream/prices
    └── tests/market/
        ├── test_cache.py
        ├── test_simulator.py
        ├── test_massive.py
        ├── test_factory.py
        ├── test_interface_conformance.py
        └── test_stream.py
```

Dependencies (add with `uv add`):

```bash
uv add fastapi "uvicorn[standard]" httpx python-dotenv
uv add --dev pytest pytest-asyncio
```

No `numpy`: the simulator needs only a handful of Gaussian draws per tick, which `random.gauss` covers. The Massive client uses `httpx` directly instead of the `massive` SDK. The reasons:

- it is async-native, so no thread pool is needed;
- `httpx.MockTransport` makes it trivial to test;
- we only call two endpoints;
- it avoids dependency churn from the Polygon → Massive SDK rename.

Configure pytest-asyncio once in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["app/tests"]
```

---

## 3. Data Model — `PriceUpdate`

`app/market/models.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Direction = Literal["up", "down", "flat"]


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Latest known price for one ticker. Immutable; the cache replaces it on each tick."""

    ticker: str
    price: float            # rounded to 2 decimals
    previous_price: float   # price before this update (== price for the first update)
    timestamp: float        # Unix seconds (float)

    @property
    def change(self) -> float:
        return round(self.price - self.previous_price, 2)

    @property
    def change_percent(self) -> float:
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def direction(self) -> Direction:
        if self.price > self.previous_price:
            return "up"
        if self.price < self.previous_price:
            return "down"
        return "flat"

    def to_dict(self) -> dict:
        """Exact SSE payload shape from PLAN.md Section 6."""
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

`change`, `change_percent` and `direction` are relative to the **previous tick**, not the trading day (PLAN.md §6).

---

## 4. `PriceCache`

`app/market/cache.py`

Responsibilities:

- holds one `PriceUpdate` per tracked ticker;
- rounds prices to 2 decimals on write;
- keeps a monotonically increasing `version` that bumps **only when something visible changed**, so the SSE loop can cheaply answer "did the cache change?";
- is the only object trade execution and `/api/watchlist` read prices from.

All writers run on the asyncio event loop, so there is no real contention. The lock exists so a future threaded writer, such as a sync SDK in a thread pool, stays safe. It is uncontended and costs nanoseconds.

```python
from __future__ import annotations

import threading
import time

from .models import PriceUpdate


class PriceCache:
    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._lock = threading.Lock()
        self._version = 0

    # ---- writes -----------------------------------------------------------

    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate:
        """Record a new price. previous_price is the last cached price (or the same price
        for the first update). Bumps `version` only if price or timestamp changed."""
        price = round(float(price), 2)
        ts = time.time() if timestamp is None else float(timestamp)
        with self._lock:
            prev = self._prices.get(ticker)
            if prev is not None and prev.price == price and prev.timestamp == ts:
                return prev  # nothing visible changed (common for Massive outside market hours)
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
                self._version += 1  # the next SSE event no longer contains the ticker

    # ---- reads ------------------------------------------------------------

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
        return ticker in self._prices

    def __len__(self) -> int:
        return len(self._prices)
```

Usage:

```python
cache = PriceCache()
cache.update("AAPL", 190.4213)           # price=190.42, previous_price=190.42, direction="flat"
cache.update("AAPL", 190.5)              # price=190.5, previous_price=190.42, direction="up"
cache.get_price("AAPL")                  # 190.5
cache.get_price("ZZZZ")                  # None -> trade service returns 400 "No price yet for ZZZZ"
```

---

## 5. Unified Interface — `MarketDataSource`

`app/market/interface.py`

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from .cache import PriceCache


class MarketDataSource(ABC):
    """Produces prices for a set of tracked tickers and writes them into a PriceCache.

    Contract (both implementations, verified by test_interface_conformance.py):
      * Tickers passed in are already normalized (uppercase, trimmed, valid). See tickers.py.
      * start() begins background production; it returns once the source is running.
        After start() returns, every ticker passed to it SHOULD have a price in the cache
        (the simulator guarantees it; Massive guarantees it if the first poll succeeds).
      * add_ticker() is idempotent. On success, the ticker has a price in the cache
        before the call returns, so "add and buy" works in one chat turn.
        Raises ValueError if the source does not know the symbol (Massive only).
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
```

Why async methods: Massive's `add_ticker` makes an HTTP call, and the simulator's version simply doesn't await anything. One signature for both keeps the callers (`tracking.py`, routes, LLM actions) source-agnostic.

---

## 6. Simulator

### 6.1 Seed data — `app/market/seed.py`

```python
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TickerProfile:
    seed_price: float
    volatility: float   # annualized sigma
    drift: float        # annualized mu
    sector: str


# Realistic starting points for the default watchlist (PLAN.md §7) plus a few common extras.
PROFILES: dict[str, TickerProfile] = {
    "AAPL":  TickerProfile(190.00, 0.25, 0.08, "tech"),
    "GOOGL": TickerProfile(175.00, 0.28, 0.08, "tech"),
    "MSFT":  TickerProfile(420.00, 0.24, 0.08, "tech"),
    "AMZN":  TickerProfile(185.00, 0.32, 0.09, "tech"),
    "META":  TickerProfile(500.00, 0.38, 0.10, "tech"),
    "NVDA":  TickerProfile(880.00, 0.50, 0.15, "semis"),
    "NFLX":  TickerProfile(620.00, 0.40, 0.08, "tech"),
    "TSLA":  TickerProfile(250.00, 0.60, 0.05, "auto"),
    "JPM":   TickerProfile(195.00, 0.20, 0.06, "finance"),
    "V":     TickerProfile(280.00, 0.18, 0.06, "finance"),
    "AMD":   TickerProfile(160.00, 0.50, 0.12, "semis"),
    "INTC":  TickerProfile( 35.00, 0.40, 0.00, "semis"),
    "PYPL":  TickerProfile( 65.00, 0.40, 0.03, "finance"),
    "BAC":   TickerProfile( 38.00, 0.25, 0.05, "finance"),
    "DIS":   TickerProfile(110.00, 0.30, 0.04, "media"),
}

DEFAULT_VOLATILITY = 0.35
DEFAULT_DRIFT = 0.05
DEFAULT_SECTOR = "other"


def profile_for(ticker: str, rng: random.Random) -> TickerProfile:
    """Known tickers get their profile; unknown ones get a random but plausible one."""
    if ticker in PROFILES:
        return PROFILES[ticker]
    return TickerProfile(
        seed_price=round(rng.uniform(20.0, 400.0), 2),
        volatility=DEFAULT_VOLATILITY,
        drift=DEFAULT_DRIFT,
        sector=DEFAULT_SECTOR,
    )
```

### 6.2 The math

**GBM step.** For each ticker *i*, with time step Δt (in years):

```
S_{t+Δt} = S_t · exp( (μ − σ²/2)·Δt + σ·√Δt·Z_i )
```

**Time scale.** At real speed, 0.5 s is Δt = 0.5 / (252 · 6.5 · 3600) ≈ 8.5e-8 years. That gives σ√Δt ≈ 0.007% per tick for σ = 0.25, which is about 1 cent on AAPL. That is too sleepy for a demo, so a `time_scale` multiplier (default **50**) speeds up simulated time:

| σ (annual) | per-tick move (time_scale=50) | AAPL @ $190 | 10-min session (1200 ticks) |
|---|---|---|---|
| 0.25 | ~0.052% | ~$0.10 | ~1.8% std |
| 0.60 (TSLA) | ~0.125% | ~$0.31 on $250 | ~4.3% std |

**Correlation via a factor model.** It needs no matrix and no Cholesky, and each Z_i stays exactly N(0,1):

```
Z_i = β_m·M + β_s·F_sector(i) + √(1 − β_m² − β_s²)·ε_i      M, F_s, ε_i ~ iid N(0,1)
```

With β_m = 0.5 and β_s = 0.5:

- corr(AAPL, MSFT), same sector: β_m² + β_s² = **0.5**
- corr(AAPL, JPM), different sectors: β_m² = **0.25**
- tickers in sector `"other"` load only on the market factor, plus a larger ε, so their correlation is 0.25.

**Random events.** On each tick, each ticker independently has probability `event_probability` (default 0.0005) of a jump. A jump multiplies the price by `1 ± U(0.02, 0.05)`, with the sign chosen 50/50. With 10 tickers at 2 ticks/s, that is about one event every 100 s across the watchlist, which is enough drama without chaos.

**Precision.** The simulator keeps a full-precision internal price per ticker and writes the rounded value to the cache. If it fed the rounded value back into GBM, low-priced tickers would get stuck, because a move under half a cent rounds to zero every time. A floor of $0.01 prevents prices from going to zero.

### 6.3 Implementation — `app/market/simulator.py`

```python
from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from collections.abc import Iterable

from .cache import PriceCache
from .interface import MarketDataSource
from .seed import TickerProfile, profile_for

log = logging.getLogger(__name__)

TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600  # 5,896,800
MIN_PRICE = 0.01


class SimulatorDataSource(MarketDataSource):
    def __init__(
        self,
        cache: PriceCache,
        *,
        tick_interval: float = 0.5,
        time_scale: float = 50.0,
        market_beta: float = 0.5,
        sector_beta: float = 0.5,
        event_probability: float = 0.0005,
        event_range: tuple[float, float] = (0.02, 0.05),
        seed: int | None = None,
    ) -> None:
        super().__init__(cache)
        if market_beta**2 + sector_beta**2 >= 1:
            raise ValueError("market_beta² + sector_beta² must be < 1")
        self.tick_interval = tick_interval
        self.dt = tick_interval * time_scale / TRADING_SECONDS_PER_YEAR
        self.market_beta = market_beta
        self.sector_beta = sector_beta
        self.event_probability = event_probability
        self.event_range = event_range
        self.rng = random.Random(seed)

        self._profiles: dict[str, TickerProfile] = {}
        self._prices: dict[str, float] = {}   # full precision, never rounded
        self._task: asyncio.Task | None = None

    # ---- MarketDataSource -------------------------------------------------

    async def start(self, tickers: Iterable[str]) -> None:
        for t in tickers:
            self._track(t)
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="market-simulator")
        log.info("Simulator started with %d tickers", len(self._prices))

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def add_ticker(self, ticker: str) -> None:
        self._track(ticker)  # the simulator accepts any well-formed symbol

    async def remove_ticker(self, ticker: str) -> None:
        self._profiles.pop(ticker, None)
        self._prices.pop(ticker, None)
        self.cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return sorted(self._prices)

    # ---- internals --------------------------------------------------------

    def _track(self, ticker: str) -> None:
        if ticker in self._prices:
            return
        profile = profile_for(ticker, self.rng)
        self._profiles[ticker] = profile
        self._prices[ticker] = profile.seed_price
        self.cache.update(ticker, profile.seed_price)  # price available immediately

    async def _run(self) -> None:
        while True:
            try:
                self.step()
            except Exception:  # never let one bad tick kill the feed
                log.exception("Simulator step failed")
            await asyncio.sleep(self.tick_interval)

    def step(self, now: float | None = None) -> None:
        """Advance every tracked ticker by one tick and write to the cache.
        Public and synchronous so tests can drive it deterministically."""
        if not self._prices:
            return
        now = time.time() if now is None else now
        gauss = self.rng.gauss

        market = gauss(0.0, 1.0)
        sectors: dict[str, float] = {}
        idio_weight = math.sqrt(1 - self.market_beta**2 - self.sector_beta**2)
        sqrt_dt = math.sqrt(self.dt)

        for ticker, price in list(self._prices.items()):
            p = self._profiles[ticker]
            if p.sector == "other":
                # no sector peers: put the sector weight into the idiosyncratic term
                z = self.market_beta * market + math.sqrt(1 - self.market_beta**2) * gauss(0.0, 1.0)
            else:
                if p.sector not in sectors:
                    sectors[p.sector] = gauss(0.0, 1.0)
                z = (
                    self.market_beta * market
                    + self.sector_beta * sectors[p.sector]
                    + idio_weight * gauss(0.0, 1.0)
                )

            sigma, mu = p.volatility, p.drift
            new_price = price * math.exp((mu - 0.5 * sigma**2) * self.dt + sigma * sqrt_dt * z)

            if self.rng.random() < self.event_probability:
                jump = self.rng.uniform(*self.event_range)
                new_price *= 1 + jump if self.rng.random() < 0.5 else 1 - jump
                log.debug("Simulator event: %s %+.1f%%", ticker, (new_price / price - 1) * 100)

            new_price = max(new_price, MIN_PRICE)
            self._prices[ticker] = new_price
            self.cache.update(ticker, new_price, now)
```

Example:

```python
cache = PriceCache()
sim = SimulatorDataSource(cache, seed=42)
await sim.start(["AAPL", "GOOGL", "PYPL"])
cache.get("AAPL")
# PriceUpdate(ticker='AAPL', price=190.0, previous_price=190.0, timestamp=1792839000.12)
await sim.add_ticker("ZZZT")        # unknown -> random seed price in [20, 400]
await asyncio.sleep(1.1)            # ~2 ticks
cache.get("AAPL").to_dict()
# {'ticker': 'AAPL', 'price': 190.07, 'previous_price': 189.98, 'timestamp': ..., 'change': 0.09,
#  'change_percent': 0.0474, 'direction': 'up'}
await sim.stop()
```

---

## 7. Massive API Client

### 7.1 API facts we rely on

Massive is Polygon.io under a new name. The same REST API is served at `https://api.massive.com`, and `api.polygon.io` keeps working.

| Item | Value |
|---|---|
| Base URL | `https://api.massive.com` |
| Auth | `Authorization: Bearer <MASSIVE_API_KEY>` header (the `?apiKey=` query param also works; we use the header so the key never appears in logged URLs) |
| Multi-ticker snapshot | `GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT,...` — **one call for all tracked tickers** |
| Single-ticker snapshot | `GET /v2/snapshot/locale/us/markets/stocks/tickers/{TICKER}` — used by `add_ticker` |
| Unknown ticker | single-ticker endpoint returns **404** (`{"status":"NOT_FOUND", ...}`) |
| Rate limit exceeded | **429** |
| Not on your plan | **403** (`{"status":"NOT_AUTHORIZED", ...}`) |
| Daily reset | snapshot data clears at ~3:30 AM ET and refills as trades arrive (fall back to `prevDay.c`) |
| Free tier | 5 calls/min → poll every 15 s (4 calls/min, leaving headroom for `add_ticker`) |

Multi-ticker response (fields we use are marked ←; timestamps are **nanoseconds**):

```json
{
  "status": "OK",
  "count": 2,
  "tickers": [
    {
      "ticker": "AAPL",                                   // ←
      "todaysChange": 1.53,
      "todaysChangePerc": 0.81,
      "updated": 1792839000123456789,                     // ← fallback timestamp (ns)
      "day":     {"o": 189.1, "h": 191.2, "l": 188.7, "c": 190.48, "v": 41234567, "vw": 190.1},
      "min":     {"o": 190.4, "h": 190.6, "l": 190.3, "c": 190.5,  "v": 120345, "t": 1792838940000},
      "prevDay": {"o": 187.0, "h": 189.4, "l": 186.5, "c": 188.97, "v": 52345678, "vw": 188.2},
      "lastTrade": {"p": 190.5, "s": 100, "t": 1792839000123456789, "x": 4},   // ← p = price, t = ns
      "lastQuote": {"P": 190.51, "S": 2, "p": 190.49, "s": 3, "t": 1792839000100000000}
    }
  ]
}
```

Single-ticker response: same object under `"ticker"` instead of a `"tickers"` list:

```json
{"status": "OK", "request_id": "…", "ticker": {"ticker": "AAPL", "lastTrade": {"p": 190.5, "t": 1792839000123456789}, "...": "..."}}
```

> **Verify before relying on it (open risk).** The Massive docs could not be fetched from the design environment, so the table above comes from the long-stable Polygon v2 API, not a fresh read. Two things to confirm with a real key:
> 1. The response shape:
>    ```bash
>    curl -s -H "Authorization: Bearer $MASSIVE_API_KEY" "https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL" | head -c 600
>    ```
> 2. Whether the **free** plan includes snapshot endpoints. Massive's free tier is centered on end-of-day data. If the call returns 403 `NOT_AUTHORIZED`, the client logs one clear error telling the user to remove `MASSIVE_API_KEY` (to use the simulator) or upgrade. It does **not** silently switch to the simulator, because a user who set a key expects real data.

### 7.2 Price extraction rule

Pick the first available, in order:

1. `lastTrade.p` (with `lastTrade.t` ns → s)
2. `min.c` (minute bar close, with `min.t` ms → s)
3. `day.c`
4. `prevDay.c` (after the 3:30 AM reset or before the open)

For 3 and 4, the timestamp is `updated` (ns → s), or `time.time()` if that is missing. If none of the four prices is present and positive, the ticker has no usable price and is skipped (in `add_ticker`, it raises `ValueError`).

### 7.3 Implementation — `app/market/massive.py`

```python
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable
from typing import Any

import httpx

from .cache import PriceCache
from .interface import MarketDataSource

log = logging.getLogger(__name__)

BASE_URL = "https://api.massive.com"
SNAPSHOT_PATH = "/v2/snapshot/locale/us/markets/stocks/tickers"
MAX_TICKERS_PER_REQUEST = 250
NS_PER_S = 1_000_000_000


class MassiveAuthError(RuntimeError):
    """403/401 — key invalid or plan lacks snapshot access."""


def parse_snapshot(item: dict[str, Any]) -> tuple[str, float, float] | None:
    """Return (ticker, price, unix_seconds) from one snapshot object, or None if unusable."""
    ticker = item.get("ticker")
    if not ticker:
        return None

    last_trade = item.get("lastTrade") or {}
    if (p := last_trade.get("p")) and p > 0:
        t = last_trade.get("t")
        return ticker, float(p), t / NS_PER_S if t else time.time()

    minute = item.get("min") or {}
    if (c := minute.get("c")) and c > 0:
        t = minute.get("t")  # milliseconds
        return ticker, float(c), t / 1000 if t else time.time()

    updated = item.get("updated")
    ts = updated / NS_PER_S if updated else time.time()
    for bar in ("day", "prevDay"):
        if (c := (item.get(bar) or {}).get("c")) and c > 0:
            return ticker, float(c), ts
    return None


class MassiveDataSource(MarketDataSource):
    def __init__(
        self,
        cache: PriceCache,
        api_key: str,
        *,
        poll_interval: float = 15.0,
        base_url: str = BASE_URL,
        client: httpx.AsyncClient | None = None,   # inject a MockTransport client in tests
        timeout: float = 10.0,
    ) -> None:
        super().__init__(cache)
        self.poll_interval = poll_interval
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self._client.headers["Authorization"] = f"Bearer {api_key}"  # also on injected clients
        self._owns_client = client is None
        self._tickers: set[str] = set()
        self._task: asyncio.Task | None = None
        self._backoff_until = 0.0

    # ---- MarketDataSource -------------------------------------------------

    async def start(self, tickers: Iterable[str]) -> None:
        self._tickers.update(tickers)
        try:
            await self.poll_once()  # prices available as soon as startup finishes
        except MassiveAuthError as exc:
            log.error("%s", exc)    # keep running: the app is usable, prices just stay empty
        except httpx.HTTPError as exc:
            log.warning("Initial Massive poll failed: %s", exc)
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="massive-poller")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._owns_client:
            await self._client.aclose()

    async def add_ticker(self, ticker: str) -> None:
        if ticker in self._tickers:
            return
        try:
            resp = await self._client.get(f"{SNAPSHOT_PATH}/{ticker}")
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Market data unavailable: {exc}") from exc
        if resp.status_code == 404:
            raise ValueError(f"Unknown ticker {ticker}")
        self._raise_for_status(resp)
        parsed = parse_snapshot(resp.json().get("ticker") or {})
        if parsed is None:
            raise ValueError(f"Unknown ticker {ticker}")
        _, price, ts = parsed
        self.cache.update(ticker, price, ts)   # seed before tracking -> "add and buy" works
        self._tickers.add(ticker)

    async def remove_ticker(self, ticker: str) -> None:
        self._tickers.discard(ticker)
        self.cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return sorted(self._tickers)

    # ---- polling ----------------------------------------------------------

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.poll_interval)
            if time.monotonic() < self._backoff_until:
                continue
            try:
                await self.poll_once()
            except MassiveAuthError as exc:
                log.error("%s", exc)
                self._backoff_until = time.monotonic() + 300  # don't hammer a 403
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    log.warning("Massive rate limit hit; backing off 60 s")
                    self._backoff_until = time.monotonic() + 60
                else:
                    log.warning("Massive poll failed: %s", exc)
            except httpx.HTTPError as exc:
                log.warning("Massive poll failed: %s", exc)
            except Exception:
                log.exception("Unexpected error in Massive poller")

    async def poll_once(self) -> int:
        """Fetch all tracked tickers and write to the cache. Returns the number updated.
        Existing cache entries are kept on failure (stale beats empty)."""
        tickers = sorted(self._tickers)
        updated = 0
        for i in range(0, len(tickers), MAX_TICKERS_PER_REQUEST):
            chunk = tickers[i : i + MAX_TICKERS_PER_REQUEST]
            resp = await self._client.get(SNAPSHOT_PATH, params={"tickers": ",".join(chunk)})
            self._raise_for_status(resp)
            for item in resp.json().get("tickers") or []:
                parsed = parse_snapshot(item)
                # ignore tickers removed while the request was in flight
                if parsed and parsed[0] in self._tickers:
                    self.cache.update(*parsed)
                    updated += 1
        return updated

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code in (401, 403):
            raise MassiveAuthError(
                f"Massive rejected the request ({resp.status_code}): the API key is invalid or "
                "your plan does not include stock snapshots. Remove MASSIVE_API_KEY to use the "
                "simulator, or upgrade your Massive plan."
            )
        resp.raise_for_status()
```

Behavioral notes:

- **Cache changes only on real changes.** Outside market hours, consecutive polls return the same `lastTrade`, so `PriceCache.update` is a no-op and the SSE stream stays quiet (a heartbeat keeps it alive, §9).
- **`add_ticker` errors.** `ValueError` → route returns 400 `"Unknown ticker X"`. `ConnectionError` → route returns 503 `"Market data unavailable"`. `MassiveAuthError` → 503 as well, with the message.
- **Budget.** At `poll_interval=15`, polling uses 4 of the 5 free calls per minute. Each `add_ticker` costs one call. Bursts of adds can trigger 429, which `add_ticker` surfaces as an HTTP error the route maps to 503. That is acceptable for a demo.

---

## 8. Ticker Normalization — `app/tickers.py`

Every endpoint and LLM action calls this **before** touching the data source (PLAN.md §8 conventions).

```python
import re

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def normalize_ticker(raw: str) -> str:
    """Uppercase + trim, then validate. Raises ValueError (-> HTTP 400) if malformed."""
    ticker = (raw or "").strip().upper()
    if not TICKER_RE.fullmatch(ticker):
        raise ValueError(f"Invalid ticker {raw!r}")
    return ticker
```

```python
normalize_ticker(" brk.b ")  # "BRK.B"
normalize_ticker("aapl")     # "AAPL"
normalize_ticker("1ABC")     # ValueError (must start with a letter)
normalize_ticker("TOOLONGTICK")  # ValueError (11 chars)
```

---

## 9. SSE Endpoint — `app/market/stream.py`

Wire format, per PLAN.md §6:

- The first frame is `retry: 1000`, so the browser reconnects after 1 s.
- Every ~500 ms, **if `cache.version` changed**, send one `data:` event holding **every** tracked ticker.
- A newly connected client gets the current snapshot immediately.
- A comment line (`: ping`) every 15 s with no changes keeps proxies and load balancers from closing an idle stream. This matters in Massive mode, where prices can sit still for minutes.

```python
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache

router = APIRouter(prefix="/api/stream", tags=["stream"])

PUSH_INTERVAL = 0.5
HEARTBEAT_INTERVAL = 15.0


def format_event(cache: PriceCache) -> str:
    payload = {t: u.to_dict() for t, u in sorted(cache.snapshot().items())}
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


async def price_events(
    cache: PriceCache,
    request: Request | None = None,
    *,
    interval: float = PUSH_INTERVAL,
) -> AsyncIterator[str]:
    yield "retry: 1000\n\n"
    last_version = -1
    last_sent = time.monotonic()
    while True:
        if request is not None and await request.is_disconnected():
            return
        version = cache.version
        if version != last_version:
            last_version = version
            yield format_event(cache)
            last_sent = time.monotonic()
        elif time.monotonic() - last_sent >= HEARTBEAT_INTERVAL:
            yield ": ping\n\n"
            last_sent = time.monotonic()
        await asyncio.sleep(interval)


@router.get("/prices")
async def stream_prices(request: Request) -> StreamingResponse:
    cache: PriceCache = request.app.state.price_cache
    return StreamingResponse(
        price_events(cache, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable buffering if ever behind nginx
        },
    )
```

Example stream as seen by `curl -N http://localhost:8000/api/stream/prices`:

```
retry: 1000

data: {"AAPL":{"ticker":"AAPL","price":190.5,"previous_price":190.42,"timestamp":1792839000.123,"change":0.08,"change_percent":0.042,"direction":"up"},"AMZN":{...},...}

data: {"AAPL":{"ticker":"AAPL","price":190.47,"previous_price":190.5,...,"direction":"down"},...}
```

Frontend consumption (for the Frontend agent's reference):

```ts
const es = new EventSource("/api/stream/prices");
es.onmessage = (e) => {
  const batch: Record<string, {ticker: string; price: number; previous_price: number; timestamp: number}> =
    JSON.parse(e.data);
  for (const u of Object.values(batch)) priceStore.push(u.ticker, u.price, u.timestamp);
};
// readyState: 0 CONNECTING = yellow, 1 OPEN = green, 2 CLOSED = red
```

Each event carries the **full set** of tracked tickers. A ticker missing from an event has been removed from tracking.

---

## 10. Tracked Tickers — `app/market/tracking.py`

The rule is **tracked = watchlist ∪ positions** (PLAN.md §6). The data source doesn't know about the database; these helpers are the only place the rule lives. They take the DB access functions as parameters, so they stay independent of the DB layer's final shape.

```python
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
```

How the callers use it:

**`POST /api/watchlist`**:
```python
ticker = normalize_ticker(body.ticker)                 # ValueError -> 400
if (existing := db.get_watchlist_entry(ticker)):       # idempotent: return existing entry
    return entry_response(existing, cache)
try:
    await track(source, ticker)                        # Massive: may raise ValueError
except ValueError as exc:
    raise HTTPException(400, str(exc))                 # "Unknown ticker X"
entry = db.add_watchlist(ticker)                       # only after the source accepted it
return entry_response(entry, cache)                    # price filled from cache
```

**`DELETE /api/watchlist/{ticker}`**:
```python
ticker = normalize_ticker(ticker)
if not db.remove_watchlist(ticker):
    raise HTTPException(404, f"{ticker} is not on the watchlist")
await untrack_if_unused(source, ticker, on_watchlist=False,
                        has_position=db.get_position(ticker) is not None)
return Response(status_code=204)
```

**Trade service, after a sell commits and the position row was deleted**:
```python
if position_closed:
    await untrack_if_unused(source, ticker,
                            on_watchlist=db.is_on_watchlist(ticker), has_position=False)
```

**Buying a ticker not on the watchlist.** This can't happen without a price: a buy requires `cache.get_price(ticker)` to be non-None, which implies the ticker is already tracked. The LLM's "add PYPL and buy it" works because watchlist changes run before trades (PLAN.md §9).

---

## 11. Factory and Lifespan

### 11.1 `app/market/factory.py`

```python
from __future__ import annotations

import logging
import os

from .cache import PriceCache
from .interface import MarketDataSource
from .massive import MassiveDataSource
from .simulator import SimulatorDataSource

log = logging.getLogger(__name__)


def create_market_data_source(cache: PriceCache, env: dict[str, str] | None = None) -> MarketDataSource:
    env = os.environ if env is None else env
    api_key = (env.get("MASSIVE_API_KEY") or "").strip()
    if api_key:
        interval = float(env.get("MASSIVE_POLL_INTERVAL") or 15)
        log.info("Market data: Massive REST API (poll every %.0f s)", interval)
        return MassiveDataSource(cache, api_key, poll_interval=interval)
    log.info("Market data: built-in simulator")
    return SimulatorDataSource(cache)
```

`MASSIVE_POLL_INTERVAL` is an **optional** new variable: seconds between polls, default 15 (free tier). Paid tiers can use 2–5. Add it to `.env.example` as `MASSIVE_POLL_INTERVAL=` and to PLAN.md §5 when implementing.

### 11.2 `app/market/__init__.py`

```python
from .cache import PriceCache
from .factory import create_market_data_source
from .interface import MarketDataSource
from .massive import MassiveDataSource
from .models import PriceUpdate
from .simulator import SimulatorDataSource
from .stream import router as stream_router
from .tracking import track, untrack_if_unused

__all__ = [
    "PriceCache", "PriceUpdate", "MarketDataSource", "SimulatorDataSource",
    "MassiveDataSource", "create_market_data_source", "stream_router",
    "track", "untrack_if_unused",
]
```

### 11.3 Lifespan wiring in `app/main.py` (PLAN.md §3 startup sequence)

```python
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.market import PriceCache, create_market_data_source, stream_router
from app import db
from app.portfolio import snapshot_loop          # owned by the portfolio module
from app.routes import api_routers               # portfolio, watchlist, chat, health

load_dotenv(Path(__file__).resolve().parents[2] / ".env")  # project-root .env for local runs


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()                                                   # 1. tables + seed
    tickers = sorted(set(db.list_watchlist()) | set(db.list_position_tickers()))  # 2.
    cache = PriceCache()                                           # 3.
    source = create_market_data_source(cache)
    await source.start(tickers)                                    # 4.
    app.state.price_cache = cache
    app.state.market_source = source
    snapshot_task = asyncio.create_task(snapshot_loop(app))        # 5.
    try:
        yield
    finally:
        snapshot_task.cancel()
        await source.stop()


app = FastAPI(title="FinAlly", lifespan=lifespan)
app.include_router(stream_router)                                  # 6.
for r in api_routers:
    app.include_router(r)

static_dir = Path("/app/static")
if static_dir.is_dir():                                            # 7. last, never shadows /api
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
```

Routers are registered at import time. FastAPI cannot add routes inside the lifespan, so steps 6 and 7 run when the module loads, which is before the lifespan starts. The ordering guarantee that matters, static files mounted last, still holds.

Route dependencies:

```python
from fastapi import Request

def get_cache(request: Request) -> PriceCache:
    return request.app.state.price_cache

def get_source(request: Request) -> MarketDataSource:
    return request.app.state.market_source
```

---

## 12. Tests

All tests run offline: the simulator is seeded, and Massive uses `httpx.MockTransport`.

### 12.1 Cache — `test_cache.py`

```python
from app.market import PriceCache


def test_first_update_is_flat_and_rounded():
    c = PriceCache()
    u = c.update("AAPL", 190.4251, 1.0)
    assert (u.price, u.previous_price, u.direction) == (190.43, 190.43, "flat")


def test_previous_price_and_direction():
    c = PriceCache()
    c.update("AAPL", 190.42, 1.0)
    u = c.update("AAPL", 190.50, 2.0)
    assert u.previous_price == 190.42 and u.direction == "up"
    assert u.change == 0.08 and u.change_percent == 0.042


def test_version_bumps_only_on_change():
    c = PriceCache()
    c.update("AAPL", 1.0, 1.0); v = c.version
    c.update("AAPL", 1.0, 1.0)
    assert c.version == v
    c.remove("AAPL")
    assert c.version == v + 1 and c.get_price("AAPL") is None
```

### 12.2 Simulator — `test_simulator.py`

```python
import math
import statistics

from app.market import PriceCache, SimulatorDataSource


async def test_start_seeds_prices_immediately():
    c = PriceCache()
    sim = SimulatorDataSource(c, seed=1)
    await sim.start(["AAPL", "ZZZT"])
    assert c.get_price("AAPL") == 190.0
    assert 20 <= c.get_price("ZZZT") <= 400
    await sim.stop()


def test_prices_stay_positive_and_rounded():
    c = PriceCache()
    sim = SimulatorDataSource(c, seed=2, time_scale=5000)
    sim._track("ZZZT")
    for _ in range(2000):
        sim.step()
    p = c.get_price("ZZZT")
    assert p >= 0.01 and round(p, 2) == p


def test_gbm_log_returns_match_sigma():
    c = PriceCache()
    sim = SimulatorDataSource(c, seed=3, event_probability=0.0)
    sim._track("AAPL")
    rets, prev = [], sim._prices["AAPL"]
    for _ in range(20_000):
        sim.step()
        cur = sim._prices["AAPL"]
        rets.append(math.log(cur / prev)); prev = cur
    expected = 0.25 * math.sqrt(sim.dt)
    assert abs(statistics.stdev(rets) / expected - 1) < 0.05


def test_same_sector_more_correlated_than_cross_sector():
    c = PriceCache()
    sim = SimulatorDataSource(c, seed=4, event_probability=0.0)
    for t in ("AAPL", "MSFT", "JPM"):
        sim._track(t)
    series = {t: [] for t in ("AAPL", "MSFT", "JPM")}
    prev = dict(sim._prices)
    for _ in range(5000):
        sim.step()
        for t in series:
            series[t].append(math.log(sim._prices[t] / prev[t]))
        prev = dict(sim._prices)
    same = statistics.correlation(series["AAPL"], series["MSFT"])
    cross = statistics.correlation(series["AAPL"], series["JPM"])
    assert 0.4 < same < 0.6 and 0.15 < cross < 0.35


def test_events_produce_big_jumps():
    c = PriceCache()
    sim = SimulatorDataSource(c, seed=5, event_probability=1.0)
    sim._track("AAPL")
    sim.step()
    assert abs(sim._prices["AAPL"] / 190.0 - 1) >= 0.019


async def test_remove_ticker_clears_cache():
    c = PriceCache()
    sim = SimulatorDataSource(c, seed=6)
    await sim.start(["AAPL"])
    await sim.remove_ticker("AAPL")
    assert "AAPL" not in c and sim.get_tickers() == []
    await sim.stop()
```

### 12.3 Massive — `test_massive.py`

```python
import httpx
import pytest

from app.market import MassiveDataSource, PriceCache
from app.market.massive import MassiveAuthError, parse_snapshot

NS = 1_000_000_000


def snap(ticker, price, t_s=1_792_839_000):
    return {"ticker": ticker, "lastTrade": {"p": price, "t": t_s * NS},
            "prevDay": {"c": price - 1}, "updated": t_s * NS}


def make_source(handler) -> tuple[MassiveDataSource, PriceCache]:
    client = httpx.AsyncClient(base_url="https://api.massive.com",
                               transport=httpx.MockTransport(handler))
    cache = PriceCache()
    return MassiveDataSource(cache, "test-key", client=client, poll_interval=999), cache


def test_parse_prefers_last_trade_then_falls_back():
    assert parse_snapshot(snap("AAPL", 190.5)) == ("AAPL", 190.5, 1_792_839_000.0)
    assert parse_snapshot({"ticker": "X", "prevDay": {"c": 10.0}, "updated": 5 * NS}) == ("X", 10.0, 5.0)
    assert parse_snapshot({"ticker": "X", "min": {"c": 11.0, "t": 6000}}) == ("X", 11.0, 6.0)
    assert parse_snapshot({"ticker": "X"}) is None


async def test_start_polls_all_tickers_in_one_call():
    calls = []

    def handler(req: httpx.Request):
        calls.append(req)
        assert req.headers["Authorization"] == "Bearer test-key"
        assert req.url.params["tickers"] == "AAPL,MSFT"
        return httpx.Response(200, json={"status": "OK",
                                         "tickers": [snap("AAPL", 190.5), snap("MSFT", 420.1)]})

    src, cache = make_source(handler)
    await src.start(["MSFT", "AAPL"])
    assert len(calls) == 1
    assert cache.get_price("AAPL") == 190.5 and cache.get_price("MSFT") == 420.1
    await src.stop()


async def test_add_ticker_seeds_cache():
    def handler(req):
        assert req.url.path.endswith("/tickers/PYPL")
        return httpx.Response(200, json={"status": "OK", "ticker": snap("PYPL", 65.2)})

    src, cache = make_source(handler)
    await src.add_ticker("PYPL")
    assert cache.get_price("PYPL") == 65.2 and "PYPL" in src.get_tickers()


async def test_add_unknown_ticker_raises_value_error():
    src, cache = make_source(lambda req: httpx.Response(404, json={"status": "NOT_FOUND"}))
    with pytest.raises(ValueError, match="Unknown ticker XXXX"):
        await src.add_ticker("XXXX")
    assert "XXXX" not in src.get_tickers() and "XXXX" not in cache


async def test_403_raises_auth_error():
    src, _ = make_source(lambda req: httpx.Response(403, json={"status": "NOT_AUTHORIZED"}))
    src._tickers = {"AAPL"}
    with pytest.raises(MassiveAuthError):
        await src.poll_once()


async def test_failed_poll_keeps_stale_prices():
    responses = iter([
        httpx.Response(200, json={"tickers": [snap("AAPL", 190.5)]}),
        httpx.Response(500),
    ])
    src, cache = make_source(lambda req: next(responses))
    await src.start(["AAPL"])
    with pytest.raises(httpx.HTTPStatusError):
        await src.poll_once()
    assert cache.get_price("AAPL") == 190.5
    await src.stop()
```

### 12.4 Interface conformance — `test_interface_conformance.py`

```python
import httpx
import pytest

from app.market import MarketDataSource, MassiveDataSource, PriceCache, SimulatorDataSource


def massive_factory(cache):
    def handler(req):
        if req.url.path.endswith("/tickers"):
            names = req.url.params["tickers"].split(",")
            return httpx.Response(200, json={"tickers": [
                {"ticker": n, "lastTrade": {"p": 100.0, "t": 1}} for n in names]})
        name = req.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"ticker": {"ticker": name, "lastTrade": {"p": 50.0, "t": 1}}})
    client = httpx.AsyncClient(base_url="https://x", transport=httpx.MockTransport(handler))
    return MassiveDataSource(cache, "k", client=client, poll_interval=999)


@pytest.fixture(params=["simulator", "massive"])
def source(request):
    cache = PriceCache()
    return (SimulatorDataSource(cache, seed=0) if request.param == "simulator"
            else massive_factory(cache))


async def test_contract(source: MarketDataSource):
    assert isinstance(source, MarketDataSource)
    await source.start(["AAPL", "MSFT"])
    assert source.get_tickers() == ["AAPL", "MSFT"]
    assert source.cache.get_price("AAPL") is not None

    await source.add_ticker("PYPL")
    await source.add_ticker("PYPL")                     # idempotent
    assert source.get_tickers() == ["AAPL", "MSFT", "PYPL"]
    assert source.cache.get_price("PYPL") is not None   # price before add_ticker returns

    await source.remove_ticker("MSFT")
    await source.remove_ticker("MSFT")                  # idempotent
    assert "MSFT" not in source.get_tickers() and "MSFT" not in source.cache

    await source.stop()
    await source.stop()                                 # idempotent
```

### 12.5 Factory and SSE — `test_factory.py`, `test_stream.py`

```python
from app.market import MassiveDataSource, PriceCache, SimulatorDataSource, create_market_data_source
from app.market.stream import price_events


def test_factory_selects_by_env():
    assert isinstance(create_market_data_source(PriceCache(), {}), SimulatorDataSource)
    assert isinstance(create_market_data_source(PriceCache(), {"MASSIVE_API_KEY": "  "}), SimulatorDataSource)
    assert isinstance(create_market_data_source(PriceCache(), {"MASSIVE_API_KEY": "k"}), MassiveDataSource)


async def test_stream_sends_retry_then_snapshot_then_only_on_change():
    import json
    cache = PriceCache()
    cache.update("AAPL", 190.5, 1.0)
    gen = price_events(cache, interval=0)
    assert await anext(gen) == "retry: 1000\n\n"
    first = await anext(gen)
    assert first.startswith("data: ") and first.endswith("\n\n")
    body = json.loads(first[6:])
    assert body["AAPL"]["price"] == 190.5 and set(body["AAPL"]) >= {
        "ticker", "price", "previous_price", "timestamp", "change", "change_percent", "direction"}
    cache.update("AAPL", 190.6, 2.0)
    second = json.loads((await anext(gen))[6:])       # no event is emitted while unchanged
    assert second["AAPL"]["direction"] == "up"
    await gen.aclose()
```

End-to-end check of the route, run manually or in a smoke test:

```bash
cd backend && uv run uvicorn app.main:app --port 8000 &
curl -N --max-time 3 http://localhost:8000/api/stream/prices
```

---

## 13. Implementation Checklist

1. `models.py`, `cache.py` + `test_cache.py`
2. `interface.py`, `seed.py`, `simulator.py` + `test_simulator.py`
3. `massive.py` + `test_massive.py` (MockTransport only, no live key in tests)
4. `test_interface_conformance.py` passes for both sources
5. `tickers.py`, `factory.py`, `tracking.py`, `stream.py` + tests
6. Wire into `main.py` lifespan; `curl -N /api/stream/prices` shows events every ~0.5 s
7. Add `MASSIVE_POLL_INTERVAL=` to `.env.example` and PLAN.md §5
8. With a real key, run the §7.1 `curl` once to confirm the response shape and plan access

## 14. Decisions at a Glance

| Decision | Choice | Why |
|---|---|---|
| Correlation model | One market factor + one sector factor | Exact unit variance, no matrices, easy to reason about and test |
| Simulator speed | `time_scale=50` | Real-time GBM moves ~1¢ per tick; ×50 looks alive while staying plausible |
| Simulator precision | Full-precision internal state, rounded cache | Avoids cheap tickers freezing due to rounding |
| Massive transport | `httpx` direct, not the SDK | Async, mockable, 2 endpoints, no rename churn |
| Massive auth | Bearer header | Key never appears in URLs/logs |
| Massive failure | Keep stale prices; back off on 429/403 | Stale beats empty; never burn the rate limit |
| No silent fallback to simulator | Log a clear error instead | A user who set a key expects real data |
| SSE change detection | `cache.version` counter | O(1) check; quiet stream when nothing moves |
| SSE heartbeat | `: ping` every 15 s | Keeps idle connections alive in Massive mode |
| Tracking rule location | `tracking.py` helpers, not in sources | Sources stay DB-agnostic; rule lives in one place |
