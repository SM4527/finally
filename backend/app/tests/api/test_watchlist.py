def tickers(client):
    return [e["ticker"] for e in client.get("/api/watchlist").json()["watchlist"]]


def test_default_watchlist_with_prices(client):
    items = client.get("/api/watchlist").json()["watchlist"]
    assert [e["ticker"] for e in items] == ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]
    assert items[0]["price"] == 100.0
    assert items[0]["added_at"].endswith("Z")


def test_add_ticker(client, source):
    r = client.post("/api/watchlist", json={"ticker": " pypl "})
    assert r.status_code == 200
    assert r.json()["ticker"] == "PYPL"
    assert r.json()["price"] == 100.0
    assert "PYPL" in tickers(client)
    assert "PYPL" in source.get_tickers()


def test_add_existing_returns_entry(client):
    first = client.get("/api/watchlist").json()["watchlist"][0]
    r = client.post("/api/watchlist", json={"ticker": "aapl"})
    assert r.status_code == 200
    assert r.json() == first
    assert tickers(client).count("AAPL") == 1


def test_add_invalid_or_unknown_is_400(client):
    assert client.post("/api/watchlist", json={"ticker": "1BAD"}).status_code == 400
    r = client.post("/api/watchlist", json={"ticker": "nope"})
    assert r.status_code == 400
    assert r.json()["detail"] == "Unknown ticker NOPE"
    assert "NOPE" not in tickers(client)


def test_remove_ticker(client, source):
    r = client.delete("/api/watchlist/tsla")
    assert r.status_code == 204
    assert "TSLA" not in tickers(client)
    assert "TSLA" not in source.get_tickers()


def test_remove_unknown_is_404(client):
    assert client.delete("/api/watchlist/ZZZ").status_code == 404


def test_remove_keeps_tracking_held_ticker(client, source):
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "side": "buy", "quantity": 1})
    client.delete("/api/watchlist/AAPL")
    assert "AAPL" in source.get_tickers()


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}
