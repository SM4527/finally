# Market Data — Summary

Condensed reference for the market data layer. It covers what was built in `backend/app/market/` and how the rest of the backend should use it.

Source documents:

| Doc | Role | Status |
|---|---|---|
| `MARKET_DATA_DESIGN.md` | Full design, with code and tests | **Implemented.** The code follows this doc. |
| `MARKET_INTERFACE.md` | An alternative design of the interface and the Massive client (uses the `massive` SDK) | Not what was built. See "Doc conflicts" below. |
| `MARKET_SIMULATOR.md` | An alternative simulator design (real-time GBM, different parameters) | Not what was built. See "Doc conflicts" below. |
| `MASSIVE_API.md` | Reference for the Massive (Polygon.io) REST API | Reference only. |

If this summary and the code disagree, trust the code. If either disagrees with PLAN.md, PLAN.md wins.

## Architecture

```
create_market_data_source(cache)
  MASSIVE_API_KEY set? --yes--> MassiveDataSource ---+
                       --no---> SimulatorDataSource -+ writes
                                                     v
SSE /api/stream/prices <-- reads -- PriceCache -- reads --> trades, portfolio, watchlist, LLM
```

- Sources **push** prices into one `PriceCache`. Readers never call the network.
- Downstream code never knows which source is running.
- Everything runs on one asyncio event loop.

## Modules (`backend/app/`)

| File | Contents |
|---|---|
| `tickers.py` | `normalize_ticker(raw)`: trims, uppercases and validates against `^[A-Z][A-Z0-9.\-]{0,9}$`. Raises `ValueError` (route returns 400). |
| `market/models.py` | `PriceUpdate` (frozen dataclass): `ticker`, `price`, `previous_price`, `timestamp` (Unix seconds), plus the properties `change`, `change_percent` and `direction`, and `to_dict()`, which gives the SSE item shape. |
| `market/cache.py` | `PriceCache`: `update`, `remove`, `get`, `get_price`, `snapshot`, `version`, `in`, `len`. |
| `market/interface.py` | `MarketDataSource`, an abstract base class (ABC). |
| `market/seed.py` | `PROFILES` (seed price, sigma, mu and sector per ticker) and `profile_for()`. |
| `market/simulator.py` | `SimulatorDataSource`: correlated GBM. |
| `market/massive.py` | `MassiveDataSource` (polls with `httpx`), `parse_snapshot`, `MassiveAuthError`. |
| `market/factory.py` | `create_market_data_source(cache, env=None)`. |
| `market/tracking.py` | `track()` and `untrack_if_unused()`: the watchlist ∪ positions rule. |
| `market/stream.py` | `router`, which serves `GET /api/stream/prices`. |

Everything is re-exported from `app.market`. Tests are in `app/tests/market/`. They cover the cache, simulator, Massive client, factory, stream and interface conformance, and all of them run offline.

## PriceCache

- Rounds prices to 2 decimal places on write.
- A ticker's first price is also its own `previous_price`, so its `direction` is `"flat"`.
- `version` goes up only when a price or timestamp actually changes, or when a ticker is removed. The SSE loop compares `version` to skip ticks where nothing changed.
- `get_price(t)` returns `None` when there is no price yet. The trade service turns that into a 400 "No price yet for X".
- `snapshot()` returns a copy, so readers can iterate it safely. A `threading.Lock` guards the cache. It is never contended today; it is there in case a threaded writer is added later.

## MarketDataSource contract

| Method | Behaviour |
|---|---|
| `start(tickers)` | Seeds the cache and starts the background task |
| `stop()` | Cancels the task. Safe to call more than once. |
| `add_ticker(t)` | Does nothing if `t` is already tracked. Otherwise the ticker has a price in the cache by the time the call returns, so "add and buy" works in one chat turn. Raises `ValueError("Unknown ticker T")` for a symbol the source doesn't know. |
| `remove_ticker(t)` | Stops tracking `t` and removes it from the cache. Safe to call more than once. |
| `get_tickers()` | Sorted list of tracked tickers |

Tickers must already be normalized when they reach the source. Sources never decide *whether* a ticker should be tracked; that rule lives in `tracking.py`.

## Simulator (default)

- Uses the exact GBM step `S·exp((μ − σ²/2)Δt + σ√Δt·Z)` every 0.5 s.
- **`time_scale = 50`** speeds up simulated time, so a typical tick moves AAPL about 0.05% (roughly $0.10).
- Moves are correlated through one market factor and one factor per sector: `Z = 0.5·M + 0.5·F_sector + √0.5·ε`.
  - Tickers in the same sector correlate at about 0.5.
  - Tickers in different sectors correlate at about 0.25.
  - Tickers in sector `"other"` load only on the market factor.
- Jump events: each ticker has a 0.0005 chance per tick of moving ±2-5%. Across 10 tickers that is about one event every 100 s.
- Internally, prices keep full precision; only the cache rounds them. Prices are floored at $0.01.
- Seed profiles cover the 10 default tickers plus AMD, INTC, PYPL, BAC and DIS. Any other symbol gets a random seed price between $20 and $400, σ 0.35, μ 0.05 and sector `"other"`.
- Accepts any well-formed symbol. Prices start again from their seeds every time the process starts.
- `step()` is public and synchronous, and `seed=` makes runs reproducible, so tests can drive the simulator deterministically.

## Massive client (when `MASSIVE_API_KEY` is set)

- Calls the REST API with `httpx.AsyncClient` (not the `massive` SDK). The key goes in an `Authorization: Bearer` header, so it never appears in logged URLs.
- Each poll requests every tracked ticker in one call to `GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=...`, in chunks of up to 250. The default interval is 15 s, which suits the free tier's 5 calls/min. Set `MASSIVE_POLL_INTERVAL` to change it.
- Price priority: `lastTrade.p`, then `min.c`, then `day.c`, then `prevDay.c`. Massive timestamps (nanoseconds or milliseconds) are converted to Unix seconds.
- `add_ticker` makes a single-ticker snapshot call. Results map as follows:

  | Result | Exception | Route returns |
  |---|---|---|
  | 404 or no usable price | `ValueError` | 400 |
  | Network failure | `ConnectionError` | 503 |
  | 401 or 403 | `MassiveAuthError` | 503 |

- Failures are handled as follows:
  - Prices from the last good poll stay in the cache.
  - A 429 makes the poller back off for 60 s; a 401/403 makes it back off for 5 min.
  - A failed first poll is logged, and the app keeps running.
- It does **not** fall back to the simulator on its own. A user who set a key expects real data, so the poller logs a clear error instead.
- **Free-tier limitation:** the snapshot endpoints are paid-only, so a free key gets a 403 and no prices. `MASSIVE_API.md` describes a fallback for free keys (grouped daily end-of-day bars), but it is not implemented. The response shape has not been checked against a live key.

## SSE stream (`GET /api/stream/prices`)

- The first frame is `retry: 1000`.
- Every 0.5 s, if `cache.version` has changed, the stream sends one `data:` event with **every** tracked ticker, keyed by symbol (`PriceUpdate.to_dict()`). A ticker missing from an event is no longer tracked.
- A new client gets the current snapshot straight away.
- When nothing changes for 15 s, the stream sends a `: ping` heartbeat.
- Response headers: `Cache-Control: no-cache` and `X-Accel-Buffering: no`.
- The route reads the cache from `request.app.state.price_cache`.

## Integration guide (for the remaining backend work)

**Lifespan** (`main.py`, not written yet). The steps follow PLAN.md Section 3:

```python
db.init_db()
tickers = sorted(set(db.list_watchlist()) | set(db.list_position_tickers()))
cache = PriceCache()
source = create_market_data_source(cache)
await source.start(tickers)
app.state.price_cache, app.state.market_source = cache, source
# ...snapshot task; on shutdown: cancel it, await source.stop()
```

- Call `load_dotenv()` (project-root `.env`) before the factory runs.
- Include `stream_router` with the other API routers.
- Mount the static files last.

**Tracked tickers** (watchlist ∪ positions):

- `POST /api/watchlist`:
  1. Run `normalize_ticker`.
  2. If the ticker is already on the watchlist, return the existing entry.
  3. `await track(source, t)`. A `ValueError` becomes a 400.
  4. Only then insert the row into the database.
- `DELETE /api/watchlist/{t}`: remove the row (404 if it wasn't there), then call `untrack_if_unused(source, t, on_watchlist=False, has_position=...)`.
- A sell that closes a position: call `untrack_if_unused(source, t, on_watchlist=..., has_position=False)`.
- The LLM's "add X and buy" works because watchlist changes run before trades.

**Reading prices**:

- Trade fill: `cache.get_price(t)`.
- Live valuation and LLM context: `{t: u.price for t, u in cache.snapshot().items()}`.

## Doc conflicts

`MARKET_INTERFACE.md` and `MARKET_SIMULATOR.md` describe an earlier alternative design that was not implemented. Where they differ from the code:

| Topic | INTERFACE / SIMULATOR docs | Implemented (DESIGN doc) |
|---|---|---|
| File names | `base.py`, `massive_client.py`, `seed_prices.py` | `interface.py`, `massive.py`, `seed.py` |
| Massive transport | `massive` SDK through `asyncio.to_thread` | `httpx` async |
| Free-tier Massive | Falls back to grouped daily bars | Logs an error; no prices |
| Simulator speed | Real time (about 1¢ per tick) | `time_scale=50` |
| Correlation weights | 0.6 within a sector, 0.3 across sectors | 0.5 within a sector, 0.25 across sectors |
| Event probability | 0.001 | 0.0005 |
| Seed prices | NVDA $130, NFLX $650, JPM $200 | NVDA $880, NFLX $620, JPM $195 |
| Cache "unchanged" rule | The price alone | Price and timestamp |
| SSE heartbeat | None | `: ping` every 15 s |

Next steps for the docs:

- Either delete these two docs or mark them as superseded.
- Decide whether free-tier Massive support (grouped daily bars) is still wanted. PLAN.md Section 6 implies free keys work.
- `MASSIVE_POLL_INTERVAL` is in `.env.example`, but it has not been added to PLAN.md Section 5 yet.
