"""Audit rows are added to the caller's transaction so they commit or roll back atomically."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent


def add_audit(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | str,
    correlation_id: str,
    at: datetime,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditEvent:
    row = AuditEvent(
        actor_id=actor_id,
        actor_kind="USER" if actor_id else "SYSTEM",
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        before=before,
        after=after,
        correlation_id=correlation_id,
        created_at=at,
    )
    db.add(row)
    return row
