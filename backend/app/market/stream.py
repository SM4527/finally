from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache

router = APIRouter(prefix="/api/stream", tags=["stream"])

PUSH_INTERVAL = 0.5
HEARTBEAT_INTERVAL = 15.0


def format_event(cache: PriceCache) -> str:
    payload = {t: u.to_dict() for t, u in sorted(cache.snapshot().items())}
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


async def price_events(
    cache: PriceCache,
    request: Request | None = None,
    *,
    interval: float = PUSH_INTERVAL,
    heartbeat: float = HEARTBEAT_INTERVAL,
) -> AsyncIterator[str]:
    yield "retry: 1000\n\n"
    last_version = -1
    last_sent = time.monotonic()
    while True:
        if request is not None and await request.is_disconnected():
            return
        version = cache.version
        if version != last_version:
            last_version = version
            yield format_event(cache)
            last_sent = time.monotonic()
        elif time.monotonic() - last_sent >= heartbeat:
            yield ": ping\n\n"
            last_sent = time.monotonic()
        await asyncio.sleep(interval)


@router.get("/prices")
async def stream_prices(request: Request) -> StreamingResponse:
    cache: PriceCache = request.app.state.price_cache
    return StreamingResponse(
        price_events(cache, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
