"""`/ws/market`: authenticated, Origin-checked snapshot + ordered delta stream."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth.deps import origin_allowed, resolve_session
from app.config import Settings
from app.runtime import Runtime
from app.streaming.hub import CLOSE_FORBIDDEN_ORIGIN, CLOSE_UNAUTHENTICATED, Connection, Control

router = APIRouter()
log = logging.getLogger("marketops.ws")


@router.websocket("/ws/market")
async def market_stream(websocket: WebSocket) -> None:
    settings: Settings = websocket.app.state.settings
    runtime: Runtime = websocket.app.state.runtime
    # Reject before accepting: the handshake fails with HTTP 403 and no data is sent.
    if not origin_allowed(settings, websocket.headers.get("origin")):
        await websocket.close(code=CLOSE_FORBIDDEN_ORIGIN)
        return
    async with websocket.app.state.sessionmaker() as db:
        user = await resolve_session(
            db, settings, websocket.cookies.get(settings.session_cookie_name), runtime.clock.now()
        )
    if user is None:
        await websocket.close(code=CLOSE_UNAUTHENTICATED)
        return

    await websocket.accept()
    conn, snapshot, watermark = await runtime.hub.register(
        user.id, user.session_id, runtime.clock.now()
    )
    try:
        await websocket.send_text(snapshot)
        sender = asyncio.create_task(_send_loop(websocket, conn, watermark))
        receiver = asyncio.create_task(_receive_loop(websocket))
        done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                log.warning("stream connection ended with %s", type(exc).__name__)
    except WebSocketDisconnect:
        pass
    finally:
        runtime.hub.unregister(conn)


async def _send_loop(websocket: WebSocket, conn: Connection, watermark: int) -> None:
    while True:
        item = await conn.queue.get()
        if isinstance(item, Control):
            with contextlib.suppress(Exception):
                await websocket.send_text(item.message)
                await websocket.close(code=item.close_code)
            return
        seq, payload = item
        if seq is not None and seq <= watermark:
            continue  # already reflected in this connection's snapshot
        await websocket.send_text(payload)
        if seq is not None:
            conn.sent_batches += 1


async def _receive_loop(websocket: WebSocket) -> None:
    # Clients do not send data; reading detects disconnects promptly.
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
