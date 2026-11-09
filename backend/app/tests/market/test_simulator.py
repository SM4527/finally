import asyncio
import math
import statistics

import pytest

from app.market import PriceCache, SimulatorDataSource
from app.market.seed import PROFILES


async def test_start_seeds_prices_immediately():
    c = PriceCache()
    sim = SimulatorDataSource(c, seed=1)
    await sim.start(["AAPL", "ZZZT"])
    assert c.get_price("AAPL") == 190.0
    assert 20 <= c.get_price("ZZZT") <= 400
    await sim.stop()


def test_default_watchlist_has_profiles():
    for t in ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]:
        assert t in PROFILES


def test_invalid_betas_rejected():
    with pytest.raises(ValueError):
        SimulatorDataSource(PriceCache(), market_beta=0.8, sector_beta=0.8)


def test_prices_stay_positive_and_rounded():
    c = PriceCache()
    sim = SimulatorDataSource(c, seed=2, time_scale=5000)
    sim._track("ZZZT")
    for _ in range(2000):
        sim.step()
    p = c.get_price("ZZZT")
    assert p >= 0.01 and round(p, 2) == p


def test_price_floor():
    c = PriceCache()
    sim = SimulatorDataSource(c, seed=1, event_probability=0.0)
    sim._track("ZZZT")
    sim._prices["ZZZT"] = 0.0001
    sim.step()
    assert sim._prices["ZZZT"] >= 0.01


def test_step_with_no_tickers_is_noop():
    c = PriceCache()
    SimulatorDataSource(c, seed=1).step()
    assert len(c) == 0


def test_step_uses_supplied_timestamp():
    c = PriceCache()
    sim = SimulatorDataSource(c, seed=1)
    sim._track("AAPL")
    sim.step(now=123.0)
    assert c.get("AAPL").timestamp == 123.0


def test_gbm_log_returns_match_sigma():
    c = PriceCache()
    sim = SimulatorDataSource(c, seed=3, event_probability=0.0)
    sim._track("AAPL")
    rets, prev = [], sim._prices["AAPL"]
    for _ in range(20_000):
        sim.step()
        cur = sim._prices["AAPL"]
        rets.append(math.log(cur / prev))
        prev = cur
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


def test_unknown_tickers_use_market_factor_only():
    c = PriceCache()
    sim = SimulatorDataSource(c, seed=7, event_probability=0.0)
    sim._track("ZZZA")
    sim._track("ZZZB")
    a, b = [], []
    pa, pb = sim._prices["ZZZA"], sim._prices["ZZZB"]
    for _ in range(5000):
        sim.step()
        a.append(math.log(sim._prices["ZZZA"] / pa))
        b.append(math.log(sim._prices["ZZZB"] / pb))
        pa, pb = sim._prices["ZZZA"], sim._prices["ZZZB"]
    assert 0.15 < statistics.correlation(a, b) < 0.35


def test_events_produce_big_jumps():
    c = PriceCache()
    sim = SimulatorDataSource(c, seed=5, event_probability=1.0)
    sim._track("AAPL")
    sim.step()
    assert abs(sim._prices["AAPL"] / 190.0 - 1) >= 0.019


def test_seeded_runs_are_deterministic():
    def run():
        sim = SimulatorDataSource(PriceCache(), seed=9)
        sim._track("AAPL")
        for _ in range(10):
            sim.step(now=1.0)
        return sim._prices["AAPL"]

    assert run() == run()


async def test_add_ticker_is_idempotent_and_keeps_price():
    c = PriceCache()
    sim = SimulatorDataSource(c, seed=6)
    await sim.add_ticker("AAPL")
    sim.step()
    price = sim._prices["AAPL"]
    await sim.add_ticker("AAPL")
    assert sim._prices["AAPL"] == price
    assert c.get_price("AAPL") is not None


async def test_remove_ticker_clears_cache():
    c = PriceCache()
    sim = SimulatorDataSource(c, seed=6)
    await sim.start(["AAPL"])
    await sim.remove_ticker("AAPL")
    assert "AAPL" not in c and sim.get_tickers() == []
    await sim.stop()


async def test_background_task_advances_cache_and_stops_twice():
    c = PriceCache()
    sim = SimulatorDataSource(c, seed=8, tick_interval=0.01)
    await sim.start(["AAPL"])
    v = c.version
    await asyncio.sleep(0.1)
    assert c.version > v
    await sim.stop()
    await sim.stop()
    v = c.version
    await asyncio.sleep(0.05)
    assert c.version == v


async def test_start_twice_keeps_single_task():
    sim = SimulatorDataSource(PriceCache(), seed=1, tick_interval=0.01)
    await sim.start(["AAPL"])
    task = sim._task
    await sim.start(["MSFT"])
    assert sim._task is task and sim.get_tickers() == ["AAPL", "MSFT"]
    await sim.stop()
