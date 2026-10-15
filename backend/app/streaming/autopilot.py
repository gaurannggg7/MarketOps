"""Demo Autopilot: an automated, clearly labelled operator for the public read-only demo.

Every `demo_autopilot_interval_seconds` it runs one scenario (alternating stale quotes and wide
spread) on an instrument without an unresolved incident, then performs the operator workflow
through the same service functions a human uses (so every step is audited under the
"Demo Autopilot (automated)" user): acknowledge → comment → wait for recovery → resolve.
It skips quietly when a human operator acts first (version conflicts / invalid transitions).
"""

from __future__ import annotations

import asyncio
import logging
import random
import secrets
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.auth.deps import CurrentUser
from app.auth.security import hash_password
from app.errors import AppError
from app.models import AlertRule, Incident, IncidentStatus, Role, RuleType, User
from app.services import incidents as svc
from app.streaming.scenarios import ScenarioConflictError, ScenarioKind

if TYPE_CHECKING:
    from app.runtime import Runtime

log = logging.getLogger("marketops.autopilot")
AUTOPILOT_NAME = "Demo Autopilot (automated)"
SCENARIO_SECONDS = 45


class DemoAutopilot:
    def __init__(self, runtime: Runtime, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self.rt = runtime
        self._sleep = sleep
        self._rng = random.Random(runtime.settings.simulator_seed + 7)
        self.cycles = 0
        self.last_result: str | None = None

    async def ensure_user(self) -> CurrentUser:
        email = self.rt.settings.demo_autopilot_email
        async with self.rt.sessionmaker() as db:
            user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
            if user is None:
                # Random, never-disclosed password: this account cannot be used to sign in.
                user = User(
                    email=email,
                    display_name=AUTOPILOT_NAME,
                    role=Role.OPERATOR,
                    password_hash=hash_password(secrets.token_urlsafe(32)),
                    is_active=True,
                )
                db.add(user)
                await db.commit()
            return CurrentUser(
                id=user.id,
                email=user.email,
                display_name=user.display_name,
                role=user.role,
                session_id=uuid.UUID(int=0),
                csrf_token_hash="",
            )

    async def run_forever(self) -> None:
        actor = await self.ensure_user()
        await self._sleep(max(30.0, self.rt.settings.warmup_seconds + 15))
        while True:
            try:
                self.last_result = await self.run_cycle(actor)
            except Exception as exc:  # never let the demo helper crash the runtime
                self.last_result = f"error: {type(exc).__name__}"
                log.warning("autopilot cycle failed: %s", type(exc).__name__)
            self.cycles += 1
            await self._sleep(self.rt.settings.demo_autopilot_interval_seconds)

    async def _candidate(self) -> tuple[uuid.UUID, str] | None:
        async with self.rt.sessionmaker() as db:
            busy = set(
                (
                    await db.execute(
                        select(Incident.instrument_id).where(
                            Incident.status != IncidentStatus.RESOLVED
                        )
                    )
                ).scalars()
            )
        ids = [i for i in self.rt.symbols if i not in busy]
        if not ids:
            return None
        iid = self._rng.choice(sorted(ids))
        return iid, self.rt.symbols[iid]

    async def _wait_for(self, predicate: Callable[[], Awaitable[bool]], max_seconds: float) -> bool:
        waited = 0.0
        # Polls with the injectable sleep (deterministic in tests) instead of asyncio.timeout.
        while waited < max_seconds:
            if await predicate():
                return True
            await self._sleep(1.0)
            waited += 1.0
        return False

    async def _incident(self, rule_type: RuleType, instrument_id: uuid.UUID) -> Incident | None:
        async with self.rt.sessionmaker() as db:
            return (
                await db.execute(
                    select(Incident)
                    .join(AlertRule, AlertRule.id == Incident.rule_id)
                    .where(
                        Incident.instrument_id == instrument_id,
                        AlertRule.rule_type == rule_type,
                        Incident.status != IncidentStatus.RESOLVED,
                    )
                )
            ).scalar_one_or_none()

    async def run_cycle(self, actor: CurrentUser) -> str:
        picked = await self._candidate()
        if picked is None:
            return "skipped: no instrument without an unresolved incident"
        iid, symbol = picked
        kind = ScenarioKind.STALE_QUOTES if self.cycles % 2 == 0 else ScenarioKind.WIDE_SPREAD
        rule_type = RuleType.STALE if kind == ScenarioKind.STALE_QUOTES else RuleType.WIDE_SPREAD
        now = self.rt.clock.now()
        try:
            sc = self.rt.scenarios.start(kind, iid, symbol, SCENARIO_SECONDS, actor.id, now)
        except ScenarioConflictError:
            return f"skipped: scenario already running for {symbol}"
        await self.rt.record_scenario_start(sc, f"autopilot-{uuid.uuid4().hex[:12]}")

        holder: dict[str, Incident] = {}

        async def opened() -> bool:
            inc = await self._incident(rule_type, iid)
            if inc is not None:
                holder["inc"] = inc
            return inc is not None

        if not await self._wait_for(opened, max_seconds=40):
            return f"no incident opened for {symbol}"
        inc = holder["inc"]
        cid = f"autopilot-{uuid.uuid4().hex[:12]}"
        try:
            async with self.rt.sessionmaker() as db:
                acked = await svc.acknowledge(
                    db, inc.id, inc.version, actor, self.rt.clock.now(), cid
                )
            async with self.rt.sessionmaker() as db:
                await svc.add_comment(
                    db,
                    inc.id,
                    f"Automated demo: {kind.value} scenario on {symbol} detected by the "
                    f"{rule_type.value} rule. Waiting for the scenario to expire and the "
                    "condition to recover before resolving.",
                    actor,
                    self.rt.clock.now(),
                    cid,
                )
        except AppError as exc:
            return f"stopped at acknowledge for #{inc.number}: {exc.code}"

        async def recovered() -> bool:
            async with self.rt.sessionmaker() as db:
                cur = await db.get(Incident, inc.id)
                return cur is not None and not cur.condition_active

        if not await self._wait_for(recovered, max_seconds=SCENARIO_SECONDS + 40):
            return f"#{inc.number} did not recover in time"
        try:
            async with self.rt.sessionmaker() as db:
                await svc.resolve(
                    db,
                    inc.id,
                    acked.version,
                    f"Automated demo: {symbol} recovered after the scenario "
                    "expired; resolved by the demo autopilot.",
                    actor,
                    self.rt.clock.now(),
                    cid,
                )
        except AppError as exc:
            return f"stopped at resolve for #{inc.number}: {exc.code}"
        self.rt.evaluator.invalidate()
        return f"resolved #{inc.number} ({kind.value} on {symbol})"
