from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app
from app.streaming.hub import Connection, Control, Quote, StreamHub
from tests.conftest import OPERATOR, ORIGIN

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _quote(n: int) -> Quote:
    return Quote(uuid.UUID(int=n), f"S{n}", Decimal("10.00"), Decimal("10.01"), n, NOW, NOW)


def _data(conn: Connection) -> list[tuple[int | None, str]]:
    items = _drain(conn)
    assert not any(isinstance(i, Control) for i in items)
    return [i for i in items if not isinstance(i, Control)]


def _drain(conn: Connection) -> list[tuple[int | None, str] | Control]:
    out = []
    while not conn.queue.empty():
        out.append(conn.queue.get_nowait())
    return out


async def test_registration_has_no_snapshot_subscription_race() -> None:
    hub = StreamHub(queue_max=10_000)
    hub.ingest([_quote(i) for i in range(5)])
    stop = asyncio.Event()

    async def publisher() -> None:
        n = 0
        while not stop.is_set():
            n += 1
            hub.ingest([_quote(n % 5)])
            await hub.flush(NOW, float(n))
            await asyncio.sleep(0)

    task = asyncio.create_task(publisher())
    registrations = []
    for _ in range(50):
        registrations.append(await hub.register(uuid.uuid4(), uuid.uuid4(), NOW))
        await asyncio.sleep(0)
    stop.set()
    await task
    for conn, snapshot, watermark in registrations:
        assert json.loads(snapshot)["seq"] == watermark
        seqs = [seq for seq, _ in _data(conn) if seq is not None]
        # Everything queued is newer than the snapshot and strictly consecutive.
        assert seqs == list(range(watermark + 1, watermark + 1 + len(seqs)))


async def test_heartbeat_does_not_advance_sequence() -> None:
    hub = StreamHub(queue_max=10)
    conn, _, _ = await hub.register(uuid.uuid4(), uuid.uuid4(), NOW)
    hub.ingest([_quote(1)])
    await hub.flush(NOW, 0.0)
    await hub.heartbeat(NOW)
    await hub.heartbeat(NOW)
    assert hub.seq == 1
    items = _data(conn)
    assert [s for s, _ in items] == [1, None, None]
    assert {json.loads(p)["seq"] for _, p in items} == {1}
    assert await hub.flush(NOW, 0.0) is None  # nothing pending → no empty batches


async def test_slow_consumer_overflow_triggers_resync_not_unbounded_buffering() -> None:
    hub = StreamHub(queue_max=3)
    conn, _, _ = await hub.register(uuid.uuid4(), uuid.uuid4(), NOW)
    for n in range(6):
        hub.ingest([_quote(n)])
        await hub.flush(NOW, float(n))
    items = _drain(conn)
    assert len(items) == 1
    assert isinstance(items[0], Control)
    assert json.loads(items[0].message) == {
        "type": "resync",
        "reason": "queue_overflow",
        "epoch": hub.epoch,
    }
    assert hub.stats.overflow_disconnects == 1


async def test_new_epoch_resets_sequence() -> None:
    hub = StreamHub(queue_max=10)
    old = hub.epoch
    hub.ingest([_quote(1)])
    await hub.flush(NOW, 0.0)
    assert await hub.start_new_epoch() != old
    assert hub.seq == 0


# ---- end-to-end WebSocket through the real app and lifespan ---------------------------------


@pytest.fixture
def live_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"simulator_enabled": True, "heartbeat_interval_ms": 200})


def _login(tc: TestClient) -> str:
    r = tc.post(
        "/api/v1/auth/login",
        json={"email": OPERATOR[0], "password": OPERATOR[1]},
        headers={"Origin": ORIGIN},
    )
    assert r.status_code == 200
    tc.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    tc.headers["Origin"] = ORIGIN
    return str(r.cookies.get("marketops_session"))


def test_socket_handshake_requires_session_and_origin(
    seeded: None, live_settings: Settings
) -> None:
    with TestClient(create_app(live_settings, null_pool=True)) as tc:
        with (
            pytest.raises(WebSocketDisconnect) as no_session,
            tc.websocket_connect("/ws/market", headers={"origin": ORIGIN}),
        ):
            pass
        assert no_session.value.code == 4401
        cookie = _login(tc)
        with (
            pytest.raises(WebSocketDisconnect) as bad_origin,
            tc.websocket_connect(
                "/ws/market",
                headers={"origin": "https://evil.example", "cookie": f"marketops_session={cookie}"},
            ),
        ):
            pass
        assert bad_origin.value.code == 4403


def test_snapshot_then_ordered_deltas_and_scenario_disconnect(
    seeded: None, live_settings: Settings
) -> None:
    app = create_app(live_settings, null_pool=True)
    with TestClient(app) as tc:
        cookie = _login(tc)
        headers = {"origin": ORIGIN, "cookie": f"marketops_session={cookie}"}
        with tc.websocket_connect("/ws/market", headers=headers) as ws:
            snap = ws.receive_json()
            assert snap["type"] == "snapshot"
            assert len(snap["quotes"]) == 5
            last, heartbeats = snap["seq"], 0
            while heartbeats < 2:
                msg = ws.receive_json()
                assert msg["epoch"] == snap["epoch"]
                if msg["type"] == "delta":
                    assert msg["seq"] == last + 1
                    last = msg["seq"]
                    assert all(Decimal(q["ask"]) >= Decimal(q["bid"]) for q in msg["quotes"])
                else:
                    assert msg["type"] == "heartbeat"
                    assert msg["seq"] <= last + 1
                    heartbeats += 1
            r = tc.post("/api/v1/demo/scenarios", json={"kind": "DISCONNECT_STREAM"})
            assert r.status_code == 201, r.text
            while True:
                msg = ws.receive_json()
                if msg["type"] == "resync":
                    assert msg["reason"] == "scenario_disconnect"
                    break
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 4001
        runtime = app.state.runtime
        assert runtime.tasks_alive
    # Leaving the context runs lifespan shutdown: background tasks are cancelled and drained.
    assert runtime._tasks == []
    assert not runtime.running
    assert runtime.hub.connection_count == 0


def test_logout_closes_that_sessions_stream(seeded: None, live_settings: Settings) -> None:
    with TestClient(create_app(live_settings, null_pool=True)) as tc:
        cookie = _login(tc)
        with tc.websocket_connect(
            "/ws/market", headers={"origin": ORIGIN, "cookie": f"marketops_session={cookie}"}
        ) as ws:
            ws.receive_json()
            assert tc.post("/api/v1/auth/logout").status_code == 204
            while True:
                msg = ws.receive_json()
                if msg["type"] == "resync":
                    assert msg["reason"] == "logged_out"
                    break
