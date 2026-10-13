from __future__ import annotations

import asyncio
import uuid

from fastapi import FastAPI
from sqlalchemy import func, select

from app.clock import FakeClock
from app.models import AlertEpisode, AlertRule, Incident, IncidentStatus, MarketEvent, RuleType
from app.runtime import Runtime
from app.services import incidents as svc
from app.services.incidents import RuleRef


def feed(rt: Runtime, clock: FakeClock, skip: set[uuid.UUID] | None = None) -> None:
    """Deliver a fresh quote for every instrument except ``skip`` (deterministic)."""
    skip = skip or set()
    quotes = []
    for iid in rt.hub.quotes:
        if iid in skip:
            continue
        q = rt.simulator.force_quote(iid, clock.now())
        if q is not None:
            quotes.append(q)
    rt.hub.ingest(quotes)


async def incidents(app: FastAPI) -> list[Incident]:
    async with app.state.sessionmaker() as db:
        return list((await db.execute(select(Incident).order_by(Incident.number))).scalars())


async def advance(rt: Runtime, clock: FakeClock, seconds: int, skip: set[uuid.UUID]) -> None:
    for _ in range(seconds):
        clock.advance(1)
        feed(rt, clock, skip)
        await rt.evaluator.evaluate_once()


async def test_warmup_then_stale_without_any_incoming_quotes(
    app: FastAPI, clock: FakeClock
) -> None:
    rt: Runtime = app.state.runtime
    rt.evaluator.warmup_seconds = 30
    clock.advance(15)  # no quotes at all; would be stale but still in warm-up
    assert rt.evaluator.condition(next(iter(rt.evaluator.rules.values())), clock.now())[0] in (
        None,
        False,
    )
    await rt.evaluator.evaluate_once()
    assert await incidents(app) == []
    clock.advance(20)  # warm-up over; nothing arrived for 35s → every instrument is stale
    await rt.evaluator.evaluate_once()
    opened = await incidents(app)
    assert len(opened) == 5
    assert {i.incident_type for i in opened} == {RuleType.STALE}
    assert all(i.condition_active and i.status == IncidentStatus.OPEN for i in opened)


async def test_heartbeats_do_not_freshen_and_stale_opens_one_incident(
    app: FastAPI, clock: FakeClock
) -> None:
    rt: Runtime = app.state.runtime
    target = next(iter(rt.hub.quotes))
    rt.simulator.paused.add(target)
    await advance(rt, clock, 8, {target})
    await rt.hub.heartbeat(clock.now())  # heartbeats never update quote receipt times
    assert await incidents(app) == []
    await advance(rt, clock, 10, {target})  # 18s without a quote > 10s threshold
    opened = await incidents(app)
    assert len(opened) == 1
    assert opened[0].instrument_id == target
    assert "no quote received" in opened[0].trigger_reason
    assert rt.evaluator.compute_stale_ids(clock.now()) == frozenset({target})
    await advance(rt, clock, 5, {target})  # repeated evaluation: still one incident
    assert len(await incidents(app)) == 1

    rt.simulator.paused.clear()
    await advance(rt, clock, 1, set())  # recovered quote updates, but never resolves
    (inc,) = await incidents(app)
    assert inc.status == IncidentStatus.OPEN
    assert not inc.condition_active
    async with app.state.sessionmaker() as db:
        ep = (await db.execute(select(AlertEpisode))).scalar_one()
        assert ep.recovered_at is not None
        assert ep.incident_id == inc.id
        kinds = (
            (await db.execute(select(MarketEvent.event_type).order_by(MarketEvent.id)))
            .scalars()
            .all()
        )
    assert "STALE_BREACH" in kinds
    assert "STALE_RECOVERY" in kinds


async def test_wide_spread_and_rebreach_updates_same_incident(
    app: FastAPI, clock: FakeClock
) -> None:
    rt: Runtime = app.state.runtime
    target = next(iter(rt.hub.quotes))
    rt.simulator.widened.add(target)
    await advance(rt, clock, 2, set())
    (inc,) = await incidents(app)
    assert inc.incident_type == RuleType.WIDE_SPREAD
    assert inc.breach_count == 1
    rt.simulator.widened.clear()
    await advance(rt, clock, 1, set())
    rt.simulator.widened.add(target)
    await advance(rt, clock, 1, set())
    (inc,) = await incidents(app)  # re-breach during unresolved incident → same incident
    assert inc.condition_active
    assert inc.breach_count == 2


async def _rule(app: FastAPI) -> RuleRef:
    async with app.state.sessionmaker() as db:
        r = (
            await db.execute(
                select(AlertRule).where(AlertRule.rule_type == RuleType.STALE).limit(1)
            )
        ).scalar_one()
    return RuleRef(r.id, r.instrument_id, "TEST", r.rule_type, r.threshold, r.version)


async def test_concurrent_evaluators_cannot_duplicate_incidents(
    app: FastAPI, clock: FakeClock
) -> None:
    rule = await _rule(app)
    factory = app.state.sessionmaker
    evidence = {"age_seconds": 30}

    async def attempt(n: int) -> svc.BreachOutcome:
        async with factory() as db:
            return await svc.record_breach(db, rule, evidence, clock.now(), f"race-{n}")

    outcomes = await asyncio.gather(*(attempt(n) for n in range(6)))
    assert sum(o.created for o in outcomes) == 1
    assert len({o.incident_id for o in outcomes}) == 1
    async with factory() as db:
        assert (await db.execute(select(func.count()).select_from(Incident))).scalar_one() == 1
        # The losing transactions left no orphan episodes behind.
        assert (await db.execute(select(func.count()).select_from(AlertEpisode))).scalar_one() == 1


async def test_restart_preserves_unresolved_incident_until_quotes_recover(
    app: FastAPI, clock: FakeClock
) -> None:
    rt: Runtime = app.state.runtime
    target = next(iter(rt.hub.quotes))
    await advance(rt, clock, 12, {target})
    (inc,) = await incidents(app)
    assert inc.condition_active

    restarted = Runtime(rt.settings, clock, app.state.sessionmaker)  # simulated process restart
    await restarted.start()
    assert restarted.hub.epoch != rt.hub.epoch
    assert restarted.evaluator.active[inc.rule_id] is True
    clock.advance(1)
    await restarted.evaluator.evaluate_once()  # warm-up: no stale verdicts, no recovery yet
    (still,) = await incidents(app)
    assert still.condition_active
    await advance(restarted, clock, 5, set())  # fresh quotes after warm-up → recovered
    (after,) = await incidents(app)
    assert not after.condition_active
    assert after.status == IncidentStatus.OPEN
    await restarted.stop()
