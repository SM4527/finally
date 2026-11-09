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
    """401/403 — key invalid or plan lacks snapshot access."""


def parse_snapshot(item: dict[str, Any]) -> tuple[str, float, float] | None:
    """Return (ticker, price, unix_seconds) from one snapshot object, or None if unusable.

    Price order: lastTrade.p, min.c, day.c, prevDay.c.
    """
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
    """Polls the Massive REST snapshot API for all tracked tickers."""

    def __init__(
        self,
        cache: PriceCache,
        api_key: str,
        *,
        poll_interval: float = 15.0,
        base_url: str = BASE_URL,
        client: httpx.AsyncClient | None = None,  # inject a MockTransport client in tests
        timeout: float = 10.0,
    ) -> None:
        super().__init__(cache)
        self.poll_interval = poll_interval
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self._client.headers["Authorization"] = f"Bearer {api_key}"
        self._owns_client = client is None
        self._tickers: set[str] = set()
        self._task: asyncio.Task | None = None
        self._backoff_until = 0.0

    # ---- MarketDataSource -------------------------------------------------

    async def start(self, tickers: Iterable[str]) -> None:
        self._tickers.update(tickers)
        try:
            await self.poll_once()
        except MassiveAuthError as exc:
            log.error("%s", exc)  # keep running: the app is usable, prices just stay empty
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
        self.cache.update(ticker, price, ts)  # seed before tracking -> "add and buy" works
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
