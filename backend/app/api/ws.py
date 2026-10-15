"""`/ws/market`: authenticated, Origin-checked snapshot + ordered delta stream."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth.deps import CurrentUser, origin_allowed, resolve_session, resolve_session_by_id
from app.config import Settings
from app.runtime import Runtime
from app.streaming.hub import (
    CLOSE_FORBIDDEN_ORIGIN,
    CLOSE_TRY_AGAIN_LATER,
    CLOSE_UNAUTHENTICATED,
    Connection,
    Control,
)

router = APIRouter()
AUTH_TIMEOUT_SECONDS = 5.0
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
    accepted = False
    if user is None and settings.stream_ticket_auth_enabled:
        # Split-origin mode: accept, then require {"type": "auth", "ticket": ...} within 5 s.
        await websocket.accept()
        accepted = True
        user = await _authenticate_with_ticket(websocket, runtime, settings)
    if user is None:
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await websocket.close(code=CLOSE_UNAUTHENTICATED)
        return
    refusal = runtime.hub.admission_error(user.session_id)
    if refusal is not None:
        if not accepted:
            await websocket.accept()
        await websocket.send_text(json.dumps({"type": "resync", "reason": refusal}))
        await websocket.close(code=CLOSE_TRY_AGAIN_LATER)
        return

    if not accepted:
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


async def _authenticate_with_ticket(
    websocket: WebSocket, runtime: Runtime, settings: Settings
) -> CurrentUser | None:
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
        message = json.loads(raw)
    except (TimeoutError, ValueError, WebSocketDisconnect, KeyError, RuntimeError):
        return None
    if not isinstance(message, dict) or message.get("type") != "auth":
        return None
    ticket = message.get("ticket")
    if not isinstance(ticket, str) or len(ticket) > 256:
        return None
    grant = runtime.tickets.redeem(ticket, runtime.clock.now())
    if grant is None:
        return None
    # The session must still be valid (not revoked or expired) when the ticket is redeemed.
    async with websocket.app.state.sessionmaker() as db:
        return await resolve_session_by_id(db, settings, grant.session_id, runtime.clock.now())


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
