# Massive API (formerly Polygon.io) — Stock Price Reference

Reference for the parts of the Massive REST API that FinAlly uses to fetch current and end-of-day prices for many tickers. Researched November 2026 from the official docs (`massive.com/docs`) and the source of the official Python client (`github.com/massive-com/client-python`).

## 1. Basics

| Item | Value |
|---|---|
| Base URL | `https://api.massive.com` (`https://api.polygon.io` still works for now) |
| Auth | Header `Authorization: Bearer <API_KEY>` (the Python client sends this). Query param `?apiKey=<API_KEY>` also works. |
| Python package | `massive` on PyPI (2.9.1, Oct 2026; Python >= 3.10). Replaces the old `polygon-api-client`. |
| Import | `from massive import RESTClient` |
| Env var read by the client | `MASSIVE_API_KEY` |
| Docs index (LLM friendly) | `https://massive.com/docs/llms.txt`; every docs page has a `.md` version |

Install in the backend:

```bash
uv add massive
```

### Plans, data freshness and rate limits (Stocks)

| Plan | Price | Freshness | Rate limit | Snapshots | Last trade |
|---|---|---|---|---|---|
| Basic (free) | $0 | End-of-day | 5 requests / min | No | No |
| Starter | $29/mo | 15-min delayed | Unlimited | Yes | No |
| Developer | $79/mo | 15-min delayed | Unlimited | Yes | Yes |
| Advanced | $199/mo | Real-time | Unlimited | Yes | Yes |
| Business | $2,499/mo | Real-time | Unlimited | Yes | Business + Expansion only |

- The rate limit is per asset class: "Five requests a minute per asset class you have not subscribed to, and no limit on the ones you have."
- Too many requests returns HTTP 429. Asking for data your plan does not include returns HTTP 403 `NOT_AUTHORIZED`.
- Massive asks paid users to stay under about 100 requests/second.

**What this means for FinAlly:**

- **Free key:** only the aggregate endpoints work: grouped daily, previous close, custom bars and open/close. Prices are end-of-day, so they do not move during the session. Poll at most every 15 s (4 calls/min), which leaves room for one `add_ticker` call each minute.
- **Paid key:** use the snapshot endpoint. One call returns every tracked ticker, and the data is 15-min delayed or real-time depending on the plan.

## 2. Endpoints

Every endpoint below takes a case-sensitive ticker (`AAPL`, not `aapl`), so uppercase tickers first.

### 2.1 Full Market Snapshot, multiple tickers (paid plans) — main polling endpoint

`GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT,TSLA`

| Param | Notes |
|---|---|
| `tickers` | Comma-separated list. Leave it empty to get the whole market (10,000+ tickers, very large). |
| `include_otc` | Default `false` |

Response (trimmed):

```json
{
  "status": "OK",
  "count": 1,
  "tickers": [
    {
      "ticker": "AAPL",
      "day":     {"o": 119.62, "h": 120.53, "l": 118.81, "c": 120.4229, "v": 28727868, "vw": 119.725},
      "min":     {"o": 120.435, "h": 120.468, "l": 120.37, "c": 120.4201, "v": 270796, "vw": 120.4129,
                  "av": 28724441, "n": 762, "t": 1684428720000},
      "prevDay": {"o": 117.19, "h": 119.63, "l": 116.44, "c": 119.49, "v": 110597265, "vw": 118.4998},
      "lastTrade": {"p": 120.47, "s": 236, "t": 1605195918306274000, "x": 10, "i": "4046", "c": [14, 41]},
      "lastQuote": {"p": 120.46, "s": 8, "P": 120.47, "S": 4, "t": 1605195918507251700},
      "todaysChange": 0.98,
      "todaysChangePerc": 0.82,
      "updated": 1605195918306274000
    }
  ]
}
```

Field notes:

- Bars (`day`, `min`, `prevDay`) use `o h l c v vw`: open, high, low, close, volume and VWAP.
- `lastTrade.p` is the last trade price. `lastTrade` is returned only if the plan includes trades (Developer and above), and `lastQuote` only if it includes quotes (Advanced and above).
- `lastTrade.t` and `updated` are Unix **nanoseconds**. `min.t` is Unix **milliseconds**.
- `todaysChangePerc` is a percentage: `0.82` means 0.82 %.
- Snapshot data is cleared overnight and fills in again from about 4:00 AM ET. Early in the morning, `day` may be empty, so fall back to `prevDay.c`.
- Unknown tickers in the `tickers` list are left out of the response. They do not cause an error.

Price to use, in order of preference: `lastTrade.p` → `min.c` → `day.c` → `prevDay.c`.

### 2.2 Single Ticker Snapshot (paid plans) — validating a new ticker

`GET /v2/snapshot/locale/us/markets/stocks/tickers/{ticker}`

The response is `{"status": "OK", "request_id": "...", "ticker": {...}}`, where the inner object has the same shape as one item of `tickers[]` above. An unknown symbol returns a non-200 response (`NOT_FOUND`).

### 2.3 Unified Snapshot (paid plans, alternative)

`GET /v3/snapshot?ticker.any_of=AAPL,MSFT&limit=250`

This endpoint covers several asset classes, with up to 250 tickers per request, and the response is paginated through `next_url`. Field names are snake_case (`last_trade`, `last_minute`, `session.price`, `session.previous_close`, `market_status`). An unknown ticker comes back as an item with `error` and `message` set. FinAlly does not need this endpoint; it is listed here for completeness.

### 2.4 Daily Market Summary / Grouped Daily (all plans) — free-tier polling endpoint

`GET /v2/aggs/grouped/locale/us/market/stocks/{date}` (`date` = `YYYY-MM-DD`)

One call returns the daily OHLC for **every** US stock on that date. This is the only way to price many tickers within the free tier's 5 calls/min.

```json
{
  "status": "OK", "adjusted": true, "queryCount": 3, "resultsCount": 3,
  "results": [
    {"T": "AAPL", "o": 324.66, "h": 326.2, "l": 322.3, "c": 325.12, "v": 26122646, "vw": 324.1, "n": 412345,
     "t": 1673298000000}
  ]
}
```

- `T` is the ticker and `t` is Unix ms (the end of the window).
- On a weekend or holiday `results` is empty or missing. On the free tier the current day is not available until after the close, so step back one day at a time until `results` is not empty.
- Params: `adjusted` (default `true`) and `include_otc` (default `false`).

### 2.5 Previous Day Bar (all plans) — free-tier single-ticker check

`GET /v2/aggs/ticker/{ticker}/prev`

```json
{"status": "OK", "ticker": "AAPL", "resultsCount": 1, "adjusted": true,
 "results": [{"T": "AAPL", "o": 115.55, "h": 117.59, "l": 114.13, "c": 115.97, "v": 131704427,
              "vw": 116.3058, "t": 1605042000000}]}
```

An unknown ticker gives `resultsCount: 0` and no `results`.

### 2.6 Daily Ticker Summary / Open-Close (all plans)

`GET /v1/open-close/{ticker}/{date}`

```json
{"status": "OK", "symbol": "AAPL", "from": "2023-01-09", "open": 324.66, "high": 326.2, "low": 322.3,
 "close": 325.12, "volume": 26122646, "preMarket": 324.5, "afterHours": 322.1}
```

### 2.7 Custom Bars / Aggregates (all plans) — historical series

`GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}`

- `timespan` is one of `minute`, `hour`, `day`, `week`, `month`, `quarter` or `year`.
- `from` and `to` are `YYYY-MM-DD` or Unix ms, and both ends are inclusive.
- Query params: `adjusted`, `sort` (`asc` or `desc`) and `limit` (max 50000).
- `results[]` has `o h l c v vw n t`, where `t` is Unix ms at the start of the bar. The response is paginated through `next_url`.

FinAlly has no price-history endpoint, so this is reference only.

### 2.8 Last Trade (Developer and above)

`GET /v2/last/trade/{ticker}` returns `{"status": "OK", "results": {"T": "AAPL", "p": 129.8473, "s": 25, "t": 1617901342969834000, ...}}`.

Snapshots already include the last trade and cover many tickers per call, so FinAlly does not use this endpoint.

## 3. Python Client

The client is **synchronous** (urllib3). From asyncio code, call it through `asyncio.to_thread`.

```python
from massive import RESTClient

client = RESTClient(api_key=api_key)  # pass the key explicitly (see gotchas)
```

Useful constructor kwargs: `retries=3`, `connect_timeout=10.0`, `read_timeout=10.0`, `pagination=True`, `trace=False`.

| Endpoint | Client method | Returns |
|---|---|---|
| Full market snapshot | `get_snapshot_all("stocks", tickers=[...])` | `list[TickerSnapshot]` |
| Single ticker snapshot | `get_snapshot_ticker("stocks", "AAPL")` | `TickerSnapshot` |
| Unified snapshot | `list_universal_snapshots(ticker_any_of=[...])` | iterator of `UniversalSnapshot` |
| Grouped daily | `get_grouped_daily_aggs(date)` | `list[GroupedDailyAgg]` |
| Previous close | `get_previous_close_agg("AAPL")` | `PreviousCloseAgg` result(s) |
| Open/close | `get_daily_open_close_agg("AAPL", date)` | `DailyOpenCloseAgg` |
| Custom bars | `list_aggs("AAPL", 1, "day", from_, to)` | iterator of `Agg` (auto-paginates) |
| Last trade | `get_last_trade("AAPL")` | `LastTrade` |

The client maps the wire names to snake_case attributes:

- `TickerSnapshot`: `ticker`, `day`, `min`, `prev_day`, `last_trade`, `last_quote`, `todays_change`, `todays_change_percent`, `updated`, `fair_market_value`
- `Agg` (`day`, `prev_day`): `open`, `high`, `low`, `close`, `volume`, `vwap`, `timestamp`
- `MinuteSnapshot` (`min`): the same as `Agg`, plus `accumulated_volume` and `transactions`
- `LastTrade`: `price`, `size`, `sip_timestamp` (ns), `exchange`, `conditions`, `id`
- `GroupedDailyAgg`: `ticker`, `open`, `high`, `low`, `close`, `volume`, `vwap`, `timestamp` (ms)

Errors (`from massive.exceptions import AuthError, BadResponse`):

- `AuthError`: no API key.
- `BadResponse`: any non-200 response. The message is the response body, for example `{"status":"NOT_AUTHORIZED",...}`.
- The client already retries 413, 429, 499 and 5xx responses with backoff (`retries=3`).

### 3.1 Current prices for many tickers (paid plans)

```python
from massive import RESTClient


def snapshot_price(snap) -> float | None:
    """Best available current price from a TickerSnapshot."""
    if snap.last_trade and snap.last_trade.price:
        return snap.last_trade.price
    for bar in (snap.min, snap.day, snap.prev_day):
        if bar and bar.close:
            return bar.close
    return None


def fetch_snapshot_prices(client: RESTClient, tickers: list[str]) -> dict[str, float]:
    """Return {ticker: price} for the given tickers in one request."""
    snaps = client.get_snapshot_all("stocks", tickers=tickers)
    prices = {s.ticker: snapshot_price(s) for s in snaps}
    return {t: p for t, p in prices.items() if p is not None}
```

### 3.2 End-of-day prices for many tickers (free tier)

```python
from datetime import date, timedelta


def fetch_eod_prices(client: RESTClient, tickers: list[str], max_days_back: int = 5) -> dict[str, float]:
    """Return {ticker: close} from the most recent trading day that has data."""
    wanted = set(tickers)
    day = date.today()
    for _ in range(max_days_back):
        bars = client.get_grouped_daily_aggs(day.isoformat())
        if bars:
            return {b.ticker: b.close for b in bars if b.ticker in wanted}
        day -= timedelta(days=1)
    return {}
```

Each call returns about 10,000 rows and costs 1 of the 5 free calls/min. Walking back over a weekend costs up to 3 calls, so cache the date that worked (Section 4).

### 3.3 Checking that a ticker exists

```python
from massive.exceptions import BadResponse


def fetch_single_price(client: RESTClient, ticker: str) -> float:
    """Price for one ticker; ValueError if Massive does not know the symbol."""
    try:
        snap = client.get_snapshot_ticker("stocks", ticker)
    except BadResponse as e:
        raise ValueError(f"Unknown ticker {ticker}") from e
    price = snapshot_price(snap)
    if price is None:
        raise ValueError(f"Unknown ticker {ticker}")
    return price
```

On the free tier, use `get_previous_close_agg(ticker)` instead. An empty result means the ticker is unknown.

### 3.4 Calling from asyncio

```python
import asyncio

prices = await asyncio.to_thread(fetch_snapshot_prices, client, ["AAPL", "MSFT"])
```

### 3.5 Raw HTTP (no client), for debugging

```bash
curl -H "Authorization: Bearer $MASSIVE_API_KEY" \
  "https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT"

curl -H "Authorization: Bearer $MASSIVE_API_KEY" \
  "https://api.massive.com/v2/aggs/grouped/locale/us/market/stocks/2026-11-06"
```

## 4. Gotchas

1. **Default key is read at import time.** The client's signature is `RESTClient(api_key=os.getenv("MASSIVE_API_KEY"))`, and that default is evaluated when `massive` is imported. If `.env` is loaded after the import, the client sees no key. Always pass `api_key=` explicitly.
2. **Free tier means no snapshots.** `get_snapshot_*` returns 403 `NOT_AUTHORIZED` on Basic. Detect this once at startup and switch to grouped daily.
3. **Ticker symbols are case-sensitive.** Uppercase them before every call.
4. **Timestamp units vary.** Trades and snapshot `updated` use nanoseconds; bars use milliseconds. FinAlly stores Unix seconds (`time.time()`) in the cache, the time the price was received, so these units do not leak downstream.
5. **Prices do not change outside market hours.** The poller rewrites the same price, so the cache should only bump its version when the price actually changes (see MARKET_INTERFACE.md).
6. **Unknown tickers in a multi-ticker snapshot are dropped without an error.** Validate a new ticker with a single-ticker call (3.3) before adding it.
7. **The client is blocking.** Never call it directly inside the event loop.

## Sources

- [Full Market Snapshot](https://massive.com/docs/rest/stocks/snapshots/full-market-snapshot.md)
- [Single Ticker Snapshot](https://massive.com/docs/rest/stocks/snapshots/single-ticker-snapshot.md)
- [Unified Snapshot](https://massive.com/docs/rest/stocks/snapshots/unified-snapshot.md)
- [Daily Market Summary](https://massive.com/docs/rest/stocks/aggregates/daily-market-summary.md)
- [Previous Day Bar](https://massive.com/docs/rest/stocks/aggregates/previous-day-bar.md)
- [Daily Ticker Summary](https://massive.com/docs/rest/stocks/aggregates/daily-ticker-summary.md)
- [Custom Bars](https://massive.com/docs/rest/stocks/aggregates/custom-bars.md)
- [Last Trade](https://massive.com/docs/rest/stocks/trades-quotes/last-trade.md)
- [Python client](https://github.com/massive-com/client-python) and [PyPI `massive`](https://pypi.org/project/massive/)
- [Request limits](https://massive.com/knowledge-base/article/what-is-the-request-limit-for-massives-restful-apis)
- [Stocks plans](https://massive.com/stocks)
