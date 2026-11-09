# Market Simulator

The default market data source, used when `MASSIVE_API_KEY` is not set. It produces realistic-looking live prices with no network and no extra dependencies, behind the `MarketDataSource` interface (MARKET_INTERFACE.md).

The code below was run (Python 3.13, standard library only) before it was written here. Measured results are in Section 6.

## 1. Requirements (from PLAN.md)

- Geometric Brownian motion (GBM) with a drift and volatility per ticker
- A tick about every 500 ms
- Correlated moves: stocks in the same sector move together
- Occasional random "events": a sudden 2-5 % move on one ticker
- Realistic seed prices for the default tickers, and a random seed price for any other symbol
- Runs in-process as an asyncio background task

## 2. The Model

### 2.1 GBM step

Each tick, every price is multiplied by the exact GBM solution over a step of `dt` years:

```
S(t+dt) = S(t) · exp( (μ − σ²/2)·dt + σ·√dt·Z )
```

- `μ` is the annual drift and `σ` the annual volatility, both per ticker.
- `Z ~ N(0,1)` is the shock, correlated across tickers (2.2).
- Prices stay positive, and log returns are normal. That is what GBM is for.
- `dt` is the tick length as a fraction of a trading year: `0.5 s / (252 days × 6.5 h × 3600 s)` ≈ 8.5 × 10⁻⁸.

At that scale a 25 %-volatility stock moves about `σ·√dt` ≈ 0.007 % per tick, about 1.4¢ on AAPL at $190. Most ticks change the 2-dp price, so the green and red flashes fire constantly but the moves still look plausible. Time is not sped up.

### 2.2 Correlation: a one-factor-per-sector model

The model uses one market shock plus one shock per sector, instead of building and decomposing a covariance matrix:

```
Z_i = √w_m · M  +  √w_s · S_sector(i)  +  √(1 − w_m − w_s) · ε_i
```

- `M`, the `S_k` and `ε_i` are independent `N(0,1)` draws, made fresh every tick.
- Each `Z_i` is still `N(0,1)`, because the squared weights add up to 1.
- The correlation within a sector is `w_m + w_s`, and across sectors it is `w_m`.
- With `w_m = 0.3` and `w_s = 0.3`, tech stocks correlate at 0.6 with each other and at 0.3 with banks.

This costs O(n) per tick, needs no numpy, and handles tickers added at runtime (a new ticker just joins a sector).

### 2.3 Events

After the GBM step, each ticker has a probability `p = 0.001` per tick of a jump: the price is multiplied by `1 ± U(0.02, 0.05)`, with the sign chosen at random. With 10 tickers at 2 ticks/s, that is one event about every 50 s somewhere on the board. Each event is logged at INFO level.

### 2.4 Parameters

| Ticker | Seed $ | μ | σ | Sector |
|---|---|---|---|---|
| AAPL | 190 | 0.08 | 0.25 | tech |
| GOOGL | 175 | 0.08 | 0.28 | tech |
| MSFT | 420 | 0.08 | 0.24 | tech |
| AMZN | 185 | 0.09 | 0.30 | tech |
| TSLA | 250 | 0.05 | 0.55 | auto |
| NVDA | 130 | 0.12 | 0.50 | tech |
| META | 500 | 0.09 | 0.35 | tech |
| JPM | 200 | 0.06 | 0.20 | finance |
| V | 280 | 0.06 | 0.18 | finance |
| NFLX | 650 | 0.07 | 0.38 | media |
| *other* | U(50, 300) | 0.05 | 0.30 | other |

All unknown tickers share the `other` sector, so they are mildly correlated with each other (0.6). That is acceptable for a demo.

## 3. Code Structure

There are two layers, so the math is testable without asyncio or time:

| Class | Role |
|---|---|
| `GBMSimulator` | A pure engine. It holds params and prices, and `step()` advances every ticker one tick and returns `{ticker: price}`. It takes an injectable `random.Random` (seeded in tests) and `event_probability` (0 in tests). |
| `SimulatorDataSource` | Implements `MarketDataSource`. It owns a `GBMSimulator`, seeds the cache on `start`/`add_ticker`, and runs a loop of `sleep(0.5)`, `step()`, and a write of every price to `PriceCache`. |

Files in `backend/app/market/`: `seed_prices.py` (the table above) and `simulator.py`.

### 3.1 `seed_prices.py`

```python
"""Starting parameters for simulated tickers."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TickerParams:
    """GBM parameters for one ticker. mu and sigma are annualised."""

    price: float
    mu: float
    sigma: float
    sector: str


DEFAULT_PARAMS: dict[str, TickerParams] = {
    "AAPL": TickerParams(190.0, 0.08, 0.25, "tech"),
    "GOOGL": TickerParams(175.0, 0.08, 0.28, "tech"),
    "MSFT": TickerParams(420.0, 0.08, 0.24, "tech"),
    "AMZN": TickerParams(185.0, 0.09, 0.30, "tech"),
    "TSLA": TickerParams(250.0, 0.05, 0.55, "auto"),
    "NVDA": TickerParams(130.0, 0.12, 0.50, "tech"),
    "META": TickerParams(500.0, 0.09, 0.35, "tech"),
    "JPM": TickerParams(200.0, 0.06, 0.20, "finance"),
    "V": TickerParams(280.0, 0.06, 0.18, "finance"),
    "NFLX": TickerParams(650.0, 0.07, 0.38, "media"),
}

UNKNOWN_PRICE_RANGE = (50.0, 300.0)
UNKNOWN_MU = 0.05
UNKNOWN_SIGMA = 0.30
UNKNOWN_SECTOR = "other"
```

### 3.2 `simulator.py`

```python
"""Simulated market: correlated geometric Brownian motion with random events."""

import asyncio
import logging
import math
import random

from .base import MarketDataSource
from .cache import PriceCache
from .seed_prices import (
    DEFAULT_PARAMS,
    UNKNOWN_MU,
    UNKNOWN_PRICE_RANGE,
    UNKNOWN_SECTOR,
    UNKNOWN_SIGMA,
    TickerParams,
)

logger = logging.getLogger(__name__)

TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600
MARKET_WEIGHT = 0.3  # share of variance from the market-wide shock
SECTOR_WEIGHT = 0.3  # share of variance from the sector shock
EVENT_PROBABILITY = 0.001  # per ticker per tick
EVENT_RANGE = (0.02, 0.05)


class GBMSimulator:
    """Pure price engine: no asyncio, no cache. step() advances every ticker by dt seconds."""

    def __init__(
        self,
        dt: float = 0.5,
        rng: random.Random | None = None,
        event_probability: float = EVENT_PROBABILITY,
    ) -> None:
        self._dt = dt / TRADING_SECONDS_PER_YEAR
        self._rng = rng or random.Random()
        self._event_probability = event_probability
        self._params: dict[str, TickerParams] = {}
        self._prices: dict[str, float] = {}

    def add(self, ticker: str) -> float:
        """Start simulating a ticker; returns its seed price."""
        if ticker not in self._prices:
            params = DEFAULT_PARAMS.get(ticker) or self._random_params()
            self._params[ticker] = params
            self._prices[ticker] = params.price
        return self._prices[ticker]

    def remove(self, ticker: str) -> None:
        self._params.pop(ticker, None)
        self._prices.pop(ticker, None)

    def tickers(self) -> list[str]:
        return sorted(self._prices)

    def step(self) -> dict[str, float]:
        """Advance one tick; return the new price of every ticker."""
        market_shock = self._rng.gauss(0, 1)
        sector_shocks: dict[str, float] = {}
        for ticker, params in self._params.items():
            if params.sector not in sector_shocks:
                sector_shocks[params.sector] = self._rng.gauss(0, 1)
            z = self._correlated_shock(market_shock, sector_shocks[params.sector])
            price = self._prices[ticker] * self._gbm_factor(params, z)
            if self._rng.random() < self._event_probability:
                price *= self._event_factor(ticker)
            self._prices[ticker] = price
        return dict(self._prices)

    def _correlated_shock(self, market: float, sector: float) -> float:
        idiosyncratic = self._rng.gauss(0, 1)
        own_weight = 1 - MARKET_WEIGHT - SECTOR_WEIGHT
        return (
            math.sqrt(MARKET_WEIGHT) * market
            + math.sqrt(SECTOR_WEIGHT) * sector
            + math.sqrt(own_weight) * idiosyncratic
        )

    def _gbm_factor(self, params: TickerParams, z: float) -> float:
        drift = (params.mu - 0.5 * params.sigma**2) * self._dt
        diffusion = params.sigma * math.sqrt(self._dt) * z
        return math.exp(drift + diffusion)

    def _event_factor(self, ticker: str) -> float:
        move = self._rng.uniform(*EVENT_RANGE) * self._rng.choice((1, -1))
        logger.info("Market event: %s %+.1f%%", ticker, move * 100)
        return 1 + move

    def _random_params(self) -> TickerParams:
        price = round(self._rng.uniform(*UNKNOWN_PRICE_RANGE), 2)
        return TickerParams(price, UNKNOWN_MU, UNKNOWN_SIGMA, UNKNOWN_SECTOR)


class SimulatorDataSource(MarketDataSource):
    """Runs GBMSimulator in a background task and writes each tick to the cache."""

    def __init__(self, cache: PriceCache, interval: float = 0.5, rng: random.Random | None = None) -> None:
        self._cache = cache
        self._interval = interval
        self._sim = GBMSimulator(dt=interval, rng=rng)
        self._task: asyncio.Task | None = None

    async def start(self, tickers: list[str]) -> None:
        for ticker in tickers:
            self._cache.update(ticker, self._sim.add(ticker))
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def add_ticker(self, ticker: str) -> None:
        self._cache.update(ticker, self._sim.add(ticker))

    async def remove_ticker(self, ticker: str) -> None:
        self._sim.remove(ticker)
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return self._sim.tickers()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            for ticker, price in self._sim.step().items():
                self._cache.update(ticker, price)
```

## 4. Behaviour Notes

- **Unrounded internal prices.** The engine keeps full precision, and the cache rounds to 2 dp on write. Rounding inside the engine would distort the small per-tick moves.
- **`add_ticker` is instant.** It seeds the price into the cache immediately, so "add and buy" in one chat turn works. The simulator accepts any well-formed symbol.
- **Re-adding a ticker** after `remove_ticker` starts again from its seed price (defaults) or a new random one. Re-adding a ticker that is already tracked keeps its current price.
- **Restart.** Prices restart from the seed values on every process start. Positions keep their stored `avg_cost`, so P&L moves accordingly. That is fine for a simulation.
- **Clock drift.** `asyncio.sleep(0.5)` plus the work adds a few ms per tick. The SSE stream sends at most every 500 ms anyway, so no catch-up logic is needed.

## 5. Testing (`backend/tests/market/test_simulator.py`)

Use `GBMSimulator(rng=random.Random(42), event_probability=0)` for deterministic math checks:

1. **Seeds:** `add("AAPL") == 190.0`. An unknown ticker's seed falls in [50, 300] and is the same on a second `add`.
2. **Positivity:** after 10,000 steps every price is > 0.
3. **GBM statistics:** the standard deviation of per-tick log returns is about `σ·√dt` (within 5 % over 20k steps).
4. **Correlation:** over 20k steps, the correlation of log returns is about 0.6 for AAPL/MSFT and about 0.3 for AAPL/JPM (± 0.05).
5. **Events:** with `event_probability=1`, every step moves each price by at least 2 % minus the GBM noise.
6. **Data source:** `start(["AAPL"])` puts a price in the cache straight away. After `asyncio.sleep(1.2)` the cache `version` has advanced. `remove_ticker` drops the ticker from the cache and from `get_tickers()`. `stop()` can be called twice.

Statistical tests must disable events. One 2-5 % jump outweighs thousands of 0.007 % ticks and swamps both the standard deviation and the correlation. The first prototype run showed this (correlation measured at 0.0 with events on, 0.61 with them off).

## 6. Verified Output

From a validation run of the code above (seed 1, 20,000 ticks, events off):

```
corr AAPL-MSFT (same sector, expect ~0.6): 0.61
corr AAPL-JPM  (diff sector, expect ~0.3): 0.3
AAPL typical tick move $: 0.014
```

A sample SSE item from the running source:

```json
{"ticker": "AAPL", "price": 190.0, "previous_price": 190.01, "timestamp": 1794237530.536,
 "change": -0.01, "change_percent": -0.005, "direction": "down"}
```
