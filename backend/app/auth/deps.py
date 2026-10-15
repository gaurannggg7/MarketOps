"""Request authentication: session cookie → user, CSRF + Origin checks, role guards."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import Depends, Request
from sqlalchemy import ColumnElement, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import digest_matches, token_digest
from app.config import Settings
from app.db import get_session
from app.errors import AppError, forbidden
from app.models import Role, User
from app.models import Session as DbSession

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
LAST_SEEN_WRITE_INTERVAL = timedelta(seconds=60)
# Writes a read-only public-demo session may still make (no business data changes).
PUBLIC_DEMO_ALLOWED_WRITES = frozenset({"/api/v1/auth/logout", "/api/v1/stream/ticket"})


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    display_name: str
    role: Role
    session_id: uuid.UUID
    csrf_token_hash: str
    public_demo: bool = False

    @property
    def is_operator(self) -> bool:
        return self.role == Role.OPERATOR


def unauthenticated() -> AppError:
    return AppError(401, "UNAUTHENTICATED", "Sign in to continue. Your session may have expired.")


def origin_allowed(settings: Settings, origin: str | None) -> bool:
    return origin is not None and origin in settings.allowed_origins


def check_origin(request: Request) -> None:
    settings: Settings = request.app.state.settings
    if not origin_allowed(settings, request.headers.get("origin")):
        raise AppError(
            403, "ORIGIN_REJECTED", "This request did not come from an allowed MarketOps origin."
        )


async def resolve_session(
    db: AsyncSession, settings: Settings, token: str | None, now: datetime
) -> CurrentUser | None:
    """Return the active session's user, applying idle and absolute expiry."""
    if not token:
        return None
    return await _resolve(db, settings, DbSession.token_hash == token_digest(token), now)


async def resolve_session_by_id(
    db: AsyncSession, settings: Settings, session_id: uuid.UUID, now: datetime
) -> CurrentUser | None:
    """Same checks as resolve_session, for a session identified by a redeemed stream ticket."""
    return await _resolve(db, settings, DbSession.id == session_id, now)


async def _resolve(
    db: AsyncSession, settings: Settings, condition: ColumnElement[bool], now: datetime
) -> CurrentUser | None:
    row = (
        await db.execute(
            select(DbSession, User).join(User, User.id == DbSession.user_id).where(condition)
        )
    ).first()
    if row is None:
        return None
    sess, user = row
    idle_deadline = sess.last_seen_at + timedelta(minutes=settings.session_idle_minutes)
    if sess.revoked_at is not None or not user.is_active or now >= sess.expires_at:
        return None
    if now >= idle_deadline:
        return None
    if now - sess.last_seen_at >= LAST_SEEN_WRITE_INTERVAL:
        await db.execute(update(DbSession).where(DbSession.id == sess.id).values(last_seen_at=now))
        await db.commit()
    return CurrentUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        session_id=sess.id,
        csrf_token_hash=sess.csrf_token_hash,
        public_demo=sess.is_public_demo,
    )


async def current_user(request: Request, db: AsyncSession = Depends(get_session)) -> CurrentUser:
    settings: Settings = request.app.state.settings
    user = await resolve_session(
        db,
        settings,
        request.cookies.get(settings.session_cookie_name),
        request.app.state.clock.now(),
    )
    if user is None:
        raise unauthenticated()
    if request.method in UNSAFE_METHODS:
        check_origin(request)
        csrf = request.headers.get("x-csrf-token", "")
        if not csrf or not digest_matches(csrf, user.csrf_token_hash):
            raise AppError(
                403,
                "CSRF_REJECTED",
                "Security token missing or expired. Reload the page and retry.",
            )
        if user.public_demo and request.url.path not in PUBLIC_DEMO_ALLOWED_WRITES:
            raise AppError(
                403,
                "PUBLIC_DEMO_READ_ONLY",
                "This is the read-only public demo. Changes are disabled; the automated demo "
                "operator runs scenarios and incident actions for you to watch.",
            )
    request.state.user_id = str(user.id)
    return user


async def require_operator(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not user.is_operator:
        raise forbidden("Viewers have read-only access. Ask an operator to make this change.")
    return user
