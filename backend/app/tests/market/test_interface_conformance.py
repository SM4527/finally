import httpx
import pytest

from app.market import MarketDataSource, MassiveDataSource, PriceCache, SimulatorDataSource


def massive_factory(cache):
    def handler(req):
        if req.url.path.endswith("/tickers"):
            names = req.url.params["tickers"].split(",")
            return httpx.Response(
                200,
                json={"tickers": [{"ticker": n, "lastTrade": {"p": 100.0, "t": 1}} for n in names]},
            )
        name = req.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"ticker": {"ticker": name, "lastTrade": {"p": 50.0, "t": 1}}})

    client = httpx.AsyncClient(base_url="https://x", transport=httpx.MockTransport(handler))
    return MassiveDataSource(cache, "k", client=client, poll_interval=999)


@pytest.fixture(params=["simulator", "massive"])
def source(request):
    cache = PriceCache()
    return SimulatorDataSource(cache, seed=0) if request.param == "simulator" else massive_factory(cache)


async def test_contract(source: MarketDataSource):
    assert isinstance(source, MarketDataSource)
    await source.start(["AAPL", "MSFT"])
    assert source.get_tickers() == ["AAPL", "MSFT"]
    assert source.cache.get_price("AAPL") is not None

    await source.add_ticker("PYPL")
    await source.add_ticker("PYPL")  # idempotent
    assert source.get_tickers() == ["AAPL", "MSFT", "PYPL"]
    assert source.cache.get_price("PYPL") is not None  # price before add_ticker returns

    await source.remove_ticker("MSFT")
    await source.remove_ticker("MSFT")  # idempotent
    assert "MSFT" not in source.get_tickers() and "MSFT" not in source.cache

    await source.stop()
    await source.stop()  # idempotent


def test_abstract_interface_cannot_be_instantiated():
    with pytest.raises(TypeError):
        MarketDataSource(PriceCache())  # type: ignore[abstract]
