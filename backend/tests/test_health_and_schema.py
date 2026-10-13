from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


async def test_health_endpoints(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/health/live")).json()["status"] == "ok"
    ready = await client.get("/api/v1/health/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"database": "ok", "migrations": "ok", "simulator": "ok"}


async def test_ready_reports_unavailable_when_not_started(
    app: FastAPI, client: AsyncClient
) -> None:
    await app.state.runtime.stop()
    r = await client.get("/api/v1/health/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["simulator"] == "not started"


async def test_partial_unique_indexes_exist(app: FastAPI) -> None:
    async with app.state.sessionmaker() as db:
        rows = dict(
            (
                await db.execute(
                    text(
                        "SELECT indexname, indexdef FROM pg_indexes WHERE indexname IN "
                        "('uq_incidents_one_unresolved_per_rule', 'uq_alert_rules_one_enabled')"
                    )
                )
            ).all()
        )
    assert "WHERE (status <> 'RESOLVED'" in rows["uq_incidents_one_unresolved_per_rule"]
    assert "WHERE enabled" in rows["uq_alert_rules_one_enabled"]


async def test_database_rejects_inverted_prices(app: FastAPI) -> None:
    async with app.state.sessionmaker() as db:
        with pytest.raises(IntegrityError):
            await db.execute(
                text(
                    "INSERT INTO quote_samples (instrument_id, bid, ask, volume, source_time, "
                    "received_time) SELECT id, -1, 1, 0, now(), now() FROM instruments LIMIT 1"
                )
            )


async def test_request_id_and_error_shape(client: AsyncClient) -> None:
    r = await client.get("/api/v1/instruments", headers={"X-Request-ID": "trace-123"})
    assert r.headers["x-request-id"] == "trace-123"
    assert r.json()["error"] == {
        "code": "UNAUTHENTICATED",
        "message": r.json()["error"]["message"],
        "details": None,
        "request_id": "trace-123",
    }
