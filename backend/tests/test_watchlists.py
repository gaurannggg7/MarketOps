from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient

from tests.conftest import OPERATOR, login, make_client
from tests.helpers import error_code, instruments


async def test_crud_and_idempotent_membership(operator: AsyncClient) -> None:
    inst = await instruments(operator)
    r = await operator.post("/api/v1/watchlists", json={"name": "  Rates desk  "})
    assert r.status_code == 201
    wl = r.json()
    assert wl["name"] == "Rates desk"
    for _ in range(2):
        r = await operator.post(f"/api/v1/watchlists/{wl['id']}/items/{inst[0]['id']}")
        assert r.status_code == 200
    assert r.json()["instrument_ids"] == [inst[0]["id"]]
    r = await operator.get("/api/v1/instruments", params={"watchlist_id": wl["id"]})
    assert [i["id"] for i in r.json()["items"]] == [inst[0]["id"]]
    for _ in range(2):
        r = await operator.delete(f"/api/v1/watchlists/{wl['id']}/items/{inst[0]['id']}")
        assert r.status_code == 200
    assert r.json()["instrument_ids"] == []
    r = await operator.patch(f"/api/v1/watchlists/{wl['id']}", json={"name": "Renamed"})
    assert r.json()["name"] == "Renamed"
    dup = await operator.post("/api/v1/watchlists", json={"name": "Renamed"})
    assert dup.status_code == 409
    assert error_code(dup) == "DUPLICATE_NAME"
    blank = await operator.post("/api/v1/watchlists", json={"name": "   "})
    assert blank.status_code == 422
    assert (await operator.delete(f"/api/v1/watchlists/{wl['id']}")).status_code == 204


async def test_membership_survives_new_session_and_app_restart(
    operator: AsyncClient, app: FastAPI
) -> None:
    inst = await instruments(operator)
    wl = (await operator.post("/api/v1/watchlists", json={"name": "Persist"})).json()
    await operator.post(f"/api/v1/watchlists/{wl['id']}/items/{inst[2]['id']}")
    await app.state.runtime.stop()
    await app.state.runtime.start()  # in-memory state rebuilt; watchlists come from PostgreSQL
    async with make_client(app) as fresh:
        await login(fresh, OPERATOR)
        lists = (await fresh.get("/api/v1/watchlists")).json()
        persisted = next(w for w in lists if w["name"] == "Persist")
        assert persisted["instrument_ids"] == [inst[2]["id"]]


async def test_users_cannot_touch_each_others_watchlists(
    operator: AsyncClient, operator2: AsyncClient
) -> None:
    inst = await instruments(operator)
    mine = (await operator.post("/api/v1/watchlists", json={"name": "Private"})).json()
    path = f"/api/v1/watchlists/{mine['id']}"
    for r in (
        await operator2.patch(path, json={"name": "Hijacked"}),
        await operator2.delete(path),
        await operator2.post(f"{path}/items/{inst[0]['id']}"),
        await operator2.delete(f"{path}/items/{inst[0]['id']}"),
        await operator2.get("/api/v1/instruments", params={"watchlist_id": mine["id"]}),
    ):
        assert r.status_code == 404
    assert all(w["id"] != mine["id"] for w in (await operator2.get("/api/v1/watchlists")).json())
    still = [w for w in (await operator.get("/api/v1/watchlists")).json() if w["id"] == mine["id"]]
    assert still[0]["name"] == "Private"


async def test_viewer_manages_own_watchlist(viewer: AsyncClient) -> None:
    r = await viewer.post("/api/v1/watchlists", json={"name": "Viewer list"})
    assert r.status_code == 201
