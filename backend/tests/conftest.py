"""Test fixtures. Tests run against a real PostgreSQL database (``marketops_test``)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.clock import FakeClock
from app.config import Settings
from app.db import make_engine, make_sessionmaker
from app.main import create_app
from app.seed import BUSINESS_TABLES, seed

PASSWORDS = {
    "DEMO_OPERATOR_PASSWORD": "operator-test-pw",
    "DEMO_OPERATOR2_PASSWORD": "operator2-test-pw",
    "DEMO_VIEWER_PASSWORD": "viewer-test-pw",
}
OPERATOR = ("operator@marketops.local", PASSWORDS["DEMO_OPERATOR_PASSWORD"])
OPERATOR2 = ("operator2@marketops.local", PASSWORDS["DEMO_OPERATOR2_PASSWORD"])
VIEWER = ("viewer@marketops.local", PASSWORDS["DEMO_VIEWER_PASSWORD"])
ORIGIN = "http://localhost:5173"


def _test_db_url() -> str:
    explicit = os.environ.get("MARKETOPS_TEST_DATABASE_URL")
    if explicit:
        return explicit
    base = make_url(Settings().database_url)
    return base.set(database="marketops_test").render_as_string(hide_password=False)


TEST_DB_URL = _test_db_url()


@pytest.fixture(scope="session", autouse=True)
def _database() -> None:
    os.environ.update(PASSWORDS)
    url = make_url(TEST_DB_URL)
    admin = url.set(drivername="postgresql", database="postgres")
    dsn = admin.render_as_string(hide_password=False)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{url.database}"')
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.attributes["database_url"] = TEST_DB_URL
    cfg.attributes["configure_logging"] = False
    command.upgrade(cfg, "head")


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        database_url=TEST_DB_URL,
        simulator_enabled=False,
        warmup_seconds=5,
        allowed_origins=[ORIGIN],
        login_max_failures=3,
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = make_engine(TEST_DB_URL, null_pool=True)
    yield make_sessionmaker(engine)
    await engine.dispose()


@pytest.fixture
async def seeded(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with sessionmaker() as db:
        await db.execute(text(f"TRUNCATE {', '.join(BUSINESS_TABLES)} RESTART IDENTITY CASCADE"))
        await db.commit()
        await seed(db, instruments=5)


@pytest.fixture
async def app(seeded: None, settings: Settings, clock: FakeClock) -> AsyncIterator[FastAPI]:
    application = create_app(settings, clock, null_pool=True)
    await application.state.runtime.start()
    yield application
    await application.state.runtime.stop()
    await application.state.engine.dispose()


def make_client(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers={"Origin": ORIGIN}
    )


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with make_client(app) as c:
        yield c


async def login(client: AsyncClient, creds: tuple[str, str]) -> dict[str, Any]:
    r = await client.post("/api/v1/auth/login", json={"email": creds[0], "password": creds[1]})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    client.headers["X-CSRF-Token"] = body["csrf_token"]
    return body


@pytest.fixture
async def operator(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with make_client(app) as c:
        await login(c, OPERATOR)
        yield c


@pytest.fixture
async def operator2(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with make_client(app) as c:
        await login(c, OPERATOR2)
        yield c


@pytest.fixture
async def viewer(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with make_client(app) as c:
        await login(c, VIEWER)
        yield c
