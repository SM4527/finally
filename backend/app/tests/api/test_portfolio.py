import pytest


def trade(client, ticker, side, quantity):
    return client.post("/api/portfolio/trade", json={"ticker": ticker, "side": side, "quantity": quantity})


def test_initial_portfolio(client):
    body = client.get("/api/portfolio").json()
    assert body == {
        "cash_balance": 10000.0, "positions_value": 0.0, "total_value": 10000.0,
        "unrealized_pnl": 0.0, "positions": [],
    }


def test_buy_updates_cash_and_position(client):
    r = trade(client, " aapl ", "buy", 10)
    assert r.status_code == 200
    body = r.json()
    assert body["trade"]["ticker"] == "AAPL"
    assert body["trade"]["price"] == 100.0
    assert body["trade"]["executed_at"].endswith("Z")
    assert set(body["trade"]) == {"id", "ticker", "side", "quantity", "price", "executed_at"}
    assert body["portfolio"]["cash_balance"] == 9000.0
    assert body["portfolio"]["positions"][0]["quantity"] == 10


def test_avg_cost_is_weighted_and_pnl_uses_live_price(client, cache):
    trade(client, "AAPL", "buy", 10)
    cache.update("AAPL", 130.0)
    trade(client, "AAPL", "buy", 20)
    cache.update("AAPL", 110.0)
    body = client.get("/api/portfolio").json()
    pos = body["positions"][0]
    assert pos["avg_cost"] == 120.0
    assert pos["current_price"] == 110.0
    assert pos["market_value"] == 3300.0
    assert pos["unrealized_pnl"] == -300.0
    assert pos["unrealized_pnl_percent"] == pytest.approx(-8.33)
    assert body["cash_balance"] == 10000 - 1000 - 2600
    assert body["positions_value"] == 3300.0
    assert body["total_value"] == 6400.0 + 3300.0
    assert body["unrealized_pnl"] == -300.0


def test_fractional_quantity_and_rounding(client, cache):
    cache.update("AAPL", 33.33)
    body = trade(client, "AAPL", "buy", 0.3).json()
    assert body["trade"]["quantity"] == 0.3
    assert body["portfolio"]["cash_balance"] == round(10000 - 0.3 * 33.33, 2)


def test_insufficient_cash(client):
    r = trade(client, "AAPL", "buy", 101)
    assert r.status_code == 400
    assert "Insufficient cash" in r.json()["detail"]
    assert client.get("/api/portfolio").json()["cash_balance"] == 10000.0


def test_oversell(client):
    trade(client, "AAPL", "buy", 5)
    r = trade(client, "AAPL", "sell", 6)
    assert r.status_code == 400
    assert client.get("/api/portfolio").json()["positions"][0]["quantity"] == 5


def test_sell_without_position(client):
    assert trade(client, "AAPL", "sell", 1).status_code == 400


def test_sell_at_a_loss_keeps_avg_cost(client, cache):
    trade(client, "AAPL", "buy", 10)
    cache.update("AAPL", 80.0)
    body = trade(client, "AAPL", "sell", 4).json()["portfolio"]
    assert body["cash_balance"] == 9000 + 320
    pos = body["positions"][0]
    assert pos["quantity"] == 6
    assert pos["avg_cost"] == 100.0
    assert pos["unrealized_pnl"] == -120.0


def test_full_sell_deletes_position(client):
    trade(client, "AAPL", "buy", 10)
    body = trade(client, "AAPL", "sell", 10).json()["portfolio"]
    assert body["positions"] == []
    assert body["cash_balance"] == 10000.0


def test_sell_within_tolerance_closes_position(client):
    trade(client, "AAPL", "buy", 0.1)
    trade(client, "AAPL", "buy", 0.2)
    assert trade(client, "AAPL", "sell", 0.3).json()["portfolio"]["positions"] == []


def test_no_price_yet(client):
    r = trade(client, "ZZZ", "buy", 1)
    assert r.status_code == 400
    assert r.json()["detail"] == "No price yet for ZZZ"


@pytest.mark.parametrize("payload", [
    {"ticker": "AAPL", "side": "buy", "quantity": 0},
    {"ticker": "AAPL", "side": "buy", "quantity": -1},
    {"ticker": "1BAD", "side": "buy", "quantity": 1},
])
def test_invalid_trade_is_400(client, payload):
    assert client.post("/api/portfolio/trade", json=payload).status_code == 400


def test_invalid_side_is_400(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "side": "hold", "quantity": 1})
    assert r.status_code == 400
    assert r.json()["detail"].startswith("side:")


def test_missing_field_is_400(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "side": "buy"})
    assert r.status_code == 400
    assert "quantity" in r.json()["detail"]
    assert client.post("/api/watchlist", json={}).status_code == 400


def test_closing_off_watchlist_position_untracks(client, source):
    client.post("/api/watchlist", json={"ticker": "PYPL"})
    trade(client, "PYPL", "buy", 1)
    client.delete("/api/watchlist/PYPL")
    assert "PYPL" in source.get_tickers()
    trade(client, "PYPL", "sell", 1)
    assert "PYPL" not in source.get_tickers()


def test_closing_watchlist_position_keeps_tracking(client, source):
    trade(client, "AAPL", "buy", 1)
    trade(client, "AAPL", "sell", 1)
    assert "AAPL" in source.get_tickers()


def test_history_has_startup_and_trade_snapshots(client):
    trade(client, "AAPL", "buy", 1)
    snaps = client.get("/api/portfolio/history").json()["snapshots"]
    assert len(snaps) >= 2
    assert snaps[0] == {"total_value": 10000.0, "recorded_at": snaps[0]["recorded_at"]}
    assert snaps[-1]["total_value"] == 10000.0
    assert snaps[0]["recorded_at"] <= snaps[-1]["recorded_at"]
