"""FastAPI application: lifespan, routers and the static frontend."""

import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.db import repo
from app.db.connection import connect, init_db
from app.market import PriceCache, create_market_data_source, stream_router
from app.routes import chat, health, portfolio, watchlist
from app.snapshots import snapshot_loop

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIRS = [Path("/app/static"), REPO_ROOT / "frontend" / "out"]

load_dotenv(REPO_ROOT / ".env")


def tracked_tickers(conn) -> list[str]:
    """watchlist ∪ positions."""
    watched = {e["ticker"] for e in repo.get_watchlist(conn)}
    held = {p["ticker"] for p in repo.get_positions(conn)}
    return sorted(watched | held)


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = connect()
    init_db(conn)
    cache = PriceCache()
    source = create_market_data_source(cache)
    await source.start(tracked_tickers(conn))
    snapshots = asyncio.create_task(snapshot_loop(conn, cache))
    app.state.db, app.state.price_cache, app.state.source = conn, cache, source
    yield
    snapshots.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await snapshots
    await source.stop()
    conn.close()


async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Request body/path validation errors are 400 (PLAN.md Section 8), not 422."""
    detail = "; ".join(
        f"{'.'.join(str(p) for p in e['loc'][1:]) or 'body'}: {e['msg']}" for e in exc.errors()
    )
    return JSONResponse({"detail": detail}, status_code=400)


def create_app() -> FastAPI:
    """Build the app: API routers first, static frontend mounted last."""
    app = FastAPI(title="FinAlly", lifespan=lifespan)
    app.add_exception_handler(RequestValidationError, validation_error)
    for router in (stream_router, health.router, portfolio.router, watchlist.router, chat.router):
        app.include_router(router)
    static = next((d for d in STATIC_DIRS if d.is_dir()), None)
    if static is not None:
        app.mount("/", StaticFiles(directory=static, html=True), name="static")
    return app


app = create_app()
