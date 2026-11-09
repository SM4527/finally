"""Ticker normalization and validation (PLAN.md Section 8)."""

import re

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def normalize_ticker(raw: str) -> str:
    """Uppercase + trim, then validate. Raises ValueError (-> HTTP 400) if malformed."""
    ticker = (raw or "").strip().upper()
    if not TICKER_RE.fullmatch(ticker):
        raise ValueError(f"Invalid ticker {raw!r}")
    return ticker
