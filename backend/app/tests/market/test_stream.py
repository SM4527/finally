import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.market import PriceCache, SimulatorDataSource, stream_router, track, untrack_if_unused
from app.market.stream import format_event, price_events


async def test_stream_sends_retry_then_snapshot_then_only_on_change():
    cache = PriceCache()
    cache.update("AAPL", 190.5, 1.0)
    gen = price_events(cache, interval=0)
    assert await anext(gen) == "retry: 1000\n\n"
    first = await anext(gen)
    assert first.startswith("data: ") and first.endswith("\n\n")
    body = json.loads(first[6:])
    assert body["AAPL"]["price"] == 190.5
    assert set(body["AAPL"]) >= {"ticker", "price", "previous_price", "timestamp", "change", "change_percent", "direction"}
    cache.update("AAPL", 190.6, 2.0)
    second = json.loads((await anext(gen))[6:])
    assert second["AAPL"]["direction"] == "up"
    await gen.aclose()


async def test_stream_heartbeat_when_idle():
    cache = PriceCache()
    cache.update("AAPL", 1.0, 1.0)
    gen = price_events(cache, interval=0, heartbeat=0)
    await anext(gen)  # retry
    await anext(gen)  # data
    assert await anext(gen) == ": ping\n\n"
    await gen.aclose()


async def test_stream_drops_removed_ticker():
    cache = PriceCache()
    cache.update("AAPL", 1.0, 1.0)
    cache.update("MSFT", 2.0, 1.0)
    gen = price_events(cache, interval=0)
    await anext(gen)
    assert set(json.loads((await anext(gen))[6:])) == {"AAPL", "MSFT"}
    cache.remove("MSFT")
    assert set(json.loads((await anext(gen))[6:])) == {"AAPL"}
    await gen.aclose()


async def test_stream_stops_when_client_disconnects():
    class Req:
        async def is_disconnected(self):
            return True

    gen = price_events(PriceCache(), Req(), interval=0)
    assert await anext(gen) == "retry: 1000\n\n"
    assert [x async for x in gen] == []


def test_format_event_sorted_and_compact():
    cache = PriceCache()
    cache.update("MSFT", 2.0, 1.0)
    cache.update("AAPL", 1.0, 1.0)
    out = format_event(cache)
    assert out.index("AAPL") < out.index("MSFT") and ", " not in out and ": " not in out


def test_route_headers_and_first_frame(monkeypatch):
    # Patch the generator to a finite one: TestClient would otherwise block on the endless stream.
    import app.market.stream as stream_mod

    async def finite(cache, request=None, **kw):
        yield "retry: 1000\n\n"
        yield format_event(cache)

    monkeypatch.setattr(stream_mod, "price_events", finite)
    app = FastAPI()
    app.state.price_cache = cache = PriceCache()
    cache.update("AAPL", 190.5, 1.0)
    app.include_router(stream_router)
    with TestClient(app) as client:
        resp = client.get("/api/stream/prices")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.text.startswith("retry: 1000\n\ndata: ")


async def test_tracking_rules():
    src = SimulatorDataSource(PriceCache(), seed=1)
    await track(src, "AAPL")
    assert src.get_tickers() == ["AAPL"]
    assert await untrack_if_unused(src, "AAPL", on_watchlist=True, has_position=False) is False
    assert await untrack_if_unused(src, "AAPL", on_watchlist=False, has_position=True) is False
    assert src.get_tickers() == ["AAPL"]
    assert await untrack_if_unused(src, "AAPL", on_watchlist=False, has_position=False) is True
    assert src.get_tickers() == [] and "AAPL" not in src.cache
