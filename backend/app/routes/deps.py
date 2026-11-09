"""Shared accessors for app state and error mapping."""

from fastapi import HTTPException, Request

from app.market.massive import MassiveAuthError


def state(request: Request):
    """(db connection, price cache, market source) from app state."""
    s = request.app.state
    return s.db, s.price_cache, s.source


def http_error(exc: Exception) -> HTTPException:
    """Map service exceptions: market source down -> 503, validation -> 400."""
    if isinstance(exc, (ConnectionError, MassiveAuthError)):
        return HTTPException(503, "Market data unavailable, try again in a moment")
    return HTTPException(400, str(exc))
