import pytest

from app.market import MassiveDataSource, PriceCache, SimulatorDataSource, create_market_data_source


def test_factory_selects_by_env():
    assert isinstance(create_market_data_source(PriceCache(), {}), SimulatorDataSource)
    assert isinstance(create_market_data_source(PriceCache(), {"MASSIVE_API_KEY": ""}), SimulatorDataSource)
    assert isinstance(create_market_data_source(PriceCache(), {"MASSIVE_API_KEY": "  "}), SimulatorDataSource)
    assert isinstance(create_market_data_source(PriceCache(), {"MASSIVE_API_KEY": "k"}), MassiveDataSource)


def test_factory_poll_interval():
    src = create_market_data_source(PriceCache(), {"MASSIVE_API_KEY": "k"})
    assert src.poll_interval == 15
    src = create_market_data_source(PriceCache(), {"MASSIVE_API_KEY": "k", "MASSIVE_POLL_INTERVAL": "2"})
    assert src.poll_interval == 2
    src = create_market_data_source(PriceCache(), {"MASSIVE_API_KEY": "k", "MASSIVE_POLL_INTERVAL": ""})
    assert src.poll_interval == 15


def test_factory_reads_os_environ_by_default(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    assert isinstance(create_market_data_source(PriceCache()), SimulatorDataSource)
    monkeypatch.setenv("MASSIVE_API_KEY", "abc")
    assert isinstance(create_market_data_source(PriceCache()), MassiveDataSource)


@pytest.mark.parametrize("raw, expected", [(" brk.b ", "BRK.B"), ("aapl", "AAPL"), ("A", "A"), ("BF-B", "BF-B")])
def test_normalize_ticker_ok(raw, expected):
    from app.tickers import normalize_ticker

    assert normalize_ticker(raw) == expected


@pytest.mark.parametrize("raw", ["1ABC", "TOOLONGTICK", "", "  ", "A B", "AA$", ".A", None])
def test_normalize_ticker_rejects(raw):
    from app.tickers import normalize_ticker

    with pytest.raises(ValueError):
        normalize_ticker(raw)
