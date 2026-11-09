from app.market import PriceCache, PriceUpdate


def test_first_update_is_flat_and_rounded():
    c = PriceCache()
    u = c.update("AAPL", 190.4251, 1.0)
    assert (u.price, u.previous_price, u.direction) == (190.43, 190.43, "flat")


def test_previous_price_and_direction():
    c = PriceCache()
    c.update("AAPL", 190.42, 1.0)
    u = c.update("AAPL", 190.50, 2.0)
    assert u.previous_price == 190.42 and u.direction == "up"
    assert u.change == 0.08 and u.change_percent == 0.042


def test_down_direction():
    c = PriceCache()
    c.update("AAPL", 10.0, 1.0)
    u = c.update("AAPL", 9.0, 2.0)
    assert u.direction == "down" and u.change == -1.0 and u.change_percent == -10.0


def test_version_bumps_only_on_change():
    c = PriceCache()
    c.update("AAPL", 1.0, 1.0)
    v = c.version
    c.update("AAPL", 1.0, 1.0)
    assert c.version == v
    c.update("AAPL", 1.0, 2.0)  # same price, new timestamp is visible
    assert c.version == v + 1
    c.remove("AAPL")
    assert c.version == v + 2 and c.get_price("AAPL") is None


def test_remove_unknown_does_not_bump_version():
    c = PriceCache()
    c.remove("NOPE")
    assert c.version == 0


def test_get_snapshot_contains_len():
    c = PriceCache()
    assert c.get("AAPL") is None and c.get_price("AAPL") is None
    c.update("AAPL", 1.0)
    c.update("MSFT", 2.0)
    snap = c.snapshot()
    assert set(snap) == {"AAPL", "MSFT"} and len(c) == 2
    assert "AAPL" in c and "ZZZ" not in c
    c.update("GOOGL", 3.0)
    assert "GOOGL" not in snap  # snapshot is a copy


def test_default_timestamp_is_now():
    import time

    c = PriceCache()
    before = time.time()
    u = c.update("AAPL", 1.0)
    assert before <= u.timestamp <= time.time()


def test_price_update_zero_previous_and_to_dict():
    u = PriceUpdate("X", 1.0, 0.0, 5.0)
    assert u.change_percent == 0.0
    assert PriceUpdate("X", 1.0, 1.0, 5.0).to_dict() == {
        "ticker": "X",
        "price": 1.0,
        "previous_price": 1.0,
        "timestamp": 5.0,
        "change": 0.0,
        "change_percent": 0.0,
        "direction": "flat",
    }
