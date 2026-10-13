"""Pydantic request/response schemas. Prices and spreads are decimal strings on the wire."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import IncidentStatus, Role, RuleType, Severity, ThresholdUnit


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any | None = None
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


# ---- auth ---------------------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class UserOut(ApiModel):
    id: uuid.UUID
    email: str
    display_name: str
    role: Role


class SessionOut(BaseModel):
    user: UserOut
    csrf_token: str
    expires_at: datetime


class SessionState(BaseModel):
    """Bootstrap probe: 200 whether or not the browser is signed in (avoids 401 console noise)."""

    authenticated: bool
    session: SessionOut | None = None


class OperatorOut(ApiModel):
    id: uuid.UUID
    display_name: str
    email: str


# ---- instruments / market -------------------------------------------------------------------
class InstrumentOut(ApiModel):
    id: uuid.UUID
    symbol: str
    name: str
    asset_label: str
    is_active: bool
    active_incident_count: int = 0


class InstrumentList(BaseModel):
    items: list[InstrumentOut]
    total: int


class RuleOut(ApiModel):
    id: uuid.UUID
    instrument_id: uuid.UUID
    symbol: str
    rule_type: RuleType
    threshold: str
    unit: ThresholdUnit
    enabled: bool
    version: int
    updated_at: datetime


class InstrumentDetail(InstrumentOut):
    rules: list[RuleOut]


class QuoteOut(BaseModel):
    id: uuid.UUID
    symbol: str
    bid: str
    ask: str
    mid: str
    spread_bps: str
    volume: int
    source_time: datetime
    received_time: datetime


class MarketSnapshot(BaseModel):
    epoch: str
    seq: int
    server_time: datetime
    stale_ids: list[uuid.UUID]
    quotes: list[QuoteOut]


HistoryRange = Literal["5m", "15m", "1h"]


class HistoryPoint(BaseModel):
    t: datetime
    bid: str
    ask: str
    mid: str
    spread_bps: str
    samples: int


class HistoryOut(BaseModel):
    instrument_id: uuid.UUID
    range: HistoryRange
    resolution_seconds: int
    start: datetime
    end: datetime
    max_points: int
    points: list[HistoryPoint]


class EventOut(BaseModel):
    id: int
    instrument_id: uuid.UUID | None
    symbol: str | None
    event_type: str
    observed_at: datetime
    evidence: dict[str, Any]


class EventPage(BaseModel):
    items: list[EventOut]
    total: int
    offset: int
    limit: int


# ---- watchlists ---------------------------------------------------------------------------
class WatchlistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be blank")
        return v


class WatchlistUpdate(WatchlistCreate):
    pass


class WatchlistOut(ApiModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    updated_at: datetime
    instrument_ids: list[uuid.UUID]


# ---- rules --------------------------------------------------------------------------------
class RuleCreate(BaseModel):
    instrument_id: uuid.UUID
    rule_type: RuleType
    threshold: Decimal
    enabled: bool = True


class RuleUpdate(BaseModel):
    version: int = Field(ge=1)
    threshold: Decimal | None = None
    enabled: bool | None = None


# ---- incidents ----------------------------------------------------------------------------
class IncidentOut(ApiModel):
    id: uuid.UUID
    number: int
    rule_id: uuid.UUID
    rule_version: int
    instrument_id: uuid.UUID
    symbol: str
    incident_type: RuleType
    status: IncidentStatus
    severity: Severity
    trigger_reason: str
    condition_active: bool
    condition_changed_at: datetime
    breach_count: int
    assignee: OperatorOut | None
    opened_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    version: int
    updated_at: datetime


class IncidentDetail(IncidentOut):
    trigger_evidence: dict[str, Any]
    latest_evidence: dict[str, Any]
    resolution_note: str | None
    acknowledged_by: OperatorOut | None
    resolved_by: OperatorOut | None
    rule: RuleOut


class IncidentPage(BaseModel):
    items: list[IncidentOut]
    total: int
    offset: int
    limit: int


class VersionedAction(BaseModel):
    version: int = Field(ge=1)


class AssignmentRequest(VersionedAction):
    assignee_id: uuid.UUID | None


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class CommentOut(ApiModel):
    id: uuid.UUID
    incident_id: uuid.UUID
    author: OperatorOut
    body: str
    created_at: datetime


class ResolveRequest(VersionedAction):
    resolution_note: str = Field(max_length=4000)


class TimelineEntry(BaseModel):
    kind: Literal["AUDIT", "COMMENT"]
    id: str
    at: datetime
    action: str
    actor: OperatorOut | None
    actor_kind: Literal["USER", "SYSTEM"]
    body: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    correlation_id: str | None = None


class Timeline(BaseModel):
    incident_id: uuid.UUID
    entries: list[TimelineEntry]


# ---- system / demo ------------------------------------------------------------------------
ScenarioKindIn = Literal["STALE_QUOTES", "WIDE_SPREAD", "RECOVERY", "DISCONNECT_STREAM"]


class ScenarioRequest(BaseModel):
    kind: ScenarioKindIn
    instrument_id: uuid.UUID | None = None
    duration_seconds: int | None = Field(default=None, ge=10, le=900)


class ScenarioOut(BaseModel):
    id: uuid.UUID
    kind: str
    instrument_id: uuid.UUID
    symbol: str
    started_at: datetime
    expires_at: datetime
    description: str


class ScenarioActionResult(BaseModel):
    kind: str
    message: str
    scenario: ScenarioOut | None = None
    stopped: list[ScenarioOut] = []


class ResetRequest(BaseModel):
    confirm: Literal["RESET"]


class ComponentStatus(BaseModel):
    status: Literal["ok", "degraded", "down", "warming_up", "disabled"]
    detail: str
    last_ok_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str | None = None


class SystemStatus(BaseModel):
    server_time: datetime
    started_at: datetime
    uptime_seconds: float
    epoch: str
    seq: int
    instruments: int
    connections: int
    configured_updates_per_second: int
    observed_quotes_per_second: float
    stale_count: int
    active_incidents: int
    simulator: ComponentStatus
    database: ComponentStatus
    persistence: ComponentStatus
    evaluator: ComponentStatus
    warmup_remaining_seconds: float
    scenarios: list[ScenarioOut]
    scenario_catalog: dict[str, str]
    overflow_disconnects: int
    single_worker: bool = True


class HealthOut(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: dict[str, str]
