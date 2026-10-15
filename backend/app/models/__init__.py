"""SQLAlchemy ORM models. Every table is created by Alembic migrations, never `create_all`."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


PRICE = Numeric(18, 6)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Role(enum.StrEnum):
    VIEWER = "VIEWER"
    OPERATOR = "OPERATOR"


class RuleType(enum.StrEnum):
    STALE = "STALE"
    WIDE_SPREAD = "WIDE_SPREAD"


class ThresholdUnit(enum.StrEnum):
    SECONDS = "SECONDS"
    BPS = "BPS"


class IncidentStatus(enum.StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class Severity(enum.StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


def _enum(e: type[enum.StrEnum], name: str) -> Enum:
    return Enum(e, name=name, values_callable=lambda x: [m.value for m in x])


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(_enum(Role, "user_role"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created_at()


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    # SHA-256 of the opaque cookie token; the plaintext token is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    # SHA-256 of the per-session CSRF token returned to the client in response bodies.
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Anonymous "explore the demo" sessions: always read-only, regardless of the user's role.
    is_public_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )


class Instrument(Base):
    __tablename__ = "instruments"
    id: Mapped[uuid.UUID] = _uuid_pk()
    symbol: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    asset_label: Mapped[str] = mapped_column(String(40), nullable=False)
    base_price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    __table_args__ = (CheckConstraint("base_price > 0", name="ck_instruments_base_price_pos"),)


class QuoteSample(Base):
    __tablename__ = "quote_samples"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instrument_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    bid: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    ask: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("bid > 0 AND ask > 0", name="ck_quote_samples_positive"),
        CheckConstraint("volume >= 0", name="ck_quote_samples_volume"),
        Index("ix_quote_samples_instrument_time_id", "instrument_id", "received_time", "id"),
        Index("ix_quote_samples_received_time", "received_time"),
    )


class MarketEvent(Base):
    __tablename__ = "market_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("instruments.id"))
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    __table_args__ = (
        Index("ix_market_events_observed_id", "observed_at", "id"),
        Index("ix_market_events_instrument_observed", "instrument_id", "observed_at", "id"),
        Index("ix_market_events_type_observed", "event_type", "observed_at", "id"),
    )


class Watchlist(Base):
    __tablename__ = "watchlists"
    id: Mapped[uuid.UUID] = _uuid_pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_watchlists_owner_name"),)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    id: Mapped[uuid.UUID] = _uuid_pk()
    # Membership rows are owned by the watchlist; deleting a watchlist removes its items.
    watchlist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    added_at: Mapped[datetime] = _created_at()
    __table_args__ = (
        UniqueConstraint("watchlist_id", "instrument_id", name="uq_watchlist_items_pair"),
    )


class AlertRule(Base):
    __tablename__ = "alert_rules"
    id: Mapped[uuid.UUID] = _uuid_pk()
    instrument_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    rule_type: Mapped[RuleType] = mapped_column(_enum(RuleType, "rule_type"), nullable=False)
    threshold: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    unit: Mapped[ThresholdUnit] = mapped_column(_enum(ThresholdUnit, "threshold_unit"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        CheckConstraint("threshold > 0", name="ck_alert_rules_threshold_pos"),
        CheckConstraint(
            "(rule_type = 'STALE' AND unit = 'SECONDS') OR "
            "(rule_type = 'WIDE_SPREAD' AND unit = 'BPS')",
            name="ck_alert_rules_unit_matches_type",
        ),
        # V1 invariant: at most one *enabled* rule per instrument/type.
        Index(
            "uq_alert_rules_one_enabled",
            "instrument_id",
            "rule_type",
            unique=True,
            postgresql_where=text("enabled"),
        ),
    )


class AlertEpisode(Base):
    __tablename__ = "alert_episodes"
    id: Mapped[uuid.UUID] = _uuid_pk()
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alert_rules.id"), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    breached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recovery_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("incidents.id", use_alter=True, name="fk_alert_episodes_incident")
    )
    __table_args__ = (Index("ix_alert_episodes_rule_breached", "rule_id", "breached_at"),)


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[uuid.UUID] = _uuid_pk()
    number: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        nullable=False,
        server_default=text("nextval('incident_number_seq')"),
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alert_rules.id"), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    instrument_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alert_episodes.id"), nullable=False)
    incident_type: Mapped[RuleType] = mapped_column(_enum(RuleType, "rule_type"), nullable=False)
    status: Mapped[IncidentStatus] = mapped_column(
        _enum(IncidentStatus, "incident_status"), nullable=False
    )
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "incident_severity"))
    trigger_reason: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    latest_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    condition_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    condition_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    breach_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        # At most one unresolved incident per rule, enforced by PostgreSQL.
        Index(
            "uq_incidents_one_unresolved_per_rule",
            "rule_id",
            unique=True,
            postgresql_where=text("status <> 'RESOLVED'"),
        ),
        Index("ix_incidents_status_opened", "status", "opened_at"),
        Index("ix_incidents_instrument", "instrument_id"),
        CheckConstraint(
            "status <> 'RESOLVED' OR (resolution_note IS NOT NULL"
            " AND length(btrim(resolution_note)) > 0"
            " AND acknowledged_at IS NOT NULL AND resolved_at IS NOT NULL"
            " AND NOT condition_active)",
            name="ck_incidents_resolution_requirements",
        ),
        CheckConstraint(
            "status = 'OPEN' OR acknowledged_at IS NOT NULL",
            name="ck_incidents_ack_before_progress",
        ),
    )


class IncidentComment(Base):
    __tablename__ = "incident_comments"
    id: Mapped[uuid.UUID] = _uuid_pk()
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id"), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("length(btrim(body)) > 0", name="ck_incident_comments_body"),
        Index("ix_incident_comments_incident_created", "incident_id", "created_at"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_kind: Mapped[str] = mapped_column(String(10), nullable=False)  # USER | SYSTEM
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("actor_kind IN ('USER', 'SYSTEM')", name="ck_audit_events_actor_kind"),
        CheckConstraint(
            "(actor_kind = 'USER') = (actor_id IS NOT NULL)", name="ck_audit_events_actor_id"
        ),
        Index("ix_audit_events_entity", "entity_type", "entity_id", "created_at", "id"),
    )
