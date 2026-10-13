"""Owner-scoped watchlists. Any authenticated user (viewer or operator) manages their own."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import now_of
from app.auth.deps import CurrentUser, current_user
from app.db import get_session
from app.errors import AppError, not_found
from app.models import Instrument, Watchlist, WatchlistItem
from app.schemas.api import ErrorResponse, WatchlistCreate, WatchlistOut, WatchlistUpdate

router = APIRouter(prefix="/watchlists", tags=["watchlists"])
_ERR: dict[int | str, dict[str, object]] = {
    s: {"model": ErrorResponse} for s in (401, 403, 404, 409, 422)
}
MAX_WATCHLISTS = 20


async def owned_watchlist(
    db: AsyncSession, watchlist_id: uuid.UUID, user: CurrentUser
) -> Watchlist:
    wl = await db.get(Watchlist, watchlist_id)
    # Another user's watchlist is reported as not found so its existence is not disclosed.
    if wl is None or wl.owner_id != user.id:
        raise not_found("Watchlist")
    return wl


async def _out(db: AsyncSession, wl: Watchlist) -> WatchlistOut:
    ids = (
        (
            await db.execute(
                select(WatchlistItem.instrument_id)
                .where(WatchlistItem.watchlist_id == wl.id)
                .order_by(WatchlistItem.added_at, WatchlistItem.id)
            )
        )
        .scalars()
        .all()
    )
    return WatchlistOut(
        id=wl.id,
        name=wl.name,
        created_at=wl.created_at,
        updated_at=wl.updated_at,
        instrument_ids=list(ids),
    )


def _duplicate_name(name: str) -> AppError:
    return AppError(
        409, "DUPLICATE_NAME", f"You already have a watchlist named '{name}'. Choose another name."
    )


@router.get("", response_model=list[WatchlistOut], responses=_ERR)
async def list_watchlists(
    user: CurrentUser = Depends(current_user), db: AsyncSession = Depends(get_session)
) -> list[WatchlistOut]:
    rows = (
        (
            await db.execute(
                select(Watchlist)
                .where(Watchlist.owner_id == user.id)
                .order_by(Watchlist.created_at, Watchlist.id)
            )
        )
        .scalars()
        .all()
    )
    return [await _out(db, wl) for wl in rows]


@router.post("", response_model=WatchlistOut, status_code=201, responses=_ERR)
async def create_watchlist(
    body: WatchlistCreate,
    request: Request,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> WatchlistOut:
    count = (
        await db.execute(select(func.count()).where(Watchlist.owner_id == user.id))
    ).scalar_one()
    if count >= MAX_WATCHLISTS:
        raise AppError(
            409,
            "LIMIT_REACHED",
            f"You can keep up to {MAX_WATCHLISTS} watchlists. Delete one first.",
        )
    now = now_of(request)
    wl = Watchlist(owner_id=user.id, name=body.name, created_at=now, updated_at=now)
    db.add(wl)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _duplicate_name(body.name) from None
    return await _out(db, wl)


@router.patch("/{watchlist_id}", response_model=WatchlistOut, responses=_ERR)
async def rename_watchlist(
    watchlist_id: uuid.UUID,
    body: WatchlistUpdate,
    request: Request,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> WatchlistOut:
    wl = await owned_watchlist(db, watchlist_id, user)
    wl.name = body.name
    wl.updated_at = now_of(request)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _duplicate_name(body.name) from None
    return await _out(db, wl)


@router.delete("/{watchlist_id}", status_code=204, responses=_ERR)
async def delete_watchlist(
    watchlist_id: uuid.UUID,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> Response:
    wl = await owned_watchlist(db, watchlist_id, user)
    await db.delete(wl)
    await db.commit()
    return Response(status_code=204)


@router.post("/{watchlist_id}/items/{instrument_id}", response_model=WatchlistOut, responses=_ERR)
async def add_item(
    watchlist_id: uuid.UUID,
    instrument_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> WatchlistOut:
    """Idempotent: adding an existing member succeeds without creating a duplicate."""
    wl = await owned_watchlist(db, watchlist_id, user)
    if await db.get(Instrument, instrument_id) is None:
        raise not_found("Instrument")
    await db.execute(
        pg_insert(WatchlistItem)
        .values(id=uuid.uuid4(), watchlist_id=wl.id, instrument_id=instrument_id)
        .on_conflict_do_nothing(constraint="uq_watchlist_items_pair")
    )
    wl.updated_at = now_of(request)
    await db.commit()
    return await _out(db, wl)


@router.delete("/{watchlist_id}/items/{instrument_id}", response_model=WatchlistOut, responses=_ERR)
async def remove_item(
    watchlist_id: uuid.UUID,
    instrument_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> WatchlistOut:
    """Idempotent: removing a non-member succeeds."""
    wl = await owned_watchlist(db, watchlist_id, user)
    await db.execute(
        delete(WatchlistItem).where(
            WatchlistItem.watchlist_id == wl.id, WatchlistItem.instrument_id == instrument_id
        )
    )
    wl.updated_at = now_of(request)
    await db.commit()
    return await _out(db, wl)
