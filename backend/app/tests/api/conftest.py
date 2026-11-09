import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.market import MarketDataSource


class FakeSource(MarketDataSource):
    """Deterministic source: every ticker is priced at 100; 'NOPE' is unknown."""

    def __init__(self, cache):
        super().__init__(cache)
        self.tickers: set[str] = set()

    async def start(self, tickers):
        for t in tickers:
            await self.add_ticker(t)

    async def stop(self):
        pass

    async def add_ticker(self, ticker):
        if ticker == "NOPE":
            raise ValueError(f"Unknown ticker {ticker}")
        if ticker not in self.tickers:
            self.tickers.add(ticker)
            self.cache.update(ticker, 100.0)

    async def remove_ticker(self, ticker):
        self.tickers.discard(ticker)
        self.cache.remove(ticker)

    def get_tickers(self):
        return sorted(self.tickers)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FINALLY_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(main, "create_market_data_source", FakeSource)
    with TestClient(main.create_app()) as c:
        yield c


@pytest.fixture
def cache(client):
    return client.app.state.price_cache


@pytest.fixture
def source(client):
    return client.app.state.source
