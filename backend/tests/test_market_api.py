from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import insert

from app.clock import FakeClock
from app.models import MarketEvent, QuoteSample
from tests.helpers import instruments


async def test_catalog_search_and_detail(viewer: AsyncClient) -> None:
    items = await instruments(viewer)
    assert len(items) == 5
    sym = items[1]["symbol"]
    r = await viewer.get("/api/v1/instruments", params={"search": sym.lower()})
    assert sym in [i["symbol"] for i in r.json()["items"]]
    detail = (await viewer.get(f"/api/v1/instruments/{items[1]['id']}")).json()
    assert {r["rule_type"] for r in detail["rules"]} == {"STALE", "WIDE_SPREAD"}
    assert (await viewer.get(f"/api/v1/instruments/{uuid.uuid4()}")).status_code == 404


async def test_snapshot_has_epoch_seq_and_decimal_strings(viewer: AsyncClient) -> None:
    snap = (await viewer.get("/api/v1/market/snapshot")).json()
    assert snap["epoch"]
    assert snap["seq"] == 0
    q = snap["quotes"][0]
    assert isinstance(q["bid"], str)
    assert Decimal(q["ask"]) >= Decimal(q["bid"])


async def test_history_is_bucketed_and_bounded(
    viewer: AsyncClient, app: FastAPI, clock: FakeClock
) -> None:
    inst = (await instruments(viewer))[0]
    now = clock.now()
    rows = [
        {
            "instrument_id": uuid.UUID(inst["id"]),
            "bid": Decimal("100.00"),
            "ask": Decimal("100.10"),
            "volume": 1000 + s,
            "source_time": now - timedelta(seconds=s),
            "received_time": now - timedelta(seconds=s),
        }
        for s in range(1, 2 * 3600)  # two hours of 1/s samples
    ]
    async with app.state.sessionmaker() as db:
        await db.execute(insert(QuoteSample), rows)
        await db.commit()
    for rng, bucket, max_expected in (("5m", 1, 301), ("15m", 3, 301), ("1h", 10, 361)):
        r = await viewer.get(f"/api/v1/instruments/{inst['id']}/history", params={"range": rng})
        body = r.json()
        assert r.status_code == 200
        assert body["resolution_seconds"] == bucket
        assert 0 < len(body["points"]) <= min(max_expected, body["max_points"])
        times = [p["t"] for p in body["points"]]
        assert times == sorted(times)
        assert body["points"][0]["spread_bps"] == "10.00"
    bad = await viewer.get(f"/api/v1/instruments/{inst['id']}/history", params={"range": "1d"})
    assert bad.status_code == 422


async def test_events_pagination_sort_filter_and_tie_breakers(
    viewer: AsyncClient, app: FastAPI, clock: FakeClock
) -> None:
    items = await instruments(viewer)
    t0 = clock.now()
    rows = []
    for n in range(30):
        rows.append(
            {
                "instrument_id": uuid.UUID(items[n % 3]["id"]),
                "event_type": "SIM_A" if n % 2 else "SIM_B",
                # pairs of identical timestamps force the id tie-breaker
                "observed_at": t0 - timedelta(seconds=n // 2),
                "evidence": {"n": n},
            }
        )
    async with app.state.sessionmaker() as db:
        await db.execute(insert(MarketEvent), rows)
        await db.commit()

    async def page(**params: Any) -> dict[str, Any]:
        r = await viewer.get("/api/v1/events", params=params)
        assert r.status_code == 200, r.text
        result: dict[str, Any] = r.json()
        return result

    first = await page(offset=0, limit=10, sort="-observed_at", event_type="SIM_A")
    second = await page(offset=10, limit=10, sort="-observed_at", event_type="SIM_A")
    assert first["total"] == 15
    ids = [e["id"] for e in first["items"] + second["items"]]
    assert len(ids) == len(set(ids)) == 15
    keys = [(e["observed_at"], e["id"]) for e in first["items"] + second["items"]]
    assert keys == sorted(keys, reverse=True)

    asc = await page(limit=500, sort="symbol", instrument_id=items[0]["id"])
    assert {e["symbol"] for e in asc["items"]} == {items[0]["symbol"]}
    ordered = [(e["observed_at"], e["id"]) for e in asc["items"]]
    assert ordered == sorted(ordered)

    for bad in (
        {"limit": 501},
        {"sort": "evidence"},
        {"event_type": "drop table"},
        {"since": t0.isoformat(), "until": (t0 - timedelta(hours=1)).isoformat()},
    ):
        r = await viewer.get("/api/v1/events", params=bad)
        assert r.status_code == 422, bad
