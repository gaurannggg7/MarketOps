"""Instruments catalog, market snapshot, sampled history, and the historical events grid."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import Select, UnaryExpression, and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import runtime_of
from app.api.rules import rule_out
from app.auth.deps import CurrentUser, current_user
from app.db import get_session
from app.errors import AppError, not_found
from app.models import (
    AlertRule,
    Incident,
    IncidentStatus,
    Instrument,
    MarketEvent,
    WatchlistItem,
)
from app.schemas.api import (
    ErrorResponse,
    EventOut,
    EventPage,
    HistoryOut,
    HistoryPoint,
    HistoryRange,
    InstrumentDetail,
    InstrumentList,
    InstrumentOut,
    MarketSnapshot,
    QuoteOut,
)
from app.services.market_math import PRICE_QUANTUM, fmt, mid_price, spread_bps

router = APIRouter(tags=["market"])
_ERR: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

# range → (window, bucket seconds). Samples are persisted at most once per second.
HISTORY_RANGES: dict[str, tuple[timedelta, int]] = {
    "5m": (timedelta(minutes=5), 1),
    "15m": (timedelta(minutes=15), 3),
    "1h": (timedelta(hours=1), 10),
}
HISTORY_MAX_POINTS = 600


async def _active_counts(db: AsyncSession) -> dict[uuid.UUID, int]:
    rows = await db.execute(
        select(Incident.instrument_id, func.count())
        .where(Incident.status != IncidentStatus.RESOLVED)
        .group_by(Incident.instrument_id)
    )
    return {iid: int(n) for iid, n in rows.all()}


@router.get("/instruments", response_model=InstrumentList, responses=_ERR)
async def list_instruments(
    search: str | None = Query(default=None, max_length=40),
    watchlist_id: uuid.UUID | None = None,
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> InstrumentList:
    stmt: Select[Instrument] = select(Instrument).where(Instrument.is_active)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(or_(Instrument.symbol.ilike(pattern), Instrument.name.ilike(pattern)))
    if watchlist_id is not None:
        from app.api.watchlists import owned_watchlist  # local import avoids a cycle

        await owned_watchlist(db, watchlist_id, user)
        stmt = stmt.join(WatchlistItem, WatchlistItem.instrument_id == Instrument.id).where(
            WatchlistItem.watchlist_id == watchlist_id
        )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await db.execute(
                stmt.order_by(Instrument.symbol, Instrument.id).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    counts = await _active_counts(db)
    items = [
        InstrumentOut.model_validate(r).model_copy(
            update={"active_incident_count": counts.get(r.id, 0)}
        )
        for r in rows
    ]
    return InstrumentList(items=items, total=int(total))


@router.get("/instruments/{instrument_id}", response_model=InstrumentDetail, responses=_ERR)
async def get_instrument(
    instrument_id: uuid.UUID,
    _: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> InstrumentDetail:
    inst = await db.get(Instrument, instrument_id)
    if inst is None:
        raise not_found("Instrument")
    rules = (
        (
            await db.execute(
                select(AlertRule)
                .where(AlertRule.instrument_id == instrument_id)
                .order_by(AlertRule.rule_type, AlertRule.enabled.desc(), AlertRule.created_at)
            )
        )
        .scalars()
        .all()
    )
    counts = await _active_counts(db)
    return InstrumentDetail(
        id=inst.id,
        symbol=inst.symbol,
        name=inst.name,
        asset_label=inst.asset_label,
        is_active=inst.is_active,
        active_incident_count=counts.get(inst.id, 0),
        rules=[rule_out(r, inst.symbol) for r in rules],
    )


@router.get("/market/snapshot", response_model=MarketSnapshot, responses=_ERR)
async def market_snapshot(
    request: Request, _: CurrentUser = Depends(current_user)
) -> MarketSnapshot:
    rt = runtime_of(request)
    hub = rt.hub
    return MarketSnapshot(
        epoch=hub.epoch,
        seq=hub.seq,
        server_time=rt.clock.now(),
        stale_ids=sorted(hub.stale_ids),
        quotes=[QuoteOut.model_validate(q.wire()) for q in hub.quotes.values()],
    )


@router.get("/instruments/{instrument_id}/history", response_model=HistoryOut, responses=_ERR)
async def instrument_history(
    request: Request,
    instrument_id: uuid.UUID,
    range_: HistoryRange = Query(default="15m", alias="range"),
    _: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> HistoryOut:
    if await db.get(Instrument, instrument_id) is None:
        raise not_found("Instrument")
    window, bucket = HISTORY_RANGES[range_]
    end = runtime_of(request).clock.now()
    start = end - window
    rows = (
        await db.execute(
            text(
                """
                SELECT date_bin(make_interval(secs => :bucket), received_time,
                                TIMESTAMPTZ '2000-01-01 00:00:00+00') AS t,
                       avg(bid) AS bid, avg(ask) AS ask, count(*) AS n
                FROM quote_samples
                WHERE instrument_id = :iid AND received_time >= :start AND received_time < :end
                GROUP BY t ORDER BY t
                LIMIT :max_points
                """
            ),
            {
                "bucket": bucket,
                "iid": instrument_id,
                "start": start,
                "end": end,
                "max_points": HISTORY_MAX_POINTS,
            },
        )
    ).all()
    points = []
    for t, bid_raw, ask_raw, n in rows:
        bid = Decimal(bid_raw).quantize(PRICE_QUANTUM, rounding=ROUND_HALF_EVEN)
        ask = Decimal(ask_raw).quantize(PRICE_QUANTUM, rounding=ROUND_HALF_EVEN)
        points.append(
            HistoryPoint(
                t=t,
                bid=fmt(bid),
                ask=fmt(ask),
                mid=fmt(mid_price(bid, ask)),
                spread_bps=fmt(spread_bps(bid, ask)),
                samples=int(n),
            )
        )
    return HistoryOut(
        instrument_id=instrument_id,
        range=range_,
        resolution_seconds=bucket,
        start=start,
        end=end,
        max_points=HISTORY_MAX_POINTS,
        points=points,
    )


EventSort = Literal["observed_at", "-observed_at", "event_type", "-event_type", "symbol", "-symbol"]
MAX_EVENT_PAGE = 500


@router.get("/events", response_model=EventPage, responses=_ERR)
async def list_events(
    offset: int = Query(default=0, ge=0, le=1_000_000),
    limit: int = Query(default=100, ge=1, le=MAX_EVENT_PAGE),
    sort: EventSort = "-observed_at",
    instrument_id: uuid.UUID | None = None,
    event_type: str | None = Query(default=None, max_length=40, pattern=r"^[A-Z_]+$"),
    since: datetime | None = None,
    until: datetime | None = None,
    _: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> EventPage:
    if since and until and since > until:
        raise AppError(422, "INVALID_RANGE", "'since' must be earlier than 'until'.")
    conds = []
    if instrument_id is not None:
        conds.append(MarketEvent.instrument_id == instrument_id)
    if event_type:
        conds.append(MarketEvent.event_type == event_type)
    if since:
        conds.append(MarketEvent.observed_at >= since)
    if until:
        conds.append(MarketEvent.observed_at < until)
    where = and_(*conds) if conds else None

    count_stmt = select(func.count()).select_from(MarketEvent)
    if where is not None:
        count_stmt = count_stmt.where(where)
    total = int((await db.execute(count_stmt)).scalar_one())

    desc = sort.startswith("-")
    field = sort.lstrip("-")
    column = {
        "observed_at": MarketEvent.observed_at,
        "event_type": MarketEvent.event_type,
        "symbol": Instrument.symbol,
    }[field]
    order: list[UnaryExpression[Any]] = [
        column.desc().nulls_last() if desc else column.asc().nulls_first()
    ]
    # Stable tie-breakers: time then id, always in the requested direction.
    if field != "observed_at":
        order.append(MarketEvent.observed_at.desc() if desc else MarketEvent.observed_at.asc())
    order.append(MarketEvent.id.desc() if desc else MarketEvent.id.asc())
    stmt = select(MarketEvent, Instrument.symbol).outerjoin(
        Instrument, Instrument.id == MarketEvent.instrument_id
    )
    if where is not None:
        stmt = stmt.where(where)
    rows = (await db.execute(stmt.order_by(*order).offset(offset).limit(limit))).all()
    return EventPage(
        items=[
            EventOut(
                id=e.id,
                instrument_id=e.instrument_id,
                symbol=sym,
                event_type=e.event_type,
                observed_at=e.observed_at,
                evidence=e.evidence,
            )
            for e, sym in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )
