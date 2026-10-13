"""Incident workspace endpoints. Viewers read; operators acknowledge, assign, comment, resolve."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import UnaryExpression, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import correlation_id, now_of, runtime_of
from app.api.rules import rule_out
from app.auth.deps import CurrentUser, current_user, require_operator
from app.db import get_session
from app.errors import not_found
from app.models import (
    AlertRule,
    AuditEvent,
    Incident,
    IncidentComment,
    IncidentStatus,
    Instrument,
    RuleType,
    Severity,
    User,
)
from app.schemas.api import (
    AssignmentRequest,
    CommentCreate,
    CommentOut,
    ErrorResponse,
    IncidentDetail,
    IncidentOut,
    IncidentPage,
    OperatorOut,
    ResolveRequest,
    Timeline,
    TimelineEntry,
    VersionedAction,
)
from app.services import incidents as svc

router = APIRouter(prefix="/incidents", tags=["incidents"])
_ERR: dict[int | str, dict[str, object]] = {
    s: {"model": ErrorResponse} for s in (401, 403, 404, 409, 422)
}


async def _users(db: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, OperatorOut]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(wanted)))).scalars().all()
    return {u.id: OperatorOut.model_validate(u) for u in rows}


def _summary(i: Incident, symbol: str, users: dict[uuid.UUID, OperatorOut]) -> IncidentOut:
    return IncidentOut(
        id=i.id,
        number=i.number,
        rule_id=i.rule_id,
        rule_version=i.rule_version,
        instrument_id=i.instrument_id,
        symbol=symbol,
        incident_type=i.incident_type,
        status=i.status,
        severity=i.severity,
        trigger_reason=i.trigger_reason,
        condition_active=i.condition_active,
        condition_changed_at=i.condition_changed_at,
        breach_count=i.breach_count,
        assignee=users.get(i.assignee_id) if i.assignee_id else None,
        opened_at=i.opened_at,
        acknowledged_at=i.acknowledged_at,
        resolved_at=i.resolved_at,
        version=i.version,
        updated_at=i.updated_at,
    )


async def _detail(db: AsyncSession, incident_id: uuid.UUID) -> IncidentDetail:
    row = (
        await db.execute(
            select(Incident, Instrument.symbol, AlertRule)
            .join(Instrument, Instrument.id == Incident.instrument_id)
            .join(AlertRule, AlertRule.id == Incident.rule_id)
            .where(Incident.id == incident_id)
        )
    ).first()
    if row is None:
        raise not_found("Incident")
    inc, symbol, rule = row
    users = await _users(db, {inc.assignee_id, inc.acknowledged_by, inc.resolved_by})
    base = _summary(inc, symbol, users)
    return IncidentDetail(
        **base.model_dump(),
        trigger_evidence=inc.trigger_evidence,
        latest_evidence=inc.latest_evidence,
        resolution_note=inc.resolution_note,
        acknowledged_by=users.get(inc.acknowledged_by) if inc.acknowledged_by else None,
        resolved_by=users.get(inc.resolved_by) if inc.resolved_by else None,
        rule=rule_out(rule, symbol),
    )


IncidentSort = Literal["-opened_at", "opened_at", "-number", "number", "severity"]


@router.get("", response_model=IncidentPage, responses=_ERR)
async def list_incidents(
    status: list[IncidentStatus] | None = Query(default=None),
    severity: list[Severity] | None = Query(default=None),
    incident_type: RuleType | None = Query(default=None, alias="type"),
    instrument_id: uuid.UUID | None = None,
    symbol: str | None = Query(default=None, max_length=16),
    sort: IncidentSort = "-opened_at",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    _: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> IncidentPage:
    stmt = select(Incident, Instrument.symbol).join(
        Instrument, Instrument.id == Incident.instrument_id
    )
    if status:
        stmt = stmt.where(Incident.status.in_(status))
    if severity:
        stmt = stmt.where(Incident.severity.in_(severity))
    if incident_type:
        stmt = stmt.where(Incident.incident_type == incident_type)
    if instrument_id:
        stmt = stmt.where(Incident.instrument_id == instrument_id)
    if symbol:
        stmt = stmt.where(func.upper(Instrument.symbol) == symbol.strip().upper())
    total = int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    orders: dict[str, list[UnaryExpression[Any]]] = {
        "-opened_at": [Incident.opened_at.desc(), Incident.number.desc()],
        "opened_at": [Incident.opened_at.asc(), Incident.number.asc()],
        "-number": [Incident.number.desc()],
        "number": [Incident.number.asc()],
        "severity": [Incident.severity.asc(), Incident.opened_at.desc(), Incident.number.desc()],
    }
    order = orders[sort]
    rows = (await db.execute(stmt.order_by(*order).offset(offset).limit(limit))).all()
    users = await _users(db, {i.assignee_id for i, _ in rows})
    return IncidentPage(
        items=[_summary(i, sym, users) for i, sym in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{incident_id}", response_model=IncidentDetail, responses=_ERR)
async def get_incident(
    incident_id: uuid.UUID,
    _: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> IncidentDetail:
    return await _detail(db, incident_id)


@router.post("/{incident_id}/acknowledge", response_model=IncidentDetail, responses=_ERR)
async def acknowledge(
    incident_id: uuid.UUID,
    body: VersionedAction,
    request: Request,
    user: CurrentUser = Depends(require_operator),
    db: AsyncSession = Depends(get_session),
) -> IncidentDetail:
    await svc.acknowledge(
        db, incident_id, body.version, user, now_of(request), correlation_id(request)
    )
    return await _detail(db, incident_id)


@router.patch("/{incident_id}/assignment", response_model=IncidentDetail, responses=_ERR)
async def assign(
    incident_id: uuid.UUID,
    body: AssignmentRequest,
    request: Request,
    user: CurrentUser = Depends(require_operator),
    db: AsyncSession = Depends(get_session),
) -> IncidentDetail:
    await svc.assign(
        db,
        incident_id,
        body.version,
        body.assignee_id,
        user,
        now_of(request),
        correlation_id(request),
    )
    return await _detail(db, incident_id)


@router.post("/{incident_id}/comments", response_model=CommentOut, status_code=201, responses=_ERR)
async def comment(
    incident_id: uuid.UUID,
    body: CommentCreate,
    request: Request,
    user: CurrentUser = Depends(require_operator),
    db: AsyncSession = Depends(get_session),
) -> CommentOut:
    c = await svc.add_comment(
        db, incident_id, body.body, user, now_of(request), correlation_id(request)
    )
    author = OperatorOut(id=user.id, display_name=user.display_name, email=user.email)
    return CommentOut(
        id=c.id, incident_id=c.incident_id, author=author, body=c.body, created_at=c.created_at
    )


@router.post("/{incident_id}/resolve", response_model=IncidentDetail, responses=_ERR)
async def resolve(
    incident_id: uuid.UUID,
    body: ResolveRequest,
    request: Request,
    user: CurrentUser = Depends(require_operator),
    db: AsyncSession = Depends(get_session),
) -> IncidentDetail:
    await svc.resolve(
        db,
        incident_id,
        body.version,
        body.resolution_note,
        user,
        now_of(request),
        correlation_id(request),
    )
    runtime_of(request).evaluator.invalidate()
    return await _detail(db, incident_id)


@router.get("/{incident_id}/timeline", response_model=Timeline, responses=_ERR)
async def timeline(
    incident_id: uuid.UUID,
    _: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> Timeline:
    if await db.get(Incident, incident_id) is None:
        raise not_found("Incident")
    audits = (
        (
            await db.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_type == "incident",
                    AuditEvent.entity_id == str(incident_id),
                    AuditEvent.action != "COMMENT_ADDED",
                )
            )
        )
        .scalars()
        .all()
    )
    comments = (
        (
            await db.execute(
                select(IncidentComment).where(IncidentComment.incident_id == incident_id)
            )
        )
        .scalars()
        .all()
    )
    users = await _users(db, {a.actor_id for a in audits} | {c.author_id for c in comments})
    entries: list[tuple[tuple[datetime, int, int, str], TimelineEntry]] = []
    for a in audits:
        entries.append(
            (
                (a.created_at, 0, a.id, ""),
                TimelineEntry(
                    kind="AUDIT",
                    id=str(a.id),
                    at=a.created_at,
                    action=a.action,
                    actor=users.get(a.actor_id) if a.actor_id else None,
                    actor_kind="USER" if a.actor_kind == "USER" else "SYSTEM",
                    before=a.before,
                    after=a.after,
                    correlation_id=a.correlation_id,
                ),
            )
        )
    for c in comments:
        entries.append(
            (
                (c.created_at, 1, 0, str(c.id)),
                TimelineEntry(
                    kind="COMMENT",
                    id=str(c.id),
                    at=c.created_at,
                    action="COMMENT_ADDED",
                    actor=users.get(c.author_id),
                    actor_kind="USER",
                    body=c.body,
                ),
            )
        )
    entries.sort(key=lambda e: e[0])
    return Timeline(incident_id=incident_id, entries=[e for _, e in entries])
