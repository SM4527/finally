# Market Data Interface — Unified Python API

How backend code gets stock prices. One interface, two implementations:

- `MASSIVE_API_KEY` set and non-empty → **`MassiveDataSource`** (real data, see MASSIVE_API.md)
- otherwise → **`SimulatorDataSource`** (GBM simulator, see MARKET_SIMULATOR.md)

Downstream code (SSE stream, portfolio valuation, trades, LLM context) never knows which one is running.
The design matches what exists in `backend/app/market/`. Section 6 lists the changes still needed for the Massive source to meet PLAN.md.

## 1. Shape of the API

Sources are **push-based**: a source runs one background task that writes into a shared `PriceCache`. Consumers only **read the cache**. Nothing calls a source to ask for a price.

```
             create_market_data_source(cache)      reads MASSIVE_API_KEY
                          │
       ┌──────────────────┴──────────────────┐
SimulatorDataSource                    MassiveDataSource
 (GBM step every 0.5 s)       (snapshot poll every 15 s, EOD fallback on free plan)
       └──────────────────┬──────────────────┘
                          ▼  cache.update(ticker, price, timestamp)
                      PriceCache  ──►  SSE /api/stream/prices
                                  ──►  portfolio valuation, trade fills
                                  ──►  watchlist API, LLM context
```

Why push plus cache: the two sources have very different natural cadences (0.5 s vs 15 s or more). The cache decouples them from readers, keeps reads synchronous and instant, and gives SSE one place to detect changes.

## 2. Public API (`app.market`)

```python
from app.market import PriceCache, PriceUpdate, MarketDataSource, create_market_data_source, create_stream_router
```

### `PriceUpdate` (models.py)

```python
@dataclass(frozen=True, slots=True)
class PriceUpdate:
    ticker: str
    price: float            # rounded to 2 dp
    previous_price: float   # price at the previous update (equals price on the first update)
    timestamp: float        # Unix seconds

    change: float           # property: price - previous_price
    change_percent: float   # property
    direction: str          # property: "up" | "down" | "flat"
    def to_dict(self) -> dict: ...   # the SSE payload shape in PLAN.md Section 6
```

### `PriceCache` (cache.py)

Thread-safe. One writer (the active source), many readers.

```python
class PriceCache:
    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate
    def get(self, ticker: str) -> PriceUpdate | None
    def get_price(self, ticker: str) -> float | None
    def get_all(self) -> dict[str, PriceUpdate]
    def remove(self, ticker: str) -> None
    @property
    def version(self) -> int          # bumped on every update; SSE sends only when it changes
```

### `MarketDataSource` (interface.py)

```python
class MarketDataSource(ABC):
    async def start(self, tickers: list[str]) -> None
        """Seed the cache for `tickers`, then start the background task. Call once."""

    async def stop(self) -> None
        """Cancel the background task. Idempotent."""

    async def add_ticker(self, ticker: str) -> None
        """Start tracking `ticker` and seed its price before returning.
        No-op if already tracked. Raises ValueError if the source does not know the symbol."""

    async def remove_ticker(self, ticker: str) -> None
        """Stop tracking `ticker` and remove it from the cache. No-op if absent."""

    def get_tickers(self) -> list[str]
        """Currently tracked tickers."""
```

Contract both implementations must honour:

| Rule | Why |
|---|---|
| `start()` and `add_ticker()` leave a price in the cache before returning | "Add and buy" in one chat turn works; trades need a cached price |
| `add_ticker` raises `ValueError` for an unknown symbol and does not track it | PLAN.md: API returns 400 "Unknown ticker X" |
| Tickers arrive already uppercased and trimmed | Normalisation happens at the API/LLM boundary |
| The background task never dies on a transient error | Log and retry next cycle |
| Timestamps written to the cache are Unix **seconds** | SSE contract |

### `create_market_data_source` (factory.py)

```python
def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if api_key:
        return MassiveDataSource(api_key=api_key, price_cache=price_cache)
    return SimulatorDataSource(price_cache=price_cache)
```

Returns an unstarted source. Optional `MASSIVE_POLL_INTERVAL` (seconds, default `15`) can be read here and passed as `poll_interval`.

## 3. Usage

### FastAPI lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    cache = PriceCache()
    source = create_market_data_source(cache)
    await source.start(tracked_tickers())          # watchlist ∪ positions
    app.state.cache, app.state.source = cache, source
    app.include_router(create_stream_router(cache))
    yield
    await source.stop()
```

### Reading prices

```python
price = request.app.state.cache.get_price("AAPL")      # float | None
if price is None:
    raise HTTPException(400, "No price yet for AAPL")
```

### Watchlist add

```python
try:
    await source.add_ticker(ticker)
except ValueError:
    raise HTTPException(400, f"Unknown ticker {ticker}")
```

## 4. SimulatorDataSource (summary)

- `start`: builds a `GBMSimulator`, writes seed prices to the cache, starts a 0.5 s loop
- `add_ticker`: adds to the simulator (rebuilds correlations) and writes its seed price. Accepts any well-formed symbol and never raises `ValueError`
- Full design in MARKET_SIMULATOR.md

## 5. MassiveDataSource

### Modes

Massive's free **Basic** plan has **no snapshot endpoints**: they return 403 and it serves only past days' bars (MASSIVE_API.md Section 2). So the source has two modes, chosen automatically on `start()`:

| Mode | When | Fetch | Interval | Prices |
|---|---|---|---|---|
| `live` | Snapshot call succeeds (Starter or higher) | `get_snapshot_all(STOCKS, tickers)`, 1 call for all tickers | `poll_interval` (15 s) | 15-min delayed or real-time |
| `eod` | Snapshot call raises `BadResponse` containing `NOT_AUTHORIZED` | `get_grouped_daily_aggs(last_trading_day)`, 1 call for the whole market | 1 hour | Previous close, static |

In `eod` mode the UI shows real but non-moving prices, and the app still works. Log one clear warning: "Massive plan has no snapshot access; showing end-of-day closes".

### Sketch

```python
class MassiveDataSource(MarketDataSource):
    """Massive REST poller. Live snapshots on paid plans, EOD closes on the free plan."""

    def __init__(self, api_key: str, price_cache: PriceCache, poll_interval: float = 15.0):
        self._client = RESTClient(api_key=api_key)
        self._cache = price_cache
        self._interval = poll_interval
        self._tickers: list[str] = []
        self._eod_closes: dict[str, float] | None = None   # set only in eod mode
        self._task: asyncio.Task | None = None

    async def start(self, tickers: list[str]) -> None:
        self._tickers = list(tickers)
        try:
            await self._poll_live()
        except BadResponse as e:
            if "NOT_AUTHORIZED" not in str(e):
                raise
            logger.warning("Massive plan has no snapshot access; showing end-of-day closes")
            await self._poll_eod()
        self._task = asyncio.create_task(self._loop(), name="massive-poller")

    async def add_ticker(self, ticker: str) -> None:
        if ticker in self._tickers:
            return
        if self._eod_closes is not None:
            if ticker not in self._eod_closes:
                raise ValueError(f"Unknown ticker {ticker}")
            self._cache.update(ticker, self._eod_closes[ticker])
        else:
            try:
                snap = await asyncio.to_thread(
                    self._client.get_snapshot_ticker, SnapshotMarketType.STOCKS, ticker
                )
            except BadResponse:
                raise ValueError(f"Unknown ticker {ticker}")
            self._write(snap)
        self._tickers.append(ticker)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(3600 if self._eod_closes is not None else self._interval)
            try:
                await (self._poll_eod() if self._eod_closes is not None else self._poll_live())
            except Exception:
                logger.exception("Massive poll failed")

    async def _poll_live(self) -> None:
        snaps = await asyncio.to_thread(
            self._client.get_snapshot_all, SnapshotMarketType.STOCKS, self._tickers
        )
        for snap in snaps:
            self._write(snap)

    async def _poll_eod(self) -> None:
        self._eod_closes = await asyncio.to_thread(latest_closes, self._client)
        for t in self._tickers:
            if t in self._eod_closes:
                self._cache.update(t, self._eod_closes[t])

    def _write(self, snap: TickerSnapshot) -> None:
        if (p := snapshot_price(snap)) is not None:
            self._cache.update(snap.ticker, p[0], p[1])
```

`snapshot_price` and `latest_closes` are the recipes in MASSIVE_API.md Section 5. Put them in `massive_parse.py` as pure functions so they can be unit-tested with real `TickerSnapshot.from_dict(...)` / `GroupedDailyAgg.from_dict(...)` objects built from the documented JSON samples.

Notes:

- `stop()`, `remove_ticker()` and `get_tickers()` are unchanged from the current code
- `snapshot_price` falls back from `last_trade` to `min.close`, `day.close`, then `prev_day.close`, because Starter snapshots omit `lastTrade`
- An empty snapshot list (e.g. 3:30–4:00 AM ET reset) simply writes nothing, and cached prices stay
- `latest_closes` computes "yesterday" in `America/New_York` and steps back over weekends and holidays

## 6. Gaps in the current `massive_client.py`

Each gap is proven from the SDK source (`.venv/Lib/site-packages/massive`) and the docs:

1. **Timestamp attribute is wrong.** The code reads `snap.last_trade.timestamp / 1000`. `LastTrade` has no `timestamp` field (it is `sip_timestamp`, in **nanoseconds**), and the SDK model sets only declared fields, so every snapshot raises `AttributeError` and is skipped. The cache never fills. The tests miss this because they build snapshots with `MagicMock`. Fix: use `snapshot_price()`, and test with `TickerSnapshot.from_dict(sample_json)`.
2. **`add_ticker` does not validate or seed.** PLAN.md requires a single-ticker snapshot, `ValueError` on an unknown symbol, and an immediate cache seed.
3. **No free-plan handling.** On Basic, every snapshot call returns 403. Add `eod` mode.
4. **PLAN.md says "free tier: poll every 15 seconds".** This is not achievable with snapshots, so update PLAN.md Section 6 to describe `eod` mode.

## 7. Testing

| Test | How |
|---|---|
| Both sources satisfy the contract | Parametrised test over a fake-client Massive source and the simulator: start seeds the cache, add seeds, remove clears |
| `snapshot_price` | `TickerSnapshot.from_dict` on the doc samples: with `lastTrade`, without it, empty |
| Unknown ticker | Fake client raising `BadResponse` → `add_ticker` raises `ValueError`, ticker not tracked |
| EOD fallback | Fake client whose snapshot raises `BadResponse('{"status":"NOT_AUTHORIZED"}')` → cache holds the grouped closes |
| Factory | `monkeypatch.setenv("MASSIVE_API_KEY", ...)` → Massive; empty or unset → simulator |

Never call the live Massive API from tests.

## 8. Out of scope

- Historical bars / price-history endpoint (PLAN.md: the frontend builds history from SSE)
- WebSocket streaming
- Day change vs previous close in the SSE payload (`change` is tick-to-tick per PLAN.md). If wanted later, add an optional `previous_close` to `PriceUpdate`, from `prev_day.close` (Massive) or the seed price (simulator).
