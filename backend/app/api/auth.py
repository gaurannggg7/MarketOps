from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import runtime_of
from app.auth.deps import CurrentUser, check_origin, current_user, resolve_session
from app.auth.security import (
    LoginThrottle,
    derive_csrf_token,
    new_token,
    token_digest,
    verify_password,
)
from app.config import Settings
from app.db import get_session
from app.errors import AppError
from app.models import Role, User
from app.models import Session as DbSession
from app.schemas.api import (
    ErrorResponse,
    LoginRequest,
    OperatorOut,
    SessionOut,
    SessionState,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
}


def _set_cookie(response: Response, settings: Settings, token: str, max_age: int) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=SessionOut, responses=_ERRORS)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> SessionOut:
    check_origin(request)  # also blocks login CSRF
    settings: Settings = request.app.state.settings
    throttle: LoginThrottle = request.app.state.login_throttle
    email = body.email.strip().lower()
    key = f"{email}|{request.client.host if request.client else '-'}"
    retry = throttle.retry_after(key)
    if retry:
        raise AppError(
            429,
            "TOO_MANY_ATTEMPTS",
            f"Too many failed sign-in attempts. Try again in {retry} seconds.",
            {"retry_after_seconds": retry},
        )
    user = (
        await db.execute(select(User).where(func.lower(User.email) == email))
    ).scalar_one_or_none()
    if not verify_password(user.password_hash if user else None, body.password) or (
        user is None or not user.is_active
    ):
        throttle.record_failure(key)
        raise AppError(401, "INVALID_CREDENTIALS", "Email or password is incorrect.")
    throttle.reset(key)
    now = request.app.state.clock.now()
    token = new_token()
    csrf = derive_csrf_token(token)
    expires_at = now + timedelta(hours=settings.session_absolute_hours)
    db.add(
        DbSession(
            token_hash=token_digest(token),
            user_id=user.id,
            csrf_token_hash=token_digest(csrf),
            last_seen_at=now,
            expires_at=expires_at,
        )
    )
    await db.commit()
    _set_cookie(response, settings, token, settings.session_absolute_hours * 3600)
    return SessionOut(user=UserOut.model_validate(user), csrf_token=csrf, expires_at=expires_at)


@router.post("/logout", status_code=204, responses=_ERRORS)
async def logout(
    request: Request,
    response: Response,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> Response:
    now = request.app.state.clock.now()
    await db.execute(
        update(DbSession).where(DbSession.id == user.session_id).values(revoked_at=now)
    )
    await db.commit()
    runtime_of(request).hub.disconnect_session(user.session_id)
    settings: Settings = request.app.state.settings
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.status_code = 204
    return response


@router.get("/me", response_model=SessionOut, responses=_ERRORS)
async def me(
    request: Request,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> SessionOut:
    """Profile + CSRF bootstrap so a reloaded page (memory-only CSRF token) can continue."""
    settings: Settings = request.app.state.settings
    sess = await db.get(DbSession, user.session_id)
    db_user = await db.get(User, user.id)
    if sess is None or db_user is None:
        raise AppError(401, "UNAUTHENTICATED", "Sign in to continue.")
    csrf = derive_csrf_token(request.cookies.get(settings.session_cookie_name, ""))
    return SessionOut(
        user=UserOut.model_validate(db_user), csrf_token=csrf, expires_at=sess.expires_at
    )


@router.get("/session", response_model=SessionState)
async def session_state(request: Request, db: AsyncSession = Depends(get_session)) -> SessionState:
    """Same as /me for a signed-in browser, but reports signed-out as 200 instead of 401."""
    settings: Settings = request.app.state.settings
    token = request.cookies.get(settings.session_cookie_name)
    user = await resolve_session(db, settings, token, request.app.state.clock.now())
    demo = settings.public_demo_enabled
    if user is None or token is None:
        return SessionState(authenticated=False, demo_available=demo)
    sess = await db.get(DbSession, user.session_id)
    db_user = await db.get(User, user.id)
    if sess is None or db_user is None:
        return SessionState(authenticated=False, demo_available=demo)
    return SessionState(
        authenticated=True,
        demo_available=demo,
        session=SessionOut(
            user=UserOut.model_validate(db_user),
            csrf_token=derive_csrf_token(token),
            expires_at=sess.expires_at,
            public_demo=sess.is_public_demo,
        ),
    )


@router.post("/demo", response_model=SessionOut, responses=_ERRORS)
async def demo_login(
    request: Request, response: Response, db: AsyncSession = Depends(get_session)
) -> SessionOut:
    """Issue a read-only public-demo session for the viewer account (only when enabled)."""
    settings: Settings = request.app.state.settings
    if not settings.public_demo_enabled:
        raise AppError(404, "NOT_FOUND", "Public demo access is not enabled on this server.")
    check_origin(request)
    limiter: LoginThrottle = request.app.state.demo_throttle
    key = f"demo|{request.client.host if request.client else '-'}"
    retry = limiter.retry_after(key)
    if retry:
        raise AppError(
            429,
            "TOO_MANY_ATTEMPTS",
            f"Too many demo sessions from this address. Try again in {retry} seconds.",
            {"retry_after_seconds": retry},
        )
    limiter.record_failure(key)  # counts every demo session issued to this address
    viewer = (
        await db.execute(
            select(User).where(
                func.lower(User.email) == settings.public_demo_viewer_email.lower(),
                User.role == Role.VIEWER,
                User.is_active,
            )
        )
    ).scalar_one_or_none()
    if viewer is None:
        raise AppError(503, "DEMO_UNAVAILABLE", "The demo viewer account is not configured.")
    now = request.app.state.clock.now()
    token = new_token()
    csrf = derive_csrf_token(token)
    expires_at = now + timedelta(hours=settings.public_demo_session_hours)
    db.add(
        DbSession(
            token_hash=token_digest(token),
            user_id=viewer.id,
            csrf_token_hash=token_digest(csrf),
            last_seen_at=now,
            expires_at=expires_at,
            is_public_demo=True,
        )
    )
    await db.commit()
    _set_cookie(response, settings, token, settings.public_demo_session_hours * 3600)
    return SessionOut(
        user=UserOut.model_validate(viewer),
        csrf_token=csrf,
        expires_at=expires_at,
        public_demo=True,
    )


@router.get("/operators", response_model=list[OperatorOut], responses=_ERRORS)
async def operators(
    _: CurrentUser = Depends(current_user), db: AsyncSession = Depends(get_session)
) -> list[OperatorOut]:
    rows = (
        (
            await db.execute(
                select(User)
                .where(User.role == Role.OPERATOR, User.is_active)
                .order_by(User.display_name)
            )
        )
        .scalars()
        .all()
    )
    return [OperatorOut.model_validate(u) for u in rows]
