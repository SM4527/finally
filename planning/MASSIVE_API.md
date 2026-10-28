# Massive API (formerly Polygon.io) — Stock Prices Reference

Research notes for retrieving **real-time** and **end-of-day (EOD)** prices for multiple US stock tickers.
Polygon.io rebranded as **Massive** (massive.com). The REST API shape is unchanged; only hosts and package names moved.

Verified against the official docs (massive.com/docs, Oct 2026) and the installed SDK source (`massive` 2.2.0 in `backend/.venv`).

## 1. Basics

| Item | Value |
|---|---|
| REST base URL | `https://api.massive.com` |
| Auth | `Authorization: Bearer <key>` header (SDK default) or `?apiKey=<key>` query param |
| Python SDK | `massive` on PyPI (`uv add massive`), repo `github.com/massive-com/client-python` |
| SDK env var | `MASSIVE_API_KEY` (the SDK reads it when no `api_key` is passed) |
| SDK style | Synchronous (urllib3). Wrap calls in `asyncio.to_thread` inside async code |
| Ticker symbols | Case-sensitive, so always send them uppercase (`AAPL`, `BRK.B`) |

```python
from massive import RESTClient

client = RESTClient(api_key="...")   # or RESTClient() to read MASSIVE_API_KEY
```

`RESTClient` defaults: `connect_timeout=10`, `read_timeout=10`, `retries=3` with urllib3 backoff on 413/429/499/500/502/503/504.
A non-200 response raises `massive.exceptions.BadResponse` (the message is the response body). A missing key raises `AuthError`.

## 2. Plans, Recency and Rate Limits

| Plan | Snapshots | Last trade | Aggregates (bars) | Recency | Rate limit |
|---|---|---|---|---|---|
| **Basic** (free) | No | No | Yes, past days only | End-of-day | **5 req/min** |
| Starter | Yes | No | Yes | 15-min delayed | Unlimited |
| Developer | Yes | Yes | Yes | 15-min delayed | Unlimited |
| Advanced | Yes | Yes | Yes | Real-time | Unlimited |
| Business | Yes | Yes (+Expansion) | Yes | Real-time | Unlimited |

Facts that matter for this project:

- **The free Basic plan has no snapshot endpoints.** It can only read bars for *past* trading days. A request for the current ET day returns **HTTP 403 `NOT_AUTHORIZED`**, even after the 4 PM close. The previous day becomes available after **12:00 AM ET**.
- Over the limit returns **HTTP 429**. On Basic, retrying does not help.
- Snapshot data is cleared at **3:30 AM ET** and refills from ~4:00 AM ET as exchanges report.
- `lastTrade` / `lastQuote` appear in snapshots **only if the plan includes trades/quotes**. Starter gets snapshots without `lastTrade`, so price extraction needs a fallback (Section 5).
- Paid plans are "unlimited", but polling every few seconds is plenty for a UI.

## 3. Real-Time Prices

### 3.1 Full-market snapshot (multiple tickers, one call) — primary endpoint

`GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT,TSLA`

- `tickers`: comma-separated; omit it to get every ticker (~10k)
- `include_otc`: default `false`
- One request covers the whole watchlist, so this is the endpoint to poll

Response (trimmed from the official sample):

```json
{
  "status": "OK",
  "count": 1,
  "tickers": [
    {
      "ticker": "AAPL",
      "todaysChange": 0.98,
      "todaysChangePerc": 0.82,
      "updated": 1605195918306274000,
      "day":     {"o": 119.62, "h": 120.53, "l": 118.81, "c": 120.4229, "v": 28727868, "vw": 119.725},
      "prevDay": {"o": 117.19, "h": 119.63, "l": 116.44, "c": 119.49,   "v": 110597265, "vw": 118.4998},
      "min":     {"o": 120.435, "h": 120.468, "l": 120.37, "c": 120.4201, "v": 270796, "t": 1684428720000, "n": 762},
      "lastTrade": {"p": 120.47, "s": 236, "t": 1605195918306274000, "x": 10, "c": [14, 41], "i": "4046"},
      "lastQuote": {"p": 120.46, "s": 8, "P": 120.47, "S": 4, "t": 1605195918507251700}
    }
  ]
}
```

Timestamp units (easy to get wrong):

| Field | Unit |
|---|---|
| `updated`, `lastTrade.t`, `lastQuote.t` | **nanoseconds** |
| `min.t`, aggregate bar `t` | **milliseconds** |

SDK:

```python
from massive import RESTClient
from massive.rest.models import SnapshotMarketType

client = RESTClient(api_key=key)
snapshots = client.get_snapshot_all(
    market_type=SnapshotMarketType.STOCKS,   # or "stocks"
    tickers=["AAPL", "MSFT", "TSLA"],        # SDK joins the list with commas
)
for snap in snapshots:                       # list[TickerSnapshot]
    print(snap.ticker, snap.last_trade.price if snap.last_trade else None,
          snap.prev_day.close if snap.prev_day else None, snap.todays_change_percent)
```

SDK model fields (`massive.rest.models`):

| `TickerSnapshot` | Type |
|---|---|
| `ticker` | `str` |
| `last_trade` | `LastTrade` or `None`: `.price`, `.size`, **`.sip_timestamp`** (ns), `.exchange` |
| `last_quote` | `LastQuote` or `None`: `.bid_price`, `.ask_price`, `.sip_timestamp` (ns) |
| `min` | `MinuteSnapshot`: `.close`, `.timestamp` (ms), `.accumulated_volume` |
| `day`, `prev_day` | `Agg`: `.open .high .low .close .volume .vwap` |
| `todays_change`, `todays_change_percent` | `float` (vs previous close) |
| `updated` | `int` (ns) |

> **Gotcha:** `LastTrade` has **no `timestamp` attribute**. It is `sip_timestamp`, in nanoseconds. The SDK model sets only its declared fields, so `snap.last_trade.timestamp` raises `AttributeError`. The current `backend/app/market/massive_client.py` reads `.timestamp` and divides by 1000. Its tests use `MagicMock` snapshots, which hide the bug. See MARKET_INTERFACE.md, Section 6.

### 3.2 Single-ticker snapshot

`GET /v2/snapshot/locale/us/markets/stocks/tickers/{ticker}` returns the same object under a `"ticker"` key.

```python
snap = client.get_snapshot_ticker(SnapshotMarketType.STOCKS, "AAPL")
```

Use it to validate and seed a newly added ticker. An unknown symbol gives a non-200 response, which the SDK raises as `BadResponse`. The docs do not specify the status code (Polygon historically returned 404 `NOT_FOUND`), so treat any `BadResponse` here as "unknown ticker".

### 3.3 Last trade / last quote (per ticker)

```python
trade = client.get_last_trade("AAPL")    # GET /v2/last/trade/AAPL  -> .price, .sip_timestamp (ns)
quote = client.get_last_quote("AAPL")    # GET /v2/last/nbbo/AAPL   -> .bid_price, .ask_price
```

These take one call per ticker and need Developer or higher (last trade). Prefer the batch snapshot.

### 3.4 Top movers

```python
gainers = client.get_snapshot_direction(SnapshotMarketType.STOCKS, "gainers")  # or "losers"; top 20
```

### 3.5 Market status

```python
status = client.get_market_status()   # GET /v1/marketstatus/now -> .market ("open"/"closed"/"extended-hours")
```

### 3.6 WebSocket (not used by this project)

Massive also streams trades, quotes and per-second/minute aggregates over WebSocket (`wss://socket.massive.com/stocks` for real-time, `wss://delayed.massive.com/stocks` for 15-min delayed). The SDK exposes this as `massive.WebSocketClient`. PLAN.md picks REST polling because it is simpler and works on every paid tier.

```python
from massive import WebSocketClient
from massive.websocket.models import Feed, Market

ws = WebSocketClient(api_key=key, feed=Feed.Delayed, market=Market.Stocks,
                     subscriptions=["AM.AAPL", "AM.MSFT"])   # AM = minute aggregates, T = trades
ws.run(handle_msg=lambda msgs: print(msgs))
```

## 4. End-of-Day Prices

All of these work on **every plan, Basic included** (Basic: past days only, 2 years of history).

### 4.1 Grouped daily — every ticker's OHLC for one date, one call

`GET /v2/aggs/grouped/locale/us/market/stocks/{date}?adjusted=true`

```json
{"status": "OK", "adjusted": true, "resultsCount": 3,
 "results": [{"T": "VSAT", "o": 34.9, "h": 35.47, "l": 34.21, "c": 34.24, "v": 312583, "vw": 34.4736, "n": 4966, "t": 1602705600000}]}
```

```python
bars = client.get_grouped_daily_aggs("2026-10-27", adjusted=True)   # list[GroupedDailyAgg]
wanted = {"AAPL", "MSFT", "TSLA"}
closes = {b.ticker: b.close for b in bars if b.ticker in wanted}
```

This is the cheapest way to get EOD closes for many tickers on the free plan: one request regardless of watchlist size. Weekends and holidays return no results, so step back a day until results appear.

### 4.2 Previous day bar (per ticker)

`GET /v2/aggs/ticker/{ticker}/prev`

```python
prev = client.get_previous_close_agg("AAPL")   # PreviousCloseAgg: .ticker .open .high .low .close .volume .vwap .timestamp (ms)
```

One call per ticker. On Basic, 10 tickers is two minutes of quota.

### 4.3 Daily open/close (per ticker, specific date)

`GET /v1/open-close/{ticker}/{date}`

```python
oc = client.get_daily_open_close_agg("AAPL", "2026-10-27")   # .open .close .high .low .pre_market .after_hours .volume
```

### 4.4 Historical bars (custom range)

`GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}`

- `timespan`: `second | minute | hour | day | week | month | quarter | year`
- `from`/`to`: `YYYY-MM-DD` or Unix ms
- `limit`: default 5000, max 50000. Pages follow `next_url`; `list_aggs` paginates automatically

```python
for bar in client.list_aggs("AAPL", 1, "day", "2026-09-01", "2026-10-27", adjusted=True, sort="asc"):
    print(bar.timestamp, bar.close)          # timestamp is Unix ms (start of the bar)

bars = client.get_aggs("AAPL", 5, "minute", "2026-10-27", "2026-10-27")   # single page as a list
```

## 5. Recipes

### Extract a price from a snapshot

`lastTrade` is missing on plans without trades (e.g. Starter), so fall back through the fields:

```python
def snapshot_price(snap) -> tuple[float, float] | None:
    """Return (price, unix_seconds) from a TickerSnapshot, or None if it has no price yet."""
    if snap.last_trade and snap.last_trade.price:
        return snap.last_trade.price, snap.last_trade.sip_timestamp / 1e9
    if snap.min and snap.min.close:
        return snap.min.close, snap.min.timestamp / 1e3
    if snap.day and snap.day.close:
        return snap.day.close, snap.updated / 1e9
    if snap.prev_day and snap.prev_day.close:
        return snap.prev_day.close, snap.updated / 1e9
    return None
```

### Poll multiple tickers from async code

```python
import asyncio

async def poll(client, tickers: list[str], interval: float = 15.0):
    while True:
        snaps = await asyncio.to_thread(
            client.get_snapshot_all, SnapshotMarketType.STOCKS, tickers
        )
        for snap in snaps:
            if (p := snapshot_price(snap)) is not None:
                print(snap.ticker, *p)
        await asyncio.sleep(interval)
```

### Latest EOD closes for many tickers (works on the free plan)

```python
from datetime import date, timedelta

def latest_closes(client, tickers: set[str], max_days_back: int = 5) -> dict[str, float]:
    """Closes from the most recent completed trading day. One call, plus one per non-trading day."""
    day = date.today() - timedelta(days=1)
    for _ in range(max_days_back):
        bars = client.get_grouped_daily_aggs(day.isoformat())
        if bars:
            return {b.ticker: b.close for b in bars if b.ticker in tickers}
        day -= timedelta(days=1)
    return {}
```

Before midnight ET, "yesterday" in a timezone ahead of ET may still be the current ET day, which gets a 403 on Basic. Compute the date in `America/New_York` (`datetime.now(ZoneInfo("America/New_York")).date()`).

### Raw HTTP without the SDK

```python
import httpx

r = httpx.get(
    "https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers",
    params={"tickers": "AAPL,MSFT"},
    headers={"Authorization": f"Bearer {key}"},
)
r.raise_for_status()
for t in r.json()["tickers"]:
    print(t["ticker"], t.get("lastTrade", {}).get("p"), t["prevDay"]["c"])
```

## 6. Errors

| Status | Meaning | Handling |
|---|---|---|
| 401 | Bad or missing key | Log clearly; do not retry tightly |
| 403 `NOT_AUTHORIZED` | Plan lacks this endpoint or timeframe (e.g. snapshot on Basic) | Log once; fall back (see MARKET_INTERFACE.md) |
| 404 | Unknown ticker / resource | Treat as invalid symbol |
| 429 | Rate limit | The SDK already retries; then wait for the next poll |
| 5xx | Server error | The SDK already retries; then wait for the next poll |

## Sources

- [Full market snapshot](https://massive.com/docs/rest/stocks/snapshots/full-market-snapshot)
- [Single ticker snapshot](https://massive.com/docs/rest/stocks/snapshots/single-ticker-snapshot)
- [Previous day bar](https://massive.com/docs/rest/stocks/aggregates/previous-day-bar)
- [Daily market summary (grouped daily)](https://massive.com/docs/rest/stocks/aggregates/daily-market-summary)
- [Custom bars](https://massive.com/docs/rest/stocks/aggregates/custom-bars)
- [Last trade](https://massive.com/docs/rest/stocks/trades-quotes/last-trade)
- [Basic plan: when previous-day data is available](https://massive.com/knowledge-base/article/on-the-free-basic-plan-when-can-i-pull-the-previous-trading-days-data)
- [Python client](https://github.com/massive-com/client-python), [docs index](https://massive.com/docs/llms.txt), [pricing](https://massive.com/pricing)
