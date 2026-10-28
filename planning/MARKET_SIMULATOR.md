# Market Simulator — Approach and Code Structure

The default market data source when `MASSIVE_API_KEY` is not set. It produces realistic-looking, correlated, live-updating prices for any set of tickers, with no network and no API key.
It implements `MarketDataSource` (MARKET_INTERFACE.md), so the rest of the app cannot tell it from real data.

## 1. Requirements (from PLAN.md)

- Geometric Brownian Motion (GBM) with per-ticker drift and volatility
- Update every ~500 ms
- Correlated moves (tech stocks move together)
- Occasional 2–5% "events" for drama
- Realistic seed prices for known tickers; a random seed for unknown ones
- Accepts any well-formed symbol; in-process asyncio task; no dependencies beyond `numpy`

## 2. The Model

### GBM step

For each ticker, each tick:

```
S(t+dt) = S(t) · exp( (μ − σ²/2)·dt + σ·√dt·Z )
```

| Symbol | Meaning |
|---|---|
| `μ` | annualised drift (e.g. 0.05) |
| `σ` | annualised volatility (e.g. 0.22 for AAPL, 0.50 for TSLA) |
| `dt` | tick length as a fraction of a trading year: `0.5 / (252 · 6.5 · 3600) ≈ 8.48e-8` |
| `Z` | standard normal draw, **correlated across tickers** |

Why GBM: prices stay positive, moves are proportional to price (a $800 stock moves more dollars than a $50 one), and with real annual parameters the statistics look real.

Scale check (AAPL, σ = 0.22, $190): per-tick σ·√dt ≈ 0.0064%, about **1 cent per tick**. Over a 6.5 h session that is ~1.4%, a normal trading day. The `−σ²/2` term makes `μ` the true expected growth rate.

### Correlated draws (Cholesky)

1. Build an `n × n` correlation matrix `C` from sector rules:

| Pair | ρ |
|---|---|
| tech–tech (AAPL, GOOGL, MSFT, AMZN, META, NVDA, NFLX) | 0.6 |
| finance–finance (JPM, V) | 0.5 |
| anything with TSLA | 0.3 |
| cross-sector or unknown ticker | 0.3 |

2. Factor it: `L = cholesky(C)`.
3. Each tick: `z = L @ rng.standard_normal(n)`. Then `z` has correlation `C`.

This matrix is always positive definite: every off-diagonal value is in [0.3, 0.6], and the 0.3 floor acts like a common "market" factor. So Cholesky never fails, even with many unknown tickers. Rebuild `L` only when the ticker set changes (O(n³), trivial for n < 50).

### Events

After the GBM step, with probability `p = 0.001` per ticker per tick, multiply the price by `1 ± U(0.02, 0.05)`.
With 10 tickers at 2 ticks/s, that is one event every ~50 s somewhere on the board: visible, not chaotic.

### Seeds and unknown tickers

- Known tickers: `SEED_PRICES` (AAPL 190, GOOGL 175, MSFT 420, AMZN 185, TSLA 250, NVDA 800, META 500, JPM 195, V 280, NFLX 600)
- Unknown tickers: seed `U(50, 300)` and default params `σ = 0.25, μ = 0.05`, correlated 0.3 with everything
- The simulator itself rounds output to 2 dp; it keeps full precision internally so tiny moves accumulate

## 3. Code Structure

```
backend/app/market/
├── seed_prices.py    # data only: SEED_PRICES, TICKER_PARAMS, DEFAULT_PARAMS, CORRELATION_GROUPS, ρ constants
├── simulator.py      # GBMSimulator (pure, sync) + SimulatorDataSource (async adapter)
└── ...               # interface.py, cache.py, models.py, factory.py (shared)
```

Two classes with one job each:

| Class | Knows about | Responsibility |
|---|---|---|
| `GBMSimulator` | numpy, seed data | The maths. `step()` returns new prices. No asyncio, no cache, so it is easy to test |
| `SimulatorDataSource` | `GBMSimulator`, `PriceCache`, asyncio | Lifecycle: run the loop, write to the cache, implement `MarketDataSource` |

### `GBMSimulator`

```python
class GBMSimulator:
    """Correlated GBM price simulator. Pure and synchronous."""

    TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600
    DEFAULT_DT = 0.5 / TRADING_SECONDS_PER_YEAR

    def __init__(self, tickers: list[str], dt: float = DEFAULT_DT,
                 event_probability: float = 0.001, rng: np.random.Generator | None = None):
        self._rng = rng or np.random.default_rng()
        ...                                   # add tickers, then _rebuild_cholesky()

    def step(self) -> dict[str, float]:
        """Advance every ticker one tick. Returns {ticker: price rounded to 2 dp}."""
        z = self._cholesky @ self._rng.standard_normal(len(self._tickers))
        for i, t in enumerate(self._tickers):
            mu, sigma = self._params[t]["mu"], self._params[t]["sigma"]
            self._prices[t] *= math.exp((mu - 0.5 * sigma**2) * self._dt
                                        + sigma * math.sqrt(self._dt) * z[i])
            if self._rng.random() < self._event_prob:
                self._prices[t] *= 1 + self._rng.choice([-1, 1]) * self._rng.uniform(0.02, 0.05)
        return {t: round(p, 2) for t, p in self._prices.items()}

    def add_ticker(self, ticker: str) -> None       # seed + params, rebuild Cholesky; no-op if present
    def remove_ticker(self, ticker: str) -> None    # rebuild Cholesky; no-op if absent
    def get_price(self, ticker: str) -> float | None
    def get_tickers(self) -> list[str]
```

For n = 1, use the identity in place of Cholesky (or `L = [[1.0]]`). For n = 0, `step()` returns `{}`.

### `SimulatorDataSource`

```python
class SimulatorDataSource(MarketDataSource):
    """MarketDataSource that steps a GBMSimulator every `update_interval` seconds."""

    def __init__(self, price_cache: PriceCache, update_interval: float = 0.5,
                 event_probability: float = 0.001): ...

    async def start(self, tickers):
        self._sim = GBMSimulator(tickers, event_probability=self._event_prob)
        for t in tickers:
            self._cache.update(t, self._sim.get_price(t))   # cache has prices before SSE connects
        self._task = asyncio.create_task(self._run_loop(), name="simulator-loop")

    async def add_ticker(self, ticker):      # sim.add_ticker + immediate cache seed; never raises ValueError
    async def remove_ticker(self, ticker):   # sim.remove_ticker + cache.remove
    async def stop(self):                    # cancel task, await it, swallow CancelledError

    async def _run_loop(self):
        while True:
            try:
                for t, p in self._sim.step().items():
                    self._cache.update(t, p)
            except Exception:
                logger.exception("Simulator step failed")   # keep the loop alive
            await asyncio.sleep(self._interval)
```

All mutation happens on the event loop thread (the loop, `add_ticker`, `remove_ticker`), so the simulator needs no lock. The `PriceCache` lock covers readers in other threads.

## 4. Current Code vs This Design

`backend/app/market/simulator.py` already implements this design. One small improvement is recommended:

- **Inject the RNG.** The current code uses the global `np.random.standard_normal` and `random.random`. Use a single `np.random.Generator` (`np.random.default_rng(seed)`, the current numpy API) passed into the constructor. Tests can then assert exact sequences instead of only statistical properties.

## 5. Tuning Knobs

| Knob | Where | Default | Effect |
|---|---|---|---|
| `update_interval` | `SimulatorDataSource` | 0.5 s | Tick rate (keep in step with the SSE 0.5 s cadence) |
| `dt` | `GBMSimulator` | 0.5 s of trading time | Raise it (e.g. ×60) for a "fast-forward" demo with bigger moves |
| `event_probability` | both | 0.001 | Frequency of 2–5% shocks |
| `TICKER_PARAMS` | `seed_prices.py` | per ticker | Volatility and drift personality |
| ρ constants | `seed_prices.py` | 0.6 / 0.5 / 0.3 | How much the board moves together |

## 6. Tests

`GBMSimulator` (pure, fast):

- `step()` returns every tracked ticker; all prices > 0 and rounded to 2 dp
- Seeded RNG gives a reproducible sequence
- With `event_probability=0`, the mean of `log(S_{t+1}/S_t)` over many steps ≈ `(μ − σ²/2)·dt`, and its std ≈ `σ·√dt`
- Correlation of log-returns between two tech tickers over ~5k steps ≈ 0.6 (tolerance ±0.05)
- `event_probability=1` gives every move ≥ 2% in absolute size
- add/remove: unknown ticker gets a price in [50, 300]; removing rebuilds without error; adding a duplicate is a no-op

`SimulatorDataSource` (async, `update_interval=0.01`):

- After `start()`, the cache holds every ticker immediately
- After a short sleep, the cache version has advanced
- `add_ticker` puts a price in the cache before returning; `remove_ticker` clears it
- `stop()` is idempotent and stops cache writes
