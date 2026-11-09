from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TickerProfile:
    seed_price: float
    volatility: float  # annualized sigma
    drift: float  # annualized mu
    sector: str


PROFILES: dict[str, TickerProfile] = {
    "AAPL": TickerProfile(190.00, 0.25, 0.08, "tech"),
    "GOOGL": TickerProfile(175.00, 0.28, 0.08, "tech"),
    "MSFT": TickerProfile(420.00, 0.24, 0.08, "tech"),
    "AMZN": TickerProfile(185.00, 0.32, 0.09, "tech"),
    "META": TickerProfile(500.00, 0.38, 0.10, "tech"),
    "NVDA": TickerProfile(880.00, 0.50, 0.15, "semis"),
    "NFLX": TickerProfile(620.00, 0.40, 0.08, "tech"),
    "TSLA": TickerProfile(250.00, 0.60, 0.05, "auto"),
    "JPM": TickerProfile(195.00, 0.20, 0.06, "finance"),
    "V": TickerProfile(280.00, 0.18, 0.06, "finance"),
    "AMD": TickerProfile(160.00, 0.50, 0.12, "semis"),
    "INTC": TickerProfile(35.00, 0.40, 0.00, "semis"),
    "PYPL": TickerProfile(65.00, 0.40, 0.03, "finance"),
    "BAC": TickerProfile(38.00, 0.25, 0.05, "finance"),
    "DIS": TickerProfile(110.00, 0.30, 0.04, "media"),
}

DEFAULT_VOLATILITY = 0.35
DEFAULT_DRIFT = 0.05
DEFAULT_SECTOR = "other"


def profile_for(ticker: str, rng: random.Random) -> TickerProfile:
    """Known tickers get their profile; unknown ones get a random but plausible one."""
    if ticker in PROFILES:
        return PROFILES[ticker]
    return TickerProfile(
        seed_price=round(rng.uniform(20.0, 400.0), 2),
        volatility=DEFAULT_VOLATILITY,
        drift=DEFAULT_DRIFT,
        sector=DEFAULT_SECTOR,
    )
