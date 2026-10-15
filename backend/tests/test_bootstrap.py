from __future__ import annotations

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from app.config import Settings
from app.main import create_app, migration_head
from app.models import Instrument, User
from tests.conftest import TEST_DB_URL

BOOT_DB = "marketops_bootstrap_test"


def _fresh_db() -> str:
    url = make_url(TEST_DB_URL)
    admin = url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{BOOT_DB}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{BOOT_DB}"')
    return url.set(database=BOOT_DB).render_as_string(hide_password=False)


def test_startup_bootstrap_migrates_and_seeds_an_empty_database(settings: Settings) -> None:
    cfg = settings.model_copy(
        update={"database_url": _fresh_db(), "startup_bootstrap": True, "simulator_enabled": False}
    )
    hashes: dict[str, str] = {}
    for run in range(2):  # second start = a free-tier wake-up: idempotent, no re-hashing
        app = create_app(cfg, null_pool=True)
        with TestClient(app) as tc:
            assert tc.get("/api/v1/health/ready").json()["checks"]["migrations"] == "ok"
            runtime = app.state.runtime
            assert len(runtime.symbols) == 200

            async def check(app: FastAPI = app) -> dict[str, str]:
                async with app.state.sessionmaker() as db:
                    version = (
                        await db.execute(text("SELECT version_num FROM alembic_version"))
                    ).scalar_one()
                    assert version == migration_head()
                    count = await db.execute(select(func.count()).select_from(Instrument))
                    assert count.scalar_one() == 200
                    rows = (await db.execute(select(User.email, User.password_hash))).all()
                    return {e: h for e, h in rows}

            assert tc.portal is not None
            current = tc.portal.call(check)
        if run == 0:
            hashes = current
        else:
            assert current == hashes
