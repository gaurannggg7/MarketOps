from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clock import FakeClock
from app.config import Settings
from app.main import create_app
from app.models import AuditEvent, Incident, IncidentStatus, User
from app.runtime import Runtime
from app.streaming.autopilot import AUTOPILOT_NAME, DemoAutopilot
from tests.conftest import make_client
from tests.helpers import error_code, instruments
from tests.test_evaluator import feed


@pytest.fixture
async def demo_app(seeded: None, settings: Settings, clock: FakeClock) -> AsyncIterator[FastAPI]:
    cfg = settings.model_copy(update={"public_demo_enabled": True, "demo_login_max_per_window": 3})
    application = create_app(cfg, clock, null_pool=True)
    await application.state.runtime.start()
    yield application
    await application.state.runtime.stop()
    await application.state.engine.dispose()


async def test_demo_login_is_disabled_by_default(client: AsyncClient) -> None:
    r = await client.post("/api/v1/auth/demo")
    assert r.status_code == 404
    assert (await client.get("/api/v1/auth/session")).json()["demo_available"] is False


async def test_public_demo_session_is_read_only(demo_app: FastAPI) -> None:
    async with make_client(demo_app) as c:
        assert (await c.get("/api/v1/auth/session")).json()["demo_available"] is True
        r = await c.post("/api/v1/auth/demo")
        assert r.status_code == 200
        body = r.json()
        assert body["public_demo"] is True
        assert body["user"]["role"] == "VIEWER"
        c.headers["X-CSRF-Token"] = body["csrf_token"]
        inst = (await instruments(c))[0]
        assert (await c.get("/api/v1/incidents")).status_code == 200
        writes = [
            await c.post("/api/v1/watchlists", json={"name": "public"}),
            await c.post(f"/api/v1/watchlists/{inst['id']}/items/{inst['id']}"),
            await c.post("/api/v1/demo/scenarios", json={"kind": "DISCONNECT_STREAM"}),
        ]
        for w in writes:
            assert w.status_code == 403
            assert error_code(w) == "PUBLIC_DEMO_READ_ONLY"
        assert (await c.post("/api/v1/auth/logout")).status_code == 204


async def test_demo_login_requires_origin_and_is_rate_limited(demo_app: FastAPI) -> None:
    async with make_client(demo_app) as c:
        bad = await c.post("/api/v1/auth/demo", headers={"Origin": "https://evil.example"})
        assert bad.status_code == 403
        for _ in range(3):
            assert (await c.post("/api/v1/auth/demo")).status_code == 200
        limited = await c.post("/api/v1/auth/demo")
        assert limited.status_code == 429
        assert error_code(limited) == "TOO_MANY_ATTEMPTS"


async def test_autopilot_runs_full_incident_lifecycle(app: FastAPI, clock: FakeClock) -> None:
    rt: Runtime = app.state.runtime
    rt.evaluator.warmup_seconds = 0

    async def fake_sleep(seconds: float) -> None:
        # Advance time second by second: deliver quotes (paused instruments emit none) and
        # run the evaluator and scenario expiry exactly as the background loops would.
        for _ in range(max(1, int(seconds))):
            clock.advance(1)
            feed(rt, clock, skip=set(rt.simulator.paused))
            for sc in rt.scenarios.expire(clock.now()):
                await rt.record_scenario_end(sc, None, "expired")
            await rt.evaluator.evaluate_once()

    pilot = DemoAutopilot(rt, sleep=fake_sleep)
    actor = await pilot.ensure_user()
    result = await pilot.run_cycle(actor)
    assert result.startswith("resolved #"), result

    async with app.state.sessionmaker() as db:
        (inc,) = (await db.execute(select(Incident))).scalars().all()
        assert inc.status == IncidentStatus.RESOLVED
        user = await db.get(User, actor.id)
        assert user is not None
        assert user.display_name == AUTOPILOT_NAME
        actions = (
            (
                await db.execute(
                    select(AuditEvent.action)
                    .where(AuditEvent.entity_id == str(inc.id))
                    .order_by(AuditEvent.id)
                )
            )
            .scalars()
            .all()
        )
    assert actions == [
        "INCIDENT_OPENED",
        "INCIDENT_ACKNOWLEDGED",
        "COMMENT_ADDED",
        "CONDITION_RECOVERED",
        "INCIDENT_RESOLVED",
    ]


async def test_runtime_picks_up_catalog_seeded_after_start(
    settings: Settings, clock: FakeClock, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    from sqlalchemy import text

    from app.seed import BUSINESS_TABLES, seed

    async with sessionmaker() as db:
        await db.execute(text(f"TRUNCATE {', '.join(BUSINESS_TABLES)} RESTART IDENTITY CASCADE"))
        await db.commit()
    rt = Runtime(settings, clock, sessionmaker)
    await rt.start()
    assert rt.symbols == {}
    async with sessionmaker() as db:
        await seed(db, instruments=5)
    await rt.load_instruments()  # what the evaluator loop does while the catalog is empty
    assert len(rt.symbols) == 5
    assert len(rt.hub.quotes) == 5
    await rt.stop()
