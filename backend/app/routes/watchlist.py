from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app import watchlist
from app.market.massive import MassiveAuthError
from app.routes.deps import http_error, state

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class AddTickerRequest(BaseModel):
    ticker: str


@router.get("")
async def get_watchlist(request: Request) -> dict:
    conn, cache, _ = state(request)
    return watchlist.list_watchlist(conn, cache)


@router.post("")
async def add(body: AddTickerRequest, request: Request) -> dict:
    conn, cache, source = state(request)
    try:
        return await watchlist.add_ticker(conn, source, cache, body.ticker)
    except (ValueError, ConnectionError, MassiveAuthError) as exc:
        raise http_error(exc) from exc


@router.delete("/{ticker}", status_code=204)
async def remove(ticker: str, request: Request) -> Response:
    conn, _, source = state(request)
    try:
        await watchlist.remove_ticker(conn, source, ticker)
    except ValueError as exc:
        raise http_error(exc) from exc
    except KeyError as exc:
        raise HTTPException(404, f"{ticker.strip().upper()} is not on the watchlist") from exc
    return Response(status_code=204)
