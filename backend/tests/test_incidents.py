from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

from app.clock import FakeClock
from app.models import AuditEvent
from app.runtime import Runtime
from tests.helpers import error_code
from tests.test_evaluator import advance


async def _open_stale_incident(app: FastAPI, clock: FakeClock) -> tuple[uuid.UUID, dict[str, Any]]:
    rt: Runtime = app.state.runtime
    target = next(iter(rt.hub.quotes))
    await advance(rt, clock, 12, {target})
    return target, {}


async def _first(client: AsyncClient, **params: Any) -> dict[str, Any]:
    r = await client.get("/api/v1/incidents", params=params)
    assert r.status_code == 200
    items = r.json()["items"]
    assert items, "expected an incident"
    detail = await client.get(f"/api/v1/incidents/{items[0]['id']}")
    result: dict[str, Any] = detail.json()
    return result


async def _audits(app: FastAPI) -> int:
    async with app.state.sessionmaker() as db:
        return int((await db.execute(select(func.count()).select_from(AuditEvent))).scalar_one())


async def test_full_lifecycle_and_timeline(
    app: FastAPI, clock: FakeClock, operator: AsyncClient, operator2: AsyncClient
) -> None:
    target, _ = await _open_stale_incident(app, clock)
    inc = await _first(operator, status="OPEN")
    base = f"/api/v1/incidents/{inc['id']}"
    assert inc["condition_active"]
    assert inc["rule"]["rule_type"] == "STALE"
    assert inc["trigger_evidence"]["threshold_seconds"] == "10"

    r = await operator.post(f"{base}/resolve", json={"version": 1, "resolution_note": "done"})
    assert r.status_code == 409
    assert error_code(r) == "INVALID_TRANSITION"

    r = await operator.post(f"{base}/acknowledge", json={"version": 1})
    assert r.status_code == 200
    acked = r.json()
    assert acked["status"] == "ACKNOWLEDGED"
    assert acked["version"] == 2
    assert acked["assignee"]["email"] == "operator@marketops.local"

    again = await operator2.post(f"{base}/acknowledge", json={"version": 2})
    assert again.status_code == 409
    assert error_code(again) == "INVALID_TRANSITION"

    me2 = (await operator2.get("/api/v1/auth/me")).json()["user"]["id"]
    r = await operator2.patch(f"{base}/assignment", json={"version": 2, "assignee_id": me2})
    assert r.status_code == 200
    assert r.json()["assignee"]["id"] == me2

    r = await operator.post(f"{base}/comments", json={"body": "  Feed handler restarted.  "})
    assert r.status_code == 201
    assert r.json()["body"] == "Feed handler restarted."
    blank = await operator.post(f"{base}/comments", json={"body": "   "})
    assert blank.status_code == 422

    r = await operator.post(f"{base}/resolve", json={"version": 3, "resolution_note": "fixed"})
    assert r.status_code == 409
    assert error_code(r) == "CONDITION_ACTIVE"

    rt: Runtime = app.state.runtime
    await advance(rt, clock, 1, set())  # feed restored → condition recovers
    current = (await operator.get(base)).json()
    assert current["status"] == "ACKNOWLEDGED"
    assert not current["condition_active"]
    assert current["version"] == 3  # system condition updates do not bump the user version

    r = await operator.post(f"{base}/resolve", json={"version": 3, "resolution_note": "   "})
    assert r.status_code == 422
    assert error_code(r) == "RESOLUTION_NOTE_REQUIRED"
    r = await operator.post(
        f"{base}/resolve", json={"version": 3, "resolution_note": "Restarted synthetic feed."}
    )
    assert r.status_code == 200
    resolved = r.json()
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution_note"]

    r = await operator.post(f"{base}/resolve", json={"version": 4, "resolution_note": "again"})
    assert r.status_code == 409

    timeline = (await operator.get(f"{base}/timeline")).json()["entries"]
    actions = [e["action"] for e in timeline]
    assert actions == [
        "INCIDENT_OPENED",
        "INCIDENT_ACKNOWLEDGED",
        "INCIDENT_ASSIGNED",
        "COMMENT_ADDED",
        "CONDITION_RECOVERED",
        "INCIDENT_RESOLVED",
    ]
    assert timeline[0]["actor_kind"] == "SYSTEM"
    assert timeline[3]["body"] == "Feed handler restarted."
    times = [e["at"] for e in timeline]
    assert times == sorted(times)

    # A later breach after resolution opens a *new* incident.
    await advance(rt, clock, 12, {target})
    page = (await operator.get("/api/v1/incidents", params={"status": ["OPEN"]})).json()
    assert page["total"] == 1
    assert page["items"][0]["id"] != inc["id"]
    assert page["items"][0]["number"] > inc["number"]


async def test_version_conflict_leaves_no_partial_audit(
    app: FastAPI, clock: FakeClock, operator: AsyncClient, operator2: AsyncClient
) -> None:
    await _open_stale_incident(app, clock)
    inc = await _first(operator)
    base = f"/api/v1/incidents/{inc['id']}"
    assert (await operator.post(f"{base}/acknowledge", json={"version": 1})).status_code == 200
    before = await _audits(app)
    r = await operator2.patch(f"{base}/assignment", json={"version": 1, "assignee_id": None})
    assert r.status_code == 409
    body = r.json()["error"]
    assert body["code"] == "VERSION_CONFLICT"
    assert body["details"]["current_version"] == 2
    assert "Reload" in body["message"]
    assert await _audits(app) == before
    still = (await operator.get(base)).json()
    assert still["assignee"] is not None
    assert still["version"] == 2


async def test_assignment_must_target_active_operator(
    app: FastAPI, clock: FakeClock, operator: AsyncClient, viewer: AsyncClient
) -> None:
    await _open_stale_incident(app, clock)
    inc = await _first(operator)
    viewer_id = (await viewer.get("/api/v1/auth/me")).json()["user"]["id"]
    r = await operator.patch(
        f"/api/v1/incidents/{inc['id']}/assignment", json={"version": 1, "assignee_id": viewer_id}
    )
    assert r.status_code == 422
    assert error_code(r) == "INVALID_ASSIGNEE"


async def test_list_filters_and_pagination(
    app: FastAPI, clock: FakeClock, viewer: AsyncClient
) -> None:
    rt: Runtime = app.state.runtime
    clock.advance(30)
    await rt.evaluator.evaluate_once()  # all 5 instruments stale
    page = (await viewer.get("/api/v1/incidents", params={"limit": 2, "type": "STALE"})).json()
    assert page["total"] == 5
    assert len(page["items"]) == 2
    nxt = (
        await viewer.get("/api/v1/incidents", params={"limit": 2, "offset": 2, "type": "STALE"})
    ).json()
    assert not {i["id"] for i in page["items"]} & {i["id"] for i in nxt["items"]}
    sym = page["items"][0]["symbol"]
    by_sym = (await viewer.get("/api/v1/incidents", params={"symbol": sym.lower()})).json()
    assert by_sym["total"] == 1
    none = (await viewer.get("/api/v1/incidents", params={"severity": "LOW"})).json()
    assert none["total"] == 0
    bad = await viewer.get("/api/v1/incidents", params={"status": "CLOSED"})
    assert bad.status_code == 422
