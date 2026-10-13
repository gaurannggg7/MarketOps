"""Clock-driven rule evaluator. Runs independently of connected browsers.

- Freshness is measured from the backend receipt time of the last quote, using the injected
  clock (never a browser clock). Heartbeats do not refresh quotes.
- After process start there is a warm-up grace period (``warmup_seconds``) before any STALE
  rule is evaluated, so a restart does not open spurious stale incidents.
- Condition state is rebuilt from PostgreSQL at start: an unresolved incident whose
  ``condition_active`` is true stays active until fresh quotes prove recovery.
- Disabled rules that still have an unresolved incident are evaluated for recovery only.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clock import Clock
from app.models import AlertRule, Incident, IncidentStatus, Instrument, RuleType
from app.services import incidents as incident_service
from app.services.incidents import RuleRef
from app.services.market_math import fmt, spread_bps, spread_breaches, stale_breaches
from app.streaming.hub import Quote

log = logging.getLogger("marketops.evaluator")


class RuleEvaluator:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        clock: Clock,
        quotes: Callable[[], dict[uuid.UUID, Quote]],
        warmup_seconds: float,
        default_stale_seconds: int,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock
        self._quotes = quotes
        self.warmup_seconds = warmup_seconds
        self.default_stale_seconds = Decimal(default_stale_seconds)
        self.started_at = clock.now()
        self.rules: dict[uuid.UUID, RuleRef] = {}
        self.active: dict[uuid.UUID, bool] = {}
        self.last_run_at: datetime | None = None
        self.last_error: str | None = None
        self._dirty = True
        self.incidents_opened = 0

    def invalidate(self) -> None:
        """Called after rule/incident changes so the next tick reloads from PostgreSQL."""
        self._dirty = True

    def warmup_remaining(self, now: datetime | None = None) -> float:
        elapsed = ((now or self._clock.now()) - self.started_at).total_seconds()
        return max(0.0, self.warmup_seconds - elapsed)

    async def load(self) -> None:
        async with self._sessionmaker() as db:
            unresolved = select(Incident.rule_id).where(Incident.status != IncidentStatus.RESOLVED)
            rows = (
                await db.execute(
                    select(AlertRule, Instrument.symbol)
                    .join(Instrument, Instrument.id == AlertRule.instrument_id)
                    .where(or_(AlertRule.enabled, AlertRule.id.in_(unresolved)))
                )
            ).all()
            active_rows = (
                await db.execute(
                    select(Incident.rule_id, Incident.condition_active).where(
                        Incident.status != IncidentStatus.RESOLVED
                    )
                )
            ).all()
        self.rules = {
            r.id: RuleRef(
                id=r.id,
                instrument_id=r.instrument_id,
                symbol=symbol,
                rule_type=r.rule_type,
                threshold=r.threshold.normalize(),
                version=r.version,
                enabled=r.enabled,
            )
            for r, symbol in rows
        }
        self.active = {rule_id: bool(active) for rule_id, active in active_rows}
        self._dirty = False

    def stale_thresholds(self) -> dict[uuid.UUID, Decimal]:
        return {
            r.instrument_id: r.threshold
            for r in self.rules.values()
            if r.rule_type == RuleType.STALE and r.enabled
        }

    def compute_stale_ids(self, now: datetime) -> frozenset[uuid.UUID]:
        thresholds = self.stale_thresholds()
        out = set()
        for iid, q in self._quotes().items():
            age = (now - q.received_time).total_seconds()
            if stale_breaches(age, thresholds.get(iid, self.default_stale_seconds)):
                out.add(iid)
        return frozenset(out)

    def condition(self, rule: RuleRef, now: datetime) -> tuple[bool | None, dict[str, Any]]:
        """Return (breached, evidence); breached is None when it cannot be evaluated yet."""
        quote = self._quotes().get(rule.instrument_id)
        if rule.rule_type == RuleType.STALE:
            if self.warmup_remaining(now) > 0:
                return None, {}
            if quote is None:
                return None, {}
            age = (now - quote.received_time).total_seconds()
            evidence = {
                "age_seconds": round(age, 1),
                "threshold_seconds": fmt(rule.threshold),
                "last_received_time": quote.received_time.isoformat(),
                "last_source_time": quote.source_time.isoformat(),
                "bid": fmt(quote.bid),
                "ask": fmt(quote.ask),
                "evaluated_at": now.isoformat(),
            }
            return stale_breaches(age, rule.threshold), evidence
        if quote is None:
            return None, {}
        evidence = {
            "spread_bps": fmt(spread_bps(quote.bid, quote.ask)),
            "threshold_bps": fmt(rule.threshold),
            "bid": fmt(quote.bid),
            "ask": fmt(quote.ask),
            "received_time": quote.received_time.isoformat(),
            "evaluated_at": now.isoformat(),
        }
        return spread_breaches(quote.bid, quote.ask, rule.threshold), evidence

    async def evaluate_once(self) -> dict[str, int]:
        now = self._clock.now()
        if self._dirty:
            await self.load()
        counts = {"opened": 0, "rebreached": 0, "recovered": 0}
        for rule in list(self.rules.values()):
            breached, evidence = self.condition(rule, now)
            if breached is None:
                continue
            active = self.active.get(rule.id, False)
            correlation_id = f"eval-{uuid.uuid4().hex[:16]}"
            if breached and not active and rule.enabled:
                async with self._sessionmaker() as db:
                    outcome = await incident_service.record_breach(
                        db, rule, evidence, now, correlation_id
                    )
                self.active[rule.id] = True
                counts["opened"] += int(outcome.created)
                counts["rebreached"] += int(outcome.rebreached)
                self.incidents_opened += int(outcome.created)
            elif not breached and active:
                async with self._sessionmaker() as db:
                    await incident_service.record_recovery(db, rule, evidence, now, correlation_id)
                self.active[rule.id] = False
                counts["recovered"] += 1
        self.last_run_at = now
        return counts
