from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

from app.models import AuditEvent
from tests.helpers import error_code, instruments, rule_for


async def _audit_count(app: FastAPI) -> int:
    async with app.state.sessionmaker() as db:
        return int((await db.execute(select(func.count()).select_from(AuditEvent))).scalar_one())


async def test_update_with_version_check(operator: AsyncClient, app: FastAPI) -> None:
    inst = (await instruments(operator))[0]
    rule = await rule_for(operator, inst["id"], "WIDE_SPREAD")
    assert rule["unit"] == "BPS"
    assert rule["threshold"] == "50"
    r = await operator.patch(
        f"/api/v1/rules/{rule['id']}", json={"version": 1, "threshold": "75.5"}
    )
    assert r.status_code == 200
    assert r.json()["version"] == 2
    assert r.json()["threshold"] == "75.5"
    before = await _audit_count(app)
    stale = await operator.patch(
        f"/api/v1/rules/{rule['id']}", json={"version": 1, "enabled": False}
    )
    assert stale.status_code == 409
    assert error_code(stale) == "VERSION_CONFLICT"
    assert stale.json()["error"]["details"]["current_version"] == 2
    assert await _audit_count(app) == before  # failed change leaves no audit entry
    still = await rule_for(operator, inst["id"], "WIDE_SPREAD")
    assert still["threshold"] == "75.5"
    assert still["enabled"]


async def test_threshold_validation_messages(operator: AsyncClient) -> None:
    inst = (await instruments(operator))[0]
    rule = await rule_for(operator, inst["id"], "STALE")
    for value in ("0", "-5", "3601", "1.234", "NaN"):
        r = await operator.patch(
            f"/api/v1/rules/{rule['id']}", json={"version": 1, "threshold": value}
        )
        assert r.status_code == 422, value
        assert r.json()["error"]["code"] in {"INVALID_THRESHOLD", "VALIDATION_ERROR"}
    r = await operator.patch(f"/api/v1/rules/{rule['id']}", json={"version": 1, "threshold": "0"})
    assert "between 1 and 3600 seconds" in r.json()["error"]["message"]


async def test_one_enabled_rule_per_instrument_and_type(operator: AsyncClient) -> None:
    inst = (await instruments(operator))[0]
    r = await operator.post(
        "/api/v1/rules", json={"instrument_id": inst["id"], "rule_type": "STALE", "threshold": "5"}
    )
    assert r.status_code == 409
    assert error_code(r) == "RULE_ALREADY_ENABLED"
    disabled = await operator.post(
        "/api/v1/rules",
        json={
            "instrument_id": inst["id"],
            "rule_type": "STALE",
            "threshold": "5",
            "enabled": False,
        },
    )
    assert disabled.status_code == 201
    r = await operator.patch(
        f"/api/v1/rules/{disabled.json()['id']}", json={"version": 1, "enabled": True}
    )
    assert r.status_code == 409
    assert error_code(r) == "RULE_ALREADY_ENABLED"
