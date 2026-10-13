"""Incident lifecycle. Every mutation, its audit row, and episode updates commit atomically.

State machine: OPEN → ACKNOWLEDGED → RESOLVED. Resolution requires a prior acknowledgment, a
recovered market condition, and a non-blank note. System condition changes (breach/recovery)
do not bump ``version``; ``version`` guards user-editable state (status, assignee, resolution).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.errors import AppError, not_found, version_conflict
from app.models import (
    AlertEpisode,
    Incident,
    IncidentComment,
    IncidentStatus,
    MarketEvent,
    Role,
    RuleType,
    Severity,
    User,
)
from app.services.audit import add_audit
from app.services.market_math import fmt

MAX_NOTE_LENGTH = 4000


@dataclass(frozen=True)
class RuleRef:
    id: uuid.UUID
    instrument_id: uuid.UUID
    symbol: str
    rule_type: RuleType
    threshold: Decimal
    version: int
    enabled: bool = True


@dataclass(frozen=True)
class BreachOutcome:
    incident_id: uuid.UUID | None
    created: bool
    rebreached: bool


SEVERITY = {RuleType.STALE: Severity.HIGH, RuleType.WIDE_SPREAD: Severity.MEDIUM}


def _reason(rule: RuleRef, evidence: dict[str, Any]) -> str:
    if rule.rule_type == RuleType.STALE:
        return (
            f"{rule.symbol}: no quote received for {evidence.get('age_seconds')}s "
            f"(threshold {fmt(rule.threshold)}s)"
        )
    return (
        f"{rule.symbol}: spread {evidence.get('spread_bps')} bps exceeds "
        f"threshold {fmt(rule.threshold)} bps"
    )


def _breach_event(rule: RuleRef, kind: str, at: datetime, evidence: dict[str, Any]) -> MarketEvent:
    suffix = "STALE" if rule.rule_type == RuleType.STALE else "SPREAD"
    return MarketEvent(
        instrument_id=rule.instrument_id,
        event_type=f"{suffix}_{kind}",
        observed_at=at,
        evidence={**evidence, "rule_id": str(rule.id), "rule_version": rule.version},
    )


async def _unresolved_for_update(db: AsyncSession, rule_id: uuid.UUID) -> Incident | None:
    return (
        await db.execute(
            select(Incident)
            .where(Incident.rule_id == rule_id, Incident.status != IncidentStatus.RESOLVED)
            .with_for_update()
        )
    ).scalar_one_or_none()


async def record_breach(
    db: AsyncSession, rule: RuleRef, evidence: dict[str, Any], at: datetime, correlation_id: str
) -> BreachOutcome:
    """Open an incident for a breach, or mark an existing unresolved incident active again.

    Two concurrent callers can both see "no unresolved incident"; the partial unique index
    ``uq_incidents_one_unresolved_per_rule`` rejects the second insert, which then returns the
    winner's incident instead of creating a duplicate.
    """
    existing = await _unresolved_for_update(db, rule.id)
    if existing is not None:
        if existing.condition_active:
            await db.rollback()
            return BreachOutcome(existing.id, created=False, rebreached=False)
        episode = AlertEpisode(
            rule_id=rule.id,
            rule_version=rule.version,
            breached_at=at,
            trigger_evidence=evidence,
            incident_id=existing.id,
        )
        db.add(episode)
        existing.condition_active = True
        existing.condition_changed_at = at
        existing.latest_evidence = evidence
        existing.breach_count += 1
        existing.updated_at = at
        db.add(_breach_event(rule, "BREACH", at, evidence))
        add_audit(
            db,
            actor_id=None,
            action="CONDITION_REBREACHED",
            entity_type="incident",
            entity_id=existing.id,
            correlation_id=correlation_id,
            at=at,
            before={"condition_active": False},
            after={"condition_active": True, **evidence},
        )
        await db.commit()
        return BreachOutcome(existing.id, created=False, rebreached=True)

    episode = AlertEpisode(
        rule_id=rule.id, rule_version=rule.version, breached_at=at, trigger_evidence=evidence
    )
    db.add(episode)
    await db.flush()
    incident = Incident(
        rule_id=rule.id,
        rule_version=rule.version,
        instrument_id=rule.instrument_id,
        episode_id=episode.id,
        incident_type=rule.rule_type,
        status=IncidentStatus.OPEN,
        severity=SEVERITY[rule.rule_type],
        trigger_reason=_reason(rule, evidence),
        trigger_evidence=evidence,
        latest_evidence=evidence,
        condition_active=True,
        condition_changed_at=at,
        breach_count=1,
        opened_at=at,
        version=1,
        updated_at=at,
    )
    db.add(incident)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        winner = (
            await db.execute(
                select(Incident.id).where(
                    Incident.rule_id == rule.id, Incident.status != IncidentStatus.RESOLVED
                )
            )
        ).scalar_one_or_none()
        await db.rollback()
        return BreachOutcome(winner, created=False, rebreached=False)
    episode.incident_id = incident.id
    db.add(_breach_event(rule, "BREACH", at, evidence))
    add_audit(
        db,
        actor_id=None,
        action="INCIDENT_OPENED",
        entity_type="incident",
        entity_id=incident.id,
        correlation_id=correlation_id,
        at=at,
        after={
            "status": "OPEN",
            "rule_version": rule.version,
            "trigger_reason": incident.trigger_reason,
            **evidence,
        },
    )
    await db.commit()
    return BreachOutcome(incident.id, created=True, rebreached=False)


async def record_recovery(
    db: AsyncSession, rule: RuleRef, evidence: dict[str, Any], at: datetime, correlation_id: str
) -> uuid.UUID | None:
    """Mark an unresolved incident's condition as recovered. Never resolves the incident."""
    incident = await _unresolved_for_update(db, rule.id)
    if incident is None or not incident.condition_active:
        await db.rollback()
        return None
    episode = (
        await db.execute(
            select(AlertEpisode)
            .where(AlertEpisode.incident_id == incident.id, AlertEpisode.recovered_at.is_(None))
            .order_by(AlertEpisode.breached_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if episode is not None:
        episode.recovered_at = at
        episode.recovery_evidence = evidence
    incident.condition_active = False
    incident.condition_changed_at = at
    incident.latest_evidence = evidence
    incident.updated_at = at
    db.add(_breach_event(rule, "RECOVERY", at, evidence))
    add_audit(
        db,
        actor_id=None,
        action="CONDITION_RECOVERED",
        entity_type="incident",
        entity_id=incident.id,
        correlation_id=correlation_id,
        at=at,
        before={"condition_active": True},
        after={"condition_active": False, **evidence},
    )
    await db.commit()
    return incident.id


# ---- user actions ------------------------------------------------------------------------


async def _load_for_update(db: AsyncSession, incident_id: uuid.UUID) -> Incident:
    incident = (
        await db.execute(select(Incident).where(Incident.id == incident_id).with_for_update())
    ).scalar_one_or_none()
    if incident is None:
        raise not_found("Incident")
    return incident


def _check_version(incident: Incident, expected: int) -> None:
    if incident.version != expected:
        raise version_conflict("incident", incident.version)


def _transition_error(message: str, incident: Incident) -> AppError:
    return AppError(409, "INVALID_TRANSITION", message, {"status": incident.status.value})


async def acknowledge(
    db: AsyncSession,
    incident_id: uuid.UUID,
    version: int,
    user: CurrentUser,
    at: datetime,
    correlation_id: str,
) -> Incident:
    incident = await _load_for_update(db, incident_id)
    _check_version(incident, version)
    if incident.status != IncidentStatus.OPEN:
        raise _transition_error(
            f"Only OPEN incidents can be acknowledged; this one is {incident.status.value}.",
            incident,
        )
    before = {"status": incident.status.value, "assignee_id": _s(incident.assignee_id)}
    incident.status = IncidentStatus.ACKNOWLEDGED
    incident.acknowledged_at = at
    incident.acknowledged_by = user.id
    if incident.assignee_id is None:
        incident.assignee_id = user.id
    incident.version += 1
    incident.updated_at = at
    add_audit(
        db,
        actor_id=user.id,
        action="INCIDENT_ACKNOWLEDGED",
        entity_type="incident",
        entity_id=incident.id,
        correlation_id=correlation_id,
        at=at,
        before=before,
        after={"status": "ACKNOWLEDGED", "assignee_id": _s(incident.assignee_id)},
    )
    await db.commit()
    return incident


async def assign(
    db: AsyncSession,
    incident_id: uuid.UUID,
    version: int,
    assignee_id: uuid.UUID | None,
    user: CurrentUser,
    at: datetime,
    correlation_id: str,
) -> Incident:
    incident = await _load_for_update(db, incident_id)
    _check_version(incident, version)
    if incident.status == IncidentStatus.RESOLVED:
        raise _transition_error("Resolved incidents cannot be reassigned.", incident)
    if assignee_id is not None:
        assignee = await db.get(User, assignee_id)
        if assignee is None or not assignee.is_active or assignee.role != Role.OPERATOR:
            raise AppError(
                422,
                "INVALID_ASSIGNEE",
                "Incidents can only be assigned to an active operator.",
            )
    before = {"assignee_id": _s(incident.assignee_id)}
    incident.assignee_id = assignee_id
    incident.version += 1
    incident.updated_at = at
    add_audit(
        db,
        actor_id=user.id,
        action="INCIDENT_ASSIGNED",
        entity_type="incident",
        entity_id=incident.id,
        correlation_id=correlation_id,
        at=at,
        before=before,
        after={"assignee_id": _s(assignee_id)},
    )
    await db.commit()
    return incident


async def add_comment(
    db: AsyncSession,
    incident_id: uuid.UUID,
    body: str,
    user: CurrentUser,
    at: datetime,
    correlation_id: str,
) -> IncidentComment:
    text_body = body.strip()
    if not text_body:
        raise AppError(422, "EMPTY_COMMENT", "Write a comment before posting.")
    incident = await _load_for_update(db, incident_id)
    comment = IncidentComment(
        incident_id=incident.id, author_id=user.id, body=text_body, created_at=at
    )
    db.add(comment)
    await db.flush()
    add_audit(
        db,
        actor_id=user.id,
        action="COMMENT_ADDED",
        entity_type="incident",
        entity_id=incident.id,
        correlation_id=correlation_id,
        at=at,
        after={"comment_id": str(comment.id), "length": len(text_body)},
    )
    await db.commit()
    return comment


async def resolve(
    db: AsyncSession,
    incident_id: uuid.UUID,
    version: int,
    note: str,
    user: CurrentUser,
    at: datetime,
    correlation_id: str,
) -> Incident:
    incident = await _load_for_update(db, incident_id)
    _check_version(incident, version)
    if incident.status == IncidentStatus.OPEN:
        raise _transition_error("Acknowledge the incident before resolving it.", incident)
    if incident.status == IncidentStatus.RESOLVED:
        raise _transition_error("This incident is already resolved.", incident)
    if incident.condition_active:
        raise AppError(
            409,
            "CONDITION_ACTIVE",
            "The market condition is still active. Wait for the feed to recover (or run the "
            "recovery scenario), then resolve.",
            {"condition_active": True},
        )
    note_text = note.strip()
    if not note_text:
        raise AppError(422, "RESOLUTION_NOTE_REQUIRED", "Describe the resolution before resolving.")
    incident.status = IncidentStatus.RESOLVED
    incident.resolved_at = at
    incident.resolved_by = user.id
    incident.resolution_note = note_text
    incident.version += 1
    incident.updated_at = at
    add_audit(
        db,
        actor_id=user.id,
        action="INCIDENT_RESOLVED",
        entity_type="incident",
        entity_id=incident.id,
        correlation_id=correlation_id,
        at=at,
        before={"status": "ACKNOWLEDGED"},
        after={"status": "RESOLVED", "resolution_note": note_text},
    )
    await db.commit()
    return incident


def _s(value: uuid.UUID | None) -> str | None:
    return str(value) if value else None
