"""Single-use, short-lived WebSocket stream tickets (split-origin deployments, ADR 0006).

Issued over the cookie-authenticated, CSRF-protected REST API; redeemed once as the first
WebSocket message. Only SHA-256 digests are kept, in process memory (single worker, ADR 0002).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.auth.security import new_token, token_digest

MAX_OUTSTANDING = 2000


@dataclass(frozen=True)
class TicketGrant:
    user_id: uuid.UUID
    session_id: uuid.UUID
    expires_at: datetime


class StreamTickets:
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl = timedelta(seconds=ttl_seconds)
        self._grants: dict[str, TicketGrant] = {}

    def issue(
        self, user_id: uuid.UUID, session_id: uuid.UUID, now: datetime
    ) -> tuple[str, datetime]:
        self._prune(now)
        if len(self._grants) >= MAX_OUTSTANDING:
            oldest = min(self._grants, key=lambda k: self._grants[k].expires_at)
            self._grants.pop(oldest)
        ticket = new_token()
        expires = now + self.ttl
        self._grants[token_digest(ticket)] = TicketGrant(user_id, session_id, expires)
        return ticket, expires

    def redeem(self, ticket: str, now: datetime) -> TicketGrant | None:
        grant = self._grants.pop(token_digest(ticket), None)  # single use, even if expired
        if grant is None or grant.expires_at <= now:
            return None
        return grant

    def _prune(self, now: datetime) -> None:
        for key in [k for k, g in self._grants.items() if g.expires_at <= now]:
            self._grants.pop(key, None)
