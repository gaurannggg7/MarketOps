"""Alert rules: viewers read; operators create/update with optimistic version checks."""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import correlation_id, now_of, runtime_of
from app.auth.deps import CurrentUser, current_user, require_operator
from app.db import get_session
from app.errors import AppError, not_found, version_conflict
from app.models import AlertRule, Instrument, RuleType, ThresholdUnit
from app.schemas.api import ErrorResponse, RuleCreate, RuleOut, RuleUpdate
from app.services.audit import add_audit
from app.services.market_math import fmt

router = APIRouter(prefix="/rules", tags=["rules"])
_ERR: dict[int | str, dict[str, object]] = {
    s: {"model": ErrorResponse} for s in (401, 403, 404, 409, 422)
}

UNITS = {RuleType.STALE: ThresholdUnit.SECONDS, RuleType.WIDE_SPREAD: ThresholdUnit.BPS}
# Inclusive bounds, in each rule type's unit.
BOUNDS = {
    RuleType.STALE: (Decimal(1), Decimal(3600)),
    RuleType.WIDE_SPREAD: (Decimal("0.5"), Decimal(5000)),
}


def rule_out(rule: AlertRule, symbol: str) -> RuleOut:
    return RuleOut(
        id=rule.id,
        instrument_id=rule.instrument_id,
        symbol=symbol,
        rule_type=rule.rule_type,
        threshold=fmt(rule.threshold.normalize()),
        unit=rule.unit,
        enabled=rule.enabled,
        version=rule.version,
        updated_at=rule.updated_at,
    )


def validate_threshold(rule_type: RuleType, threshold: Decimal) -> Decimal:
    lo, hi = BOUNDS[rule_type]
    unit = "seconds" if rule_type == RuleType.STALE else "basis points"
    if not threshold.is_finite() or threshold < lo or threshold > hi:
        raise AppError(
            422,
            "INVALID_THRESHOLD",
            f"Threshold must be between {lo} and {hi} {unit}.",
            {"field": "threshold", "min": str(lo), "max": str(hi), "unit": UNITS[rule_type].value},
        )
    if threshold != threshold.quantize(Decimal("0.01")):
        raise AppError(
            422, "INVALID_THRESHOLD", "Use at most two decimal places.", {"field": "threshold"}
        )
    return threshold


def _enabled_conflict(rule_type: RuleType) -> AppError:
    return AppError(
        409,
        "RULE_ALREADY_ENABLED",
        f"This instrument already has an enabled {rule_type.value} rule. Disable it "
        "or edit its threshold instead.",
    )


@router.get("", response_model=list[RuleOut], responses=_ERR)
async def list_rules(
    instrument_id: uuid.UUID | None = None,
    rule_type: RuleType | None = None,
    enabled: bool | None = None,
    limit: int = Query(default=500, ge=1, le=1000),
    _: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> list[RuleOut]:
    stmt = select(AlertRule, Instrument.symbol).join(
        Instrument, Instrument.id == AlertRule.instrument_id
    )
    if instrument_id:
        stmt = stmt.where(AlertRule.instrument_id == instrument_id)
    if rule_type:
        stmt = stmt.where(AlertRule.rule_type == rule_type)
    if enabled is not None:
        stmt = stmt.where(AlertRule.enabled == enabled)
    rows = (
        await db.execute(
            stmt.order_by(Instrument.symbol, AlertRule.rule_type, AlertRule.id).limit(limit)
        )
    ).all()
    return [rule_out(r, sym) for r, sym in rows]


@router.post("", response_model=RuleOut, status_code=201, responses=_ERR)
async def create_rule(
    body: RuleCreate,
    request: Request,
    user: CurrentUser = Depends(require_operator),
    db: AsyncSession = Depends(get_session),
) -> RuleOut:
    inst = await db.get(Instrument, body.instrument_id)
    if inst is None:
        raise not_found("Instrument")
    threshold = validate_threshold(body.rule_type, body.threshold)
    now = now_of(request)
    rule = AlertRule(
        instrument_id=inst.id,
        rule_type=body.rule_type,
        threshold=threshold,
        unit=UNITS[body.rule_type],
        enabled=body.enabled,
        version=1,
        created_by=user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(rule)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise _enabled_conflict(body.rule_type) from None
    add_audit(
        db,
        actor_id=user.id,
        action="RULE_CREATED",
        entity_type="alert_rule",
        entity_id=rule.id,
        correlation_id=correlation_id(request),
        at=now,
        after={
            "threshold": fmt(threshold),
            "enabled": body.enabled,
            "rule_type": body.rule_type.value,
        },
    )
    await db.commit()
    runtime_of(request).evaluator.invalidate()
    return rule_out(rule, inst.symbol)


@router.patch("/{rule_id}", response_model=RuleOut, responses=_ERR)
async def update_rule(
    rule_id: uuid.UUID,
    body: RuleUpdate,
    request: Request,
    user: CurrentUser = Depends(require_operator),
    db: AsyncSession = Depends(get_session),
) -> RuleOut:
    rule = (
        await db.execute(select(AlertRule).where(AlertRule.id == rule_id).with_for_update())
    ).scalar_one_or_none()
    if rule is None:
        raise not_found("Rule")
    if rule.version != body.version:
        raise version_conflict("rule", rule.version)
    if body.threshold is None and body.enabled is None:
        raise AppError(422, "NO_CHANGES", "Change the threshold or enabled state, then save.")
    before = {"threshold": fmt(rule.threshold), "enabled": rule.enabled, "version": rule.version}
    if body.threshold is not None:
        rule.threshold = validate_threshold(rule.rule_type, body.threshold)
    if body.enabled is not None:
        rule.enabled = body.enabled
    rule_type = rule.rule_type  # attributes expire on rollback; capture for the error path
    rule.version += 1
    rule.updated_at = now_of(request)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise _enabled_conflict(rule_type) from None
    add_audit(
        db,
        actor_id=user.id,
        action="RULE_UPDATED",
        entity_type="alert_rule",
        entity_id=rule.id,
        correlation_id=correlation_id(request),
        at=rule.updated_at,
        before=before,
        after={"threshold": fmt(rule.threshold), "enabled": rule.enabled, "version": rule.version},
    )
    await db.commit()
    runtime_of(request).evaluator.invalidate()
    symbol = (
        await db.execute(select(Instrument.symbol).where(Instrument.id == rule.instrument_id))
    ).scalar_one()
    return rule_out(rule, symbol)
