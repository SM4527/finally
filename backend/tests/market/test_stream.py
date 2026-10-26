"""Tests for the SSE stream router factory."""

from app.market import PriceCache, create_stream_router


def test_each_router_has_one_prices_route():
    """Building two routers must not register duplicate routes."""
    first = create_stream_router(PriceCache())
    second = create_stream_router(PriceCache())

    assert first is not second
    assert [r.path for r in first.routes] == ["/api/stream/prices"]
    assert [r.path for r in second.routes] == ["/api/stream/prices"]
