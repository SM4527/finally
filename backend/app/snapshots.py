"""Periodic portfolio value snapshots for the P&L chart."""

import asyncio

from app.db import repo
from app.market import PriceCache
from app.portfolio import total_value


def record_snapshot(conn, cache: PriceCache) -> None:
    """Store the current total portfolio value."""
    repo.insert_snapshot(conn, total_value(conn, cache))


async def snapshot_loop(conn, cache: PriceCache, interval: float = 30.0) -> None:
    """Record a snapshot now and then every `interval` seconds until cancelled."""
    while True:
        record_snapshot(conn, cache)
        await asyncio.sleep(interval)
