"""Process-wide runtime: simulator, stream hub, evaluator, sampler, and supervised tasks.

Exactly one Runtime exists per backend process (single worker, ADR 0002). It is created in the
FastAPI lifespan and never per request or per WebSocket.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.tickets import StreamTickets
from app.clock import Clock
from app.config import Settings
from app.models import Instrument, MarketEvent, QuoteSample
from app.services.audit import add_audit
from app.streaming.evaluator import RuleEvaluator
from app.streaming.hub import StreamHub
from app.streaming.scenarios import Scenario, ScenarioManager
from app.streaming.simulator import InstrumentSpec, Simulator

log = logging.getLogger("marketops.runtime")


@dataclass
class ComponentHealth:
    last_ok_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0

    def ok(self, now: datetime) -> None:
        self.last_ok_at = now
        self.consecutive_failures = 0

    def fail(self, now: datetime, exc: BaseException) -> None:
        self.last_error_at = now
        self.last_error = type(exc).__name__
        self.consecutive_failures += 1

    @property
    def healthy(self) -> bool:
        return self.consecutive_failures == 0


class Runtime:
    def __init__(
        self, settings: Settings, clock: Clock, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.sessionmaker = sessionmaker
        self.hub = StreamHub(
            settings.client_queue_max,
            settings.max_stream_connections,
            settings.max_stream_connections_per_session,
        )
        self.tickets = StreamTickets(settings.stream_ticket_ttl_seconds)
        self.simulator = Simulator(
            [],
            settings.simulator_seed,
            settings.simulator_updates_per_second,
            settings.batch_interval_ms / 1000,
        )
        self.scenarios = ScenarioManager(self.simulator)
        self.evaluator = RuleEvaluator(
            sessionmaker,
            clock,
            lambda: self.hub.quotes,
            settings.warmup_seconds,
            settings.default_stale_seconds,
        )
        self.persistence = ComponentHealth()
        self.evaluator_health = ComponentHealth()
        self.started_at = clock.now()
        self.started_monotonic = time.monotonic()
        self.last_tick_at: datetime | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self.task_failures: dict[str, str] = {}
        self.running = False
        self.symbols: dict[uuid.UUID, str] = {}
        self.autopilot: Any = None

    # ---- lifecycle ----------------------------------------------------------------------
    async def load_instruments(self) -> None:
        async with self.sessionmaker() as db:
            rows = (
                (
                    await db.execute(
                        select(Instrument).where(Instrument.is_active).order_by(Instrument.symbol)
                    )
                )
                .scalars()
                .all()
            )
        specs = [InstrumentSpec(r.id, r.symbol, r.base_price) for r in rows]
        self.symbols = {s.instrument_id: s.symbol for s in specs}
        self.simulator = Simulator(
            specs,
            self.settings.simulator_seed,
            self.settings.simulator_updates_per_second,
            self.settings.batch_interval_ms / 1000,
        )
        self.scenarios = ScenarioManager(self.simulator)
        self.hub.quotes.clear()
        self.hub.ingest(self.simulator.initial_quotes(self.clock.now()))

    async def start(self) -> None:
        await self.load_instruments()
        await self.evaluator.load()
        await self._record_system_event("FEED_EPOCH_STARTED", {"epoch": self.hub.epoch})
        self.running = True
        if not self.settings.simulator_enabled:
            return
        self._spawn("producer", self._producer_loop)
        self._spawn("heartbeat", self._heartbeat_loop)
        self._spawn("sampler", self._sampler_loop)
        self._spawn("evaluator", self._evaluator_loop)
        self._spawn("maintenance", self._maintenance_loop)
        if self.settings.demo_autopilot_enabled:
            from app.streaming.autopilot import DemoAutopilot  # optional demo helper

            self.autopilot = DemoAutopilot(self)
            self._spawn("autopilot", self.autopilot.run_forever)

    def _spawn(self, name: str, fn: Callable[[], Coroutine[Any, Any, None]]) -> None:
        task: asyncio.Task[None] = asyncio.create_task(fn(), name=f"marketops-{name}")

        def _done(t: asyncio.Task[None]) -> None:
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                self.task_failures[name] = type(exc).__name__
                log.error("background task %s crashed", name, exc_info=exc)

        task.add_done_callback(_done)
        self._tasks.append(task)

    async def stop(self) -> None:
        self.running = False
        await self.hub.close_all("server_shutdown")
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    @property
    def tasks_alive(self) -> bool:
        return not self.task_failures and all(not t.done() for t in self._tasks)

    # ---- loops --------------------------------------------------------------------------
    async def _producer_loop(self) -> None:
        interval = self.settings.batch_interval_ms / 1000
        loop = asyncio.get_running_loop()
        next_at = loop.time()
        while True:
            now = self.clock.now()
            self.hub.ingest(self.simulator.step(now))
            await self.hub.flush(now, loop.time())
            self.last_tick_at = now
            next_at += interval
            await asyncio.sleep(max(0.0, next_at - loop.time()))

    async def _heartbeat_loop(self) -> None:
        interval = self.settings.heartbeat_interval_ms / 1000
        while True:
            await asyncio.sleep(interval)
            now = self.clock.now()
            self.hub.stale_ids = self.evaluator.compute_stale_ids(now)
            await self.hub.heartbeat(now)

    async def _sampler_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.sample_interval_seconds)
            await self.sample_once()

    async def sample_once(self) -> int:
        """Persist at most one sample per updated instrument (batched insert)."""
        rows = []
        for q in self.hub.quotes.values():
            if q.needs_sample:
                rows.append(
                    {
                        "instrument_id": q.instrument_id,
                        "bid": q.bid,
                        "ask": q.ask,
                        "volume": q.volume,
                        "source_time": q.source_time,
                        "received_time": q.received_time,
                    }
                )
                q.needs_sample = False
        if not rows:
            return 0
        now = self.clock.now()
        try:
            async with self.sessionmaker() as db:
                await db.execute(insert(QuoteSample), rows)
                await db.commit()
            self.persistence.ok(now)
        except Exception as exc:  # report and keep streaming; samples for this second are lost
            self.persistence.fail(now, exc)
            log.warning("quote sample write failed: %s", type(exc).__name__)
        return len(rows)

    async def _evaluator_loop(self) -> None:
        last_reload = time.monotonic()
        while True:
            await asyncio.sleep(self.settings.evaluator_interval_seconds)
            now = self.clock.now()
            try:
                for sc in self.scenarios.expire(now):
                    await self.record_scenario_end(sc, None, "expired")
                if time.monotonic() - last_reload > 30:
                    self.evaluator.invalidate()
                    last_reload = time.monotonic()
                if not self.symbols:
                    # Started before the catalog was seeded (fresh database): pick it up.
                    await self.load_instruments()
                await self.evaluator.evaluate_once()
                self.evaluator_health.ok(now)
            except Exception as exc:  # DB outage must not kill the evaluator loop
                self.evaluator_health.fail(now, exc)
                self.evaluator.invalidate()
                log.warning("evaluation failed: %s", type(exc).__name__)

    async def _maintenance_loop(self) -> None:
        while True:
            await asyncio.sleep(600)
            try:
                await prune_samples(
                    self.sessionmaker, self.clock.now(), self.settings.quote_retention_hours
                )
            except Exception as exc:
                log.warning("retention prune failed: %s", type(exc).__name__)

    # ---- events -------------------------------------------------------------------------
    async def _record_system_event(self, event_type: str, evidence: dict[str, object]) -> None:
        try:
            async with self.sessionmaker() as db:
                db.add(
                    MarketEvent(
                        instrument_id=None,
                        event_type=event_type,
                        observed_at=self.clock.now(),
                        evidence=evidence,
                    )
                )
                await db.commit()
        except Exception as exc:
            self.persistence.fail(self.clock.now(), exc)

    async def record_scenario_start(self, sc: Scenario, correlation_id: str) -> None:
        now = self.clock.now()
        async with self.sessionmaker() as db:
            db.add(
                MarketEvent(
                    instrument_id=sc.instrument_id,
                    event_type="SCENARIO_STARTED",
                    observed_at=now,
                    evidence=_scenario_evidence(sc),
                )
            )
            add_audit(
                db,
                actor_id=sc.started_by,
                action="SCENARIO_STARTED",
                entity_type="scenario",
                entity_id=sc.id,
                correlation_id=correlation_id,
                at=now,
                after=_scenario_evidence(sc),
            )
            await db.commit()

    async def record_scenario_end(
        self,
        sc: Scenario,
        actor_id: uuid.UUID | None,
        reason: str,
        correlation_id: str | None = None,
    ) -> None:
        now = self.clock.now()
        forced = self.simulator.force_quote(sc.instrument_id, now)
        if forced is not None:
            self.hub.ingest([forced])
        evidence = {**_scenario_evidence(sc), "reason": reason}
        async with self.sessionmaker() as db:
            db.add(
                MarketEvent(
                    instrument_id=sc.instrument_id,
                    event_type="SCENARIO_ENDED",
                    observed_at=now,
                    evidence=evidence,
                )
            )
            add_audit(
                db,
                actor_id=actor_id,
                action="SCENARIO_ENDED",
                entity_type="scenario",
                entity_id=sc.id,
                correlation_id=correlation_id or f"sys-{uuid.uuid4().hex[:16]}",
                at=now,
                after=evidence,
            )
            await db.commit()

    async def reset_demo(self) -> str:
        """Stop scenarios, restart the seeded price paths, and begin a new stream epoch."""
        self.scenarios.stop_for_instrument(None)
        self.simulator.reset()
        epoch = await self.hub.start_new_epoch()
        self.hub.quotes.clear()
        self.hub.ingest(self.simulator.initial_quotes(self.clock.now()))
        await self._record_system_event("FEED_EPOCH_STARTED", {"epoch": epoch, "reason": "reset"})
        return epoch


def _scenario_evidence(sc: Scenario) -> dict[str, object]:
    return {
        "scenario_id": str(sc.id),
        "kind": sc.kind.value,
        "symbol": sc.symbol,
        "expires_at": sc.expires_at.isoformat(),
    }


async def prune_samples(
    sessionmaker: async_sessionmaker[AsyncSession], now: datetime, retention_hours: int
) -> int:
    cutoff = now - timedelta(hours=retention_hours)
    async with sessionmaker() as db:
        result = await db.execute(delete(QuoteSample).where(QuoteSample.received_time < cutoff))
        await db.commit()
        return int(getattr(result, "rowcount", 0) or 0)
