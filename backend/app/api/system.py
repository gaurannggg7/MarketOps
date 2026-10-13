"""System status, demo scenarios, and health probes."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import correlation_id, runtime_of
from app.auth.deps import CurrentUser, current_user, require_operator
from app.db import get_session
from app.errors import AppError, not_found
from app.models import Incident, IncidentStatus, Instrument
from app.runtime import ComponentHealth, Runtime
from app.schemas.api import (
    ComponentStatus,
    ErrorResponse,
    HealthOut,
    ResetRequest,
    ScenarioActionResult,
    ScenarioOut,
    ScenarioRequest,
    SystemStatus,
)
from app.services.audit import add_audit
from app.streaming.hub import CLOSE_SCENARIO_DISCONNECT
from app.streaming.scenarios import DESCRIPTIONS, Scenario, ScenarioConflictError, ScenarioKind

router = APIRouter(tags=["system"])
_ERR: dict[int | str, dict[str, object]] = {
    s: {"model": ErrorResponse} for s in (401, 403, 404, 409, 422)
}

CATALOG = {
    "STALE_QUOTES": DESCRIPTIONS[ScenarioKind.STALE_QUOTES],
    "WIDE_SPREAD": DESCRIPTIONS[ScenarioKind.WIDE_SPREAD],
    "RECOVERY": "Ends active scenarios for one instrument (or all) so normal quotes resume. "
    "Incidents are updated but never resolved automatically.",
    "DISCONNECT_STREAM": "Closes your own live-stream connection to exercise reconnection and "
    "snapshot resynchronization. Other users are unaffected.",
}


def _scenario_out(sc: Scenario) -> ScenarioOut:
    return ScenarioOut(
        id=sc.id,
        kind=sc.kind.value,
        instrument_id=sc.instrument_id,
        symbol=sc.symbol,
        started_at=sc.started_at,
        expires_at=sc.expires_at,
        description=DESCRIPTIONS[sc.kind],
    )


def _component(h: ComponentHealth, ok_detail: str) -> ComponentStatus:
    if h.healthy:
        return ComponentStatus(
            status="ok",
            detail=ok_detail,
            last_ok_at=h.last_ok_at,
            last_error_at=h.last_error_at,
            last_error=h.last_error,
        )
    return ComponentStatus(
        status="degraded",
        detail=f"{h.consecutive_failures} consecutive failures",
        last_ok_at=h.last_ok_at,
        last_error_at=h.last_error_at,
        last_error=h.last_error,
    )


async def _db_check(db: AsyncSession) -> tuple[bool, str]:
    started = time.perf_counter()
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        return False, type(exc).__name__
    return True, f"SELECT 1 in {(time.perf_counter() - started) * 1000:.1f} ms"


@router.get("/system/status", response_model=SystemStatus, responses=_ERR)
async def system_status(
    request: Request,
    _: CurrentUser = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> SystemStatus:
    rt = runtime_of(request)
    now = rt.clock.now()
    db_ok, db_detail = await _db_check(db)
    active_incidents = 0
    if db_ok:
        active_incidents = int(
            (
                await db.execute(
                    select(func.count()).where(Incident.status != IncidentStatus.RESOLVED)
                )
            ).scalar_one()
        )
    loop_time = time.monotonic()
    if not rt.settings.simulator_enabled:
        sim = ComponentStatus(status="disabled", detail="Simulator disabled by configuration")
    elif rt.task_failures:
        sim = ComponentStatus(status="down", detail=f"Task failure: {rt.task_failures}")
    else:
        sim = ComponentStatus(
            status="ok",
            detail=f"Synthetic feed, seed {rt.settings.simulator_seed}",
            last_ok_at=rt.last_tick_at,
        )
    warmup = rt.evaluator.warmup_remaining(now)
    evaluator = _component(rt.evaluator_health, f"{len(rt.evaluator.rules)} rules loaded")
    if warmup > 0 and evaluator.status == "ok":
        evaluator.status = "warming_up"
        evaluator.detail = f"Stale checks begin in {warmup:.0f}s; {len(rt.evaluator.rules)} rules"
    return SystemStatus(
        server_time=now,
        started_at=rt.started_at,
        uptime_seconds=round((now - rt.started_at).total_seconds(), 1),
        epoch=rt.hub.epoch,
        seq=rt.hub.seq,
        instruments=len(rt.hub.quotes),
        connections=rt.hub.connection_count,
        configured_updates_per_second=rt.settings.simulator_updates_per_second,
        observed_quotes_per_second=rt.hub.observed_quotes_per_second(loop_time),
        stale_count=len(rt.hub.stale_ids),
        active_incidents=active_incidents,
        simulator=sim,
        database=ComponentStatus(status="ok" if db_ok else "down", detail=db_detail),
        persistence=_component(rt.persistence, "Quote samples persisting"),
        evaluator=evaluator,
        warmup_remaining_seconds=round(warmup, 1),
        scenarios=[_scenario_out(s) for s in rt.scenarios.active.values()],
        scenario_catalog=CATALOG,
        overflow_disconnects=rt.hub.stats.overflow_disconnects,
    )


async def _instrument_symbol(db: AsyncSession, instrument_id: uuid.UUID | None) -> str:
    if instrument_id is None:
        raise AppError(422, "INSTRUMENT_REQUIRED", "Choose an instrument for this scenario.")
    symbol = (
        await db.execute(select(Instrument.symbol).where(Instrument.id == instrument_id))
    ).scalar_one_or_none()
    if symbol is None:
        raise not_found("Instrument")
    return symbol


@router.post(
    "/demo/scenarios", response_model=ScenarioActionResult, status_code=201, responses=_ERR
)
async def start_scenario(
    body: ScenarioRequest,
    request: Request,
    user: CurrentUser = Depends(require_operator),
    db: AsyncSession = Depends(get_session),
) -> ScenarioActionResult:
    rt: Runtime = runtime_of(request)
    cid = correlation_id(request)
    now = rt.clock.now()
    if body.kind == "DISCONNECT_STREAM":
        closed = rt.hub.disconnect_user(user.id, "scenario_disconnect", CLOSE_SCENARIO_DISCONNECT)
        add_audit(
            db,
            actor_id=user.id,
            action="STREAM_DISCONNECT_SCENARIO",
            entity_type="user",
            entity_id=user.id,
            correlation_id=cid,
            at=now,
            after={"connections": closed},
        )
        await db.commit()
        return ScenarioActionResult(
            kind=body.kind,
            message=f"Closed {closed} live connection(s) for your user; "
            "the client will reconnect and resynchronize.",
        )
    if body.kind == "RECOVERY":
        if body.instrument_id is not None:
            await _instrument_symbol(db, body.instrument_id)
        stopped = rt.scenarios.stop_for_instrument(body.instrument_id)
        for sc in stopped:
            await rt.record_scenario_end(sc, user.id, "recovery", cid)
        return ScenarioActionResult(
            kind=body.kind,
            message=f"Stopped {len(stopped)} scenario(s); normal quotes resume.",
            stopped=[_scenario_out(s) for s in stopped],
        )
    symbol = await _instrument_symbol(db, body.instrument_id)
    assert body.instrument_id is not None
    duration = min(
        body.duration_seconds or rt.settings.default_scenario_seconds,
        rt.settings.max_scenario_seconds,
    )
    try:
        sc = rt.scenarios.start(
            ScenarioKind(body.kind), body.instrument_id, symbol, duration, user.id, now
        )
    except ScenarioConflictError as exc:
        raise AppError(409, "SCENARIO_CONFLICT", str(exc)) from None
    await rt.record_scenario_start(sc, cid)
    return ScenarioActionResult(
        kind=body.kind,
        message=f"{body.kind} started for {symbol}; expires automatically in {duration}s.",
        scenario=_scenario_out(sc),
    )


@router.delete("/demo/scenarios/{scenario_id}", response_model=ScenarioActionResult, responses=_ERR)
async def stop_scenario(
    scenario_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(require_operator),
) -> ScenarioActionResult:
    rt = runtime_of(request)
    sc = rt.scenarios.stop(scenario_id)
    if sc is None:
        raise not_found("Active scenario")
    await rt.record_scenario_end(sc, user.id, "stopped", correlation_id(request))
    return ScenarioActionResult(
        kind=sc.kind.value,
        message=f"Stopped {sc.kind.value} for {sc.symbol}.",
        stopped=[_scenario_out(sc)],
    )


@router.post("/demo/reset", response_model=ScenarioActionResult, responses=_ERR)
async def reset_demo(
    body: ResetRequest,
    request: Request,
    user: CurrentUser = Depends(require_operator),
    db: AsyncSession = Depends(get_session),
) -> ScenarioActionResult:
    """Stops scenarios and restarts seeded price paths in a new stream epoch.

    Persisted incidents, comments, and audit history are intentionally kept.
    """
    rt = runtime_of(request)
    epoch = await rt.reset_demo()
    add_audit(
        db,
        actor_id=user.id,
        action="DEMO_RESET",
        entity_type="system",
        entity_id="feed",
        correlation_id=correlation_id(request),
        at=rt.clock.now(),
        after={"epoch": epoch},
    )
    await db.commit()
    return ScenarioActionResult(
        kind="RESET",
        message=f"Feed reset; new epoch {epoch}. Incident and audit history were kept.",
    )


@router.get("/health/live", response_model=HealthOut)
async def live() -> HealthOut:
    return HealthOut(status="ok", checks={"process": "ok"})


@router.get("/health/ready", response_model=HealthOut, responses={503: {"model": HealthOut}})
async def ready(
    request: Request, response: Response, db: AsyncSession = Depends(get_session)
) -> HealthOut:
    rt = runtime_of(request)
    checks: dict[str, str] = {}
    db_ok, db_detail = await _db_check(db)
    checks["database"] = "ok" if db_ok else f"down: {db_detail}"
    if db_ok:
        try:
            current = (
                await db.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
        except Exception as exc:
            current = None
            checks["migrations"] = f"unknown: {type(exc).__name__}"
        head = request.app.state.migration_head
        if "migrations" not in checks:
            checks["migrations"] = "ok" if current == head else f"at {current}, expected {head}"
    else:
        checks["migrations"] = "unknown"
    if not rt.running:
        checks["simulator"] = "not started"
    elif rt.settings.simulator_enabled and not rt.tasks_alive:
        checks["simulator"] = f"background task failure: {rt.task_failures}"
    else:
        checks["simulator"] = "ok"
    healthy = all(v == "ok" for v in checks.values())
    if not healthy:
        response.status_code = 503
    return HealthOut(status="ok" if healthy else "unavailable", checks=checks)
