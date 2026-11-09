"""Portfolio valuation and trade execution (PLAN.md Section 8)."""

from app.db import repo
from app.market import PriceCache, untrack_if_unused
from app.market.interface import MarketDataSource
from app.tickers import normalize_ticker

EPSILON = 1e-6


class TradeError(ValueError):
    """A trade rejected by validation. The message is shown to the user (HTTP 400)."""


def _price_or_cost(cache: PriceCache, position: dict) -> float:
    """Live price, falling back to avg cost while the ticker has no price yet."""
    price = cache.get_price(position["ticker"])
    return position["avg_cost"] if price is None else price


def total_value(conn, cache: PriceCache) -> float:
    """Cash plus every position at its live price, unrounded."""
    positions = repo.get_positions(conn)
    return repo.get_cash(conn) + sum(p["quantity"] * _price_or_cost(cache, p) for p in positions)


def _position_view(cache: PriceCache, position: dict) -> dict:
    quantity, avg_cost = position["quantity"], position["avg_cost"]
    price = _price_or_cost(cache, position)
    cost = quantity * avg_cost
    pnl = quantity * price - cost
    return {
        "ticker": position["ticker"],
        "quantity": quantity,
        "avg_cost": round(avg_cost, 4),
        "current_price": round(price, 2),
        "market_value": round(quantity * price, 2),
        "unrealized_pnl": round(pnl, 2),
        "unrealized_pnl_percent": round(pnl / cost * 100, 2) if cost else 0.0,
    }


def portfolio_summary(conn, cache: PriceCache) -> dict:
    """The GET /api/portfolio response, rounded."""
    positions = repo.get_positions(conn)
    cash = repo.get_cash(conn)
    values = [0.0] + [p["quantity"] * _price_or_cost(cache, p) for p in positions]
    costs = [0.0] + [p["quantity"] * p["avg_cost"] for p in positions]
    return {
        "cash_balance": round(cash, 2),
        "positions_value": round(sum(values), 2),
        "total_value": round(cash + sum(values), 2),
        "unrealized_pnl": round(sum(values) - sum(costs), 2),
        "positions": [_position_view(cache, p) for p in positions],
    }


def _apply_trade(conn, ticker: str, side: str, quantity: float, price: float) -> bool:
    """Validate and write cash and position. Returns True if a sell closed the position."""
    cash = repo.get_cash(conn)
    position = repo.get_position(conn, ticker)
    held = position["quantity"] if position else 0.0
    if side == "buy":
        cost = quantity * price
        if cash < cost:
            raise TradeError(f"Insufficient cash: need ${cost:,.2f}, have ${cash:,.2f}")
        new_qty = held + quantity
        old_cost = held * position["avg_cost"] if position else 0.0
        repo.set_cash(conn, cash - cost)
        repo.upsert_position(conn, ticker, new_qty, (old_cost + cost) / new_qty)
        return False
    if quantity > held + EPSILON:
        raise TradeError(f"Cannot sell {quantity:g} {ticker}: you hold {held:g}")
    repo.set_cash(conn, cash + quantity * price)
    remaining = held - quantity
    if remaining < EPSILON:
        repo.delete_position(conn, ticker)
        return True
    repo.upsert_position(conn, ticker, remaining, position["avg_cost"])
    return False


def _trade_view(trade: dict) -> dict:
    return {k: trade[k] for k in ("id", "ticker", "side", "quantity", "price", "executed_at")}


async def execute_trade(
    conn, cache: PriceCache, source: MarketDataSource, ticker: str, side: str, quantity: float
) -> dict:
    """Execute a market order in one transaction. Raises TradeError/ValueError (-> 400)."""
    ticker = normalize_ticker(ticker)
    if side not in ("buy", "sell"):
        raise TradeError(f"Invalid side {side!r}")
    if not quantity > 0:
        raise TradeError("Quantity must be greater than 0")
    price = cache.get_price(ticker)
    if price is None:
        raise TradeError(f"No price yet for {ticker}")

    conn.execute("BEGIN IMMEDIATE")
    try:
        closed = _apply_trade(conn, ticker, side, quantity, price)
        trade = repo.insert_trade(conn, ticker, side, quantity, price)
        repo.insert_snapshot(conn, total_value(conn, cache))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise

    if closed:
        on_watchlist = repo.get_watchlist_entry(conn, ticker) is not None
        await untrack_if_unused(source, ticker, on_watchlist=on_watchlist, has_position=False)
    return {"trade": _trade_view(trade), "portfolio": portfolio_summary(conn, cache)}
