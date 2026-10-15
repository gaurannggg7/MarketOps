from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.auth.tickets import StreamTickets
from app.config import Settings, normalize_database_url
from app.main import create_app
from tests.conftest import OPERATOR, ORIGIN

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_tickets_are_single_use_and_expire() -> None:
    t = StreamTickets(ttl_seconds=30)
    uid, sid = uuid.uuid4(), uuid.uuid4()
    ticket, expires = t.issue(uid, sid, NOW)
    assert expires == NOW + timedelta(seconds=30)
    grant = t.redeem(ticket, NOW)
    assert grant is not None
    assert grant.session_id == sid
    assert t.redeem(ticket, NOW) is None  # single use
    late, _ = t.issue(uid, sid, NOW)
    assert t.redeem(late, NOW + timedelta(seconds=31)) is None
    assert t.redeem("forged", NOW) is None


def test_provider_database_urls_use_psycopg_driver() -> None:
    neon = "postgresql://u:p@ep-x.us-east-1.aws.neon.tech/neondb?sslmode=require"
    assert normalize_database_url(neon).startswith("postgresql+psycopg://u:p@ep-x")
    assert normalize_database_url("postgres://u@h/db") == "postgresql+psycopg://u@h/db"
    assert Settings(database_url=neon).database_url.endswith("?sslmode=require")


@pytest.fixture
def split_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "simulator_enabled": True,
            "stream_ticket_auth_enabled": True,
            "max_stream_connections_per_session": 2,
        }
    )


def _login(tc: TestClient) -> None:
    r = tc.post(
        "/api/v1/auth/login",
        json={"email": OPERATOR[0], "password": OPERATOR[1]},
        headers={"Origin": ORIGIN},
    )
    assert r.status_code == 200
    tc.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    tc.headers["Origin"] = ORIGIN


def _attempt(tc: TestClient, ticket: str, origin: str = ORIGIN) -> None:
    with tc.websocket_connect("/ws/market", headers={"origin": origin}) as ws:
        ws.send_json({"type": "auth", "ticket": ticket})
        ws.receive_json()


def _close_code(tc: TestClient, ticket: str) -> int:
    with pytest.raises(WebSocketDisconnect) as exc:
        _attempt(tc, ticket)
    code: int = exc.value.code
    return code


def _ticket(tc: TestClient) -> str:
    r = tc.post("/api/v1/stream/ticket")
    assert r.status_code == 200, r.text
    ticket: str = r.json()["ticket"]
    return ticket


def test_ticket_endpoint_disabled_by_default(seeded: None, settings: Settings) -> None:
    with TestClient(create_app(settings, null_pool=True)) as tc:
        _login(tc)
        assert tc.post("/api/v1/stream/ticket").status_code == 404


def test_cookieless_socket_authenticates_with_ticket(
    seeded: None, split_settings: Settings
) -> None:
    with TestClient(create_app(split_settings, null_pool=True)) as tc:
        _login(tc)
        ticket = _ticket(tc)
        tc.cookies.clear()  # the stream host never sees the session cookie in split-origin mode
        with tc.websocket_connect("/ws/market", headers={"origin": ORIGIN}) as ws:
            ws.send_json({"type": "auth", "ticket": ticket})
            snap = ws.receive_json()
            assert snap["type"] == "snapshot"
            assert len(snap["quotes"]) == 5
            ws.close()  # client-initiated close; TestClient cancels a still-streaming server
        # Reusing the same ticket fails.
        assert _close_code(tc, ticket) == 4401


def test_ticket_auth_rejects_bad_tickets_and_wrong_origin(
    seeded: None, split_settings: Settings
) -> None:
    with TestClient(create_app(split_settings, null_pool=True)) as tc:
        assert _close_code(tc, "forged") == 4401
        with (
            pytest.raises(WebSocketDisconnect) as bad_origin,
            tc.websocket_connect("/ws/market", headers={"origin": "https://evil.example"}),
        ):
            pass
        assert bad_origin.value.code == 4403


def test_ticket_is_useless_after_logout(seeded: None, split_settings: Settings) -> None:
    with TestClient(create_app(split_settings, null_pool=True)) as tc:
        _login(tc)
        ticket = _ticket(tc)
        assert tc.post("/api/v1/auth/logout").status_code == 204
        assert _close_code(tc, ticket) == 4401


def test_per_session_connection_cap(seeded: None, split_settings: Settings) -> None:
    with TestClient(create_app(split_settings, null_pool=True)) as tc:
        _login(tc)
        headers = {"origin": ORIGIN}
        with (
            tc.websocket_connect("/ws/market", headers=headers) as a,
            tc.websocket_connect("/ws/market", headers=headers) as b,
        ):
            assert a.receive_json()["type"] == "snapshot"
            assert b.receive_json()["type"] == "snapshot"
            with tc.websocket_connect("/ws/market", headers=headers) as c:
                refused = c.receive_json()
                assert refused == {"type": "resync", "reason": "too_many_session_connections"}
                with pytest.raises(WebSocketDisconnect) as closed:
                    c.receive_json()
                assert closed.value.code == 1013
            a.close()
            b.close()
