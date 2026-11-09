import asyncio

import httpx
import pytest

from app.market import MassiveDataSource, PriceCache
from app.market.massive import MassiveAuthError, parse_snapshot

NS = 1_000_000_000


def snap(ticker, price, t_s=1_792_839_000):
    return {
        "ticker": ticker,
        "lastTrade": {"p": price, "t": t_s * NS},
        "prevDay": {"c": price - 1},
        "updated": t_s * NS,
    }


def make_source(handler, **kw) -> tuple[MassiveDataSource, PriceCache]:
    client = httpx.AsyncClient(
        base_url="https://api.massive.com", transport=httpx.MockTransport(handler)
    )
    cache = PriceCache()
    return MassiveDataSource(cache, "test-key", client=client, poll_interval=kw.pop("poll_interval", 999), **kw), cache


def test_parse_prefers_last_trade_then_falls_back():
    assert parse_snapshot(snap("AAPL", 190.5)) == ("AAPL", 190.5, 1_792_839_000.0)
    assert parse_snapshot({"ticker": "X", "prevDay": {"c": 10.0}, "updated": 5 * NS}) == ("X", 10.0, 5.0)
    assert parse_snapshot({"ticker": "X", "min": {"c": 11.0, "t": 6000}}) == ("X", 11.0, 6.0)
    assert parse_snapshot({"ticker": "X", "day": {"c": 12.0}, "prevDay": {"c": 10.0}, "updated": 7 * NS}) == (
        "X",
        12.0,
        7.0,
    )
    assert parse_snapshot({"ticker": "X"}) is None
    assert parse_snapshot({"prevDay": {"c": 1.0}}) is None
    assert parse_snapshot({"ticker": "X", "lastTrade": {"p": 0}, "day": {"c": 0}, "prevDay": {"c": -1}}) is None


def test_parse_missing_timestamp_uses_now():
    import time

    before = time.time()
    _, _, ts = parse_snapshot({"ticker": "X", "lastTrade": {"p": 5.0}})
    assert before <= ts <= time.time()


async def test_start_polls_all_tickers_in_one_call():
    calls = []

    def handler(req: httpx.Request):
        calls.append(req)
        assert req.headers["Authorization"] == "Bearer test-key"
        assert req.url.params["tickers"] == "AAPL,MSFT"
        return httpx.Response(200, json={"status": "OK", "tickers": [snap("AAPL", 190.5), snap("MSFT", 420.1)]})

    src, cache = make_source(handler)
    await src.start(["MSFT", "AAPL"])
    assert len(calls) == 1
    assert cache.get_price("AAPL") == 190.5 and cache.get_price("MSFT") == 420.1
    await src.stop()


async def test_poll_drops_untracked_tickers_and_chunks():
    def handler(req):
        return httpx.Response(200, json={"tickers": [snap("AAPL", 1.0), snap("OTHER", 2.0)]})

    src, cache = make_source(handler)
    src._tickers = {"AAPL"}
    assert await src.poll_once() == 1
    assert "OTHER" not in cache


async def test_poll_chunks_large_ticker_sets(monkeypatch):
    import app.market.massive as m

    monkeypatch.setattr(m, "MAX_TICKERS_PER_REQUEST", 2)
    sizes = []

    def handler(req):
        names = req.url.params["tickers"].split(",")
        sizes.append(len(names))
        return httpx.Response(200, json={"tickers": [snap(n, 10.0) for n in names]})

    src, cache = make_source(handler)
    src._tickers = {"A", "B", "C", "D", "E"}
    assert await src.poll_once() == 5
    assert sizes == [2, 2, 1]


async def test_add_ticker_seeds_cache():
    def handler(req):
        assert req.url.path.endswith("/tickers/PYPL")
        return httpx.Response(200, json={"status": "OK", "ticker": snap("PYPL", 65.2)})

    src, cache = make_source(handler)
    await src.add_ticker("PYPL")
    assert cache.get_price("PYPL") == 65.2 and "PYPL" in src.get_tickers()


async def test_add_existing_ticker_makes_no_request():
    src, _ = make_source(lambda req: pytest.fail("no request expected"))
    src._tickers = {"AAPL"}
    await src.add_ticker("AAPL")


async def test_add_unknown_ticker_raises_value_error():
    src, cache = make_source(lambda req: httpx.Response(404, json={"status": "NOT_FOUND"}))
    with pytest.raises(ValueError, match="Unknown ticker XXXX"):
        await src.add_ticker("XXXX")
    assert "XXXX" not in src.get_tickers() and "XXXX" not in cache


async def test_add_ticker_without_usable_price_is_unknown():
    src, cache = make_source(lambda req: httpx.Response(200, json={"ticker": {"ticker": "XXXX"}}))
    with pytest.raises(ValueError, match="Unknown ticker XXXX"):
        await src.add_ticker("XXXX")
    assert "XXXX" not in cache


async def test_add_ticker_network_error_is_connection_error():
    def handler(req):
        raise httpx.ConnectError("boom")

    src, _ = make_source(handler)
    with pytest.raises(ConnectionError):
        await src.add_ticker("AAPL")
    assert src.get_tickers() == []


async def test_add_ticker_403_raises_auth_error():
    src, _ = make_source(lambda req: httpx.Response(403, json={"status": "NOT_AUTHORIZED"}))
    with pytest.raises(MassiveAuthError):
        await src.add_ticker("AAPL")


async def test_403_raises_auth_error_from_poll():
    src, _ = make_source(lambda req: httpx.Response(403, json={"status": "NOT_AUTHORIZED"}))
    src._tickers = {"AAPL"}
    with pytest.raises(MassiveAuthError):
        await src.poll_once()


async def test_start_survives_auth_and_http_errors():
    src, cache = make_source(lambda req: httpx.Response(403))
    await src.start(["AAPL"])
    assert src.get_tickers() == ["AAPL"] and len(cache) == 0
    await src.stop()

    def boom(req):
        raise httpx.ConnectError("down")

    src, cache = make_source(boom)
    await src.start(["AAPL"])
    assert len(cache) == 0
    await src.stop()


async def test_failed_poll_keeps_stale_prices():
    responses = iter(
        [
            httpx.Response(200, json={"tickers": [snap("AAPL", 190.5)]}),
            httpx.Response(500),
        ]
    )
    src, cache = make_source(lambda req: next(responses))
    await src.start(["AAPL"])
    with pytest.raises(httpx.HTTPStatusError):
        await src.poll_once()
    assert cache.get_price("AAPL") == 190.5
    await src.stop()


async def test_unchanged_poll_does_not_bump_version():
    src, cache = make_source(lambda req: httpx.Response(200, json={"tickers": [snap("AAPL", 190.5)]}))
    src._tickers = {"AAPL"}
    await src.poll_once()
    v = cache.version
    await src.poll_once()
    assert cache.version == v


async def test_remove_ticker():
    src, cache = make_source(lambda req: httpx.Response(200, json={"tickers": [snap("AAPL", 1.0)]}))
    await src.start(["AAPL"])
    await src.remove_ticker("AAPL")
    assert src.get_tickers() == [] and "AAPL" not in cache
    await src.stop()


async def test_background_loop_polls_periodically():
    count = 0

    def handler(req):
        nonlocal count
        count += 1
        return httpx.Response(200, json={"tickers": [snap("AAPL", 100.0 + count)]})

    src, cache = make_source(handler, poll_interval=0.01)
    await src.start(["AAPL"])
    await asyncio.sleep(0.1)
    assert count > 1 and cache.get_price("AAPL") > 101.0
    await src.stop()


@pytest.mark.parametrize(
    "response, backoff_min",
    [
        (httpx.Response(429), 50),
        (httpx.Response(403), 250),
        (httpx.Response(500), 0),
    ],
)
async def test_background_loop_backs_off_on_errors(response, backoff_min):
    import time

    src, _ = make_source(lambda req: response, poll_interval=0.01)
    src._tickers = {"AAPL"}
    src._task = asyncio.create_task(src._run())
    await asyncio.sleep(0.1)
    await src.stop()
    if backoff_min:
        assert src._backoff_until - time.monotonic() > backoff_min
    else:
        assert src._backoff_until == 0.0


async def test_background_loop_survives_unexpected_errors():
    calls = 0

    def handler(req):
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"not json")

    src, _ = make_source(handler, poll_interval=0.01)
    src._tickers = {"AAPL"}
    src._task = asyncio.create_task(src._run())
    await asyncio.sleep(0.1)
    await src.stop()
    assert calls > 1


async def test_owned_client_is_closed_on_stop():
    cache = PriceCache()
    src = MassiveDataSource(cache, "k", poll_interval=999)
    src._tickers = set()
    assert src._client.headers["Authorization"] == "Bearer k"
    await src.stop()
    assert src._client.is_closed
