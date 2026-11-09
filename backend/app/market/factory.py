from __future__ import annotations

import logging
import os
from collections.abc import Mapping

from .cache import PriceCache
from .interface import MarketDataSource
from .massive import MassiveDataSource
from .simulator import SimulatorDataSource

log = logging.getLogger(__name__)


def create_market_data_source(
    cache: PriceCache, env: Mapping[str, str] | None = None
) -> MarketDataSource:
    """Massive if MASSIVE_API_KEY is set and non-empty, otherwise the simulator."""
    env = os.environ if env is None else env
    api_key = (env.get("MASSIVE_API_KEY") or "").strip()
    if api_key:
        interval = float(env.get("MASSIVE_POLL_INTERVAL") or 15)
        log.info("Market data: Massive REST API (poll every %.0f s)", interval)
        return MassiveDataSource(cache, api_key, poll_interval=interval)
    log.info("Market data: built-in simulator")
    return SimulatorDataSource(cache)
