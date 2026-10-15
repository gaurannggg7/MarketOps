from __future__ import annotations

from datetime import timedelta

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

from app.clock import FakeClock
from app.models import Session as DbSession
from tests.conftest import OPERATOR, VIEWER, login, make_client
from tests.helpers import error_code, instruments, rule_for


async def test_login_profile_logout(client: AsyncClient) -> None:
    body = await login(client, OPERATOR)
    assert body["user"]["role"] == "OPERATOR"
    cookie = client.cookies.get("marketops_session")
    assert cookie
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["csrf_token"] == body["csrf_token"]  # stable for the session
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    client.cookies.set("marketops_session", cookie)  # replaying a revoked token must fail
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert error_code(r) == "UNAUTHENTICATED"


async def test_session_token_not_stored_in_plaintext(client: AsyncClient, app: FastAPI) -> None:
    await login(client, OPERATOR)
    token = client.cookies.get("marketops_session")
    async with app.state.sessionmaker() as db:
        hashes = (await db.execute(select(DbSession.token_hash))).scalars().all()
    assert token not in hashes
    assert all(len(h) == 64 for h in hashes)


async def test_wrong_password_is_generic_and_throttled(client: AsyncClient) -> None:
    for _ in range(3):
        r = await client.post(
            "/api/v1/auth/login", json={"email": OPERATOR[0], "password": "wrong"}
        )
        assert r.status_code == 401
        assert r.json()["error"]["message"] == "Email or password is incorrect."
    r = await client.post(
        "/api/v1/auth/login", json={"email": OPERATOR[0], "password": OPERATOR[1]}
    )
    assert r.status_code == 429
    assert error_code(r) == "TOO_MANY_ATTEMPTS"
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@marketops.local", "password": "x"}
    )
    assert unknown.status_code == 401


async def test_idle_and_absolute_expiry(app: FastAPI, clock: FakeClock) -> None:
    async with make_client(app) as c:
        await login(c, VIEWER)
        clock.advance(29 * 60)
        assert (await c.get("/api/v1/auth/me")).status_code == 200  # refreshes last_seen
        clock.advance(31 * 60)
        assert (await c.get("/api/v1/auth/me")).status_code == 401  # idle timeout
    async with make_client(app) as c:
        await login(c, VIEWER)
        for _ in range(26):  # stay active every 28 minutes until the 12h absolute limit
            clock.advance(28 * 60)
            await c.get("/api/v1/auth/me")
        assert (await c.get("/api/v1/auth/me")).status_code == 401


async def test_csrf_and_origin_required_for_writes(operator: AsyncClient) -> None:
    csrf = operator.headers.pop("X-CSRF-Token")
    r = await operator.post("/api/v1/watchlists", json={"name": "No CSRF"})
    assert r.status_code == 403
    assert error_code(r) == "CSRF_REJECTED"
    r = await operator.post(
        "/api/v1/watchlists", json={"name": "Bad"}, headers={"X-CSRF-Token": "forged"}
    )
    assert error_code(r) == "CSRF_REJECTED"
    r = await operator.post(
        "/api/v1/watchlists",
        json={"name": "Evil"},
        headers={"X-CSRF-Token": csrf, "Origin": "https://evil.example"},
    )
    assert r.status_code == 403
    assert error_code(r) == "ORIGIN_REJECTED"
    r = await operator.post(
        "/api/v1/watchlists", json={"name": "OK"}, headers={"X-CSRF-Token": csrf}
    )
    assert r.status_code == 201


async def test_login_requires_allowed_origin(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": OPERATOR[0], "password": OPERATOR[1]},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403


async def test_viewer_cannot_mutate(viewer: AsyncClient, app: FastAPI) -> None:
    inst = (await instruments(viewer))[0]
    rule = await rule_for(viewer, inst["id"], "STALE")
    attempts = [
        viewer.patch(f"/api/v1/rules/{rule['id']}", json={"version": 1, "threshold": "20"}),
        viewer.post(
            "/api/v1/rules",
            json={"instrument_id": inst["id"], "rule_type": "STALE", "threshold": "5"},
        ),
        viewer.post(
            "/api/v1/demo/scenarios", json={"kind": "STALE_QUOTES", "instrument_id": inst["id"]}
        ),
        viewer.post("/api/v1/demo/reset", json={"confirm": "RESET"}),
        viewer.post(f"/api/v1/incidents/{rule['id']}/acknowledge", json={"version": 1}),
        viewer.post(f"/api/v1/incidents/{rule['id']}/comments", json={"body": "hi"}),
        viewer.post(
            f"/api/v1/incidents/{rule['id']}/resolve", json={"version": 1, "resolution_note": "x"}
        ),
    ]
    for coro in attempts:
        r = await coro
        assert r.status_code == 403, r.text
        assert error_code(r) == "FORBIDDEN"
    assert app.state.runtime.scenarios.active == {}
    # Viewer reads still work.
    assert (await viewer.get("/api/v1/incidents")).status_code == 200
    assert (await viewer.get("/api/v1/system/status")).status_code == 200


async def test_unauthenticated_reads_rejected(client: AsyncClient) -> None:
    for path in (
        "/api/v1/instruments",
        "/api/v1/incidents",
        "/api/v1/market/snapshot",
        "/api/v1/events",
        "/api/v1/system/status",
    ):
        r = await client.get(path)
        assert r.status_code == 401
        assert r.json()["error"]["request_id"]


async def test_logout_revokes_only_that_session(app: FastAPI) -> None:
    async with make_client(app) as a, make_client(app) as b:
        await login(a, OPERATOR)
        await login(b, OPERATOR)
        await a.post("/api/v1/auth/logout")
        assert (await b.get("/api/v1/auth/me")).status_code == 200
        async with app.state.sessionmaker() as db:
            revoked = (
                await db.execute(select(func.count()).where(DbSession.revoked_at.is_not(None)))
            ).scalar_one()
        assert revoked == 1
    assert timedelta(0) == timedelta(0)


async def test_session_probe_reports_signed_out_without_401(client: AsyncClient) -> None:
    r = await client.get("/api/v1/auth/session")
    assert r.status_code == 200
    assert r.json() == {"authenticated": False, "session": None, "demo_available": False}
    body = await login(client, OPERATOR)
    r = await client.get("/api/v1/auth/session")
    assert r.json()["authenticated"] is True
    assert r.json()["session"]["csrf_token"] == body["csrf_token"]
