from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app import portfolio
from app.db import repo
from app.routes.deps import http_error, state

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class TradeRequest(BaseModel):
    ticker: str
    quantity: float
    side: Literal["buy", "sell"]


@router.get("")
async def get_portfolio(request: Request) -> dict:
    conn, cache, _ = state(request)
    return portfolio.portfolio_summary(conn, cache)


@router.post("/trade")
async def trade(body: TradeRequest, request: Request) -> dict:
    conn, cache, source = state(request)
    try:
        return await portfolio.execute_trade(
            conn, cache, source, body.ticker, body.side, body.quantity
        )
    except ValueError as exc:
        raise http_error(exc) from exc


@router.get("/history")
async def history(request: Request) -> dict:
    conn, _, _ = state(request)
    snapshots = repo.get_snapshots(conn, limit=1000)
    return {
        "snapshots": [
            {"total_value": round(s["total_value"], 2), "recorded_at": s["recorded_at"]}
            for s in snapshots
        ]
    }
