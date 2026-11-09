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

TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600
MIN_PRICE = 0.01


class SimulatorDataSource(MarketDataSource):
    """Correlated GBM price simulator with occasional random jump events."""

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
        self._prices: dict[str, float] = {}  # full precision, never rounded
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
        self.cache.update(ticker, profile.seed_price)

    async def _run(self) -> None:
        while True:
            try:
                self.step()
            except Exception:  # never let one bad tick kill the feed
                log.exception("Simulator step failed")
            await asyncio.sleep(self.tick_interval)

    def step(self, now: float | None = None) -> None:
        """Advance every tracked ticker one tick and write to the cache.
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
                # no sector peers: fold the sector weight into the idiosyncratic term
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
