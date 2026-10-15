"""Stream ticket issuance for split-origin deployments (ADR 0006)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import runtime_of
from app.auth.deps import CurrentUser, current_user
from app.errors import AppError
from app.schemas.api import ErrorResponse, StreamTicketOut

router = APIRouter(prefix="/stream", tags=["stream"])


@router.post(
    "/ticket",
    response_model=StreamTicketOut,
    responses={s: {"model": ErrorResponse} for s in (401, 403, 404)},
)
async def stream_ticket(
    request: Request, user: CurrentUser = Depends(current_user)
) -> StreamTicketOut:
    """Single-use ticket (30 s) that authenticates one WebSocket as this session."""
    rt = runtime_of(request)
    if not rt.settings.stream_ticket_auth_enabled:
        raise AppError(404, "NOT_FOUND", "Stream tickets are not enabled on this server.")
    ticket, expires = rt.tickets.issue(user.id, user.session_id, rt.clock.now())
    return StreamTicketOut(ticket=ticket, expires_at=expires)
