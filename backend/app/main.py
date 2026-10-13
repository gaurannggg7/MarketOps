"""FastAPI application factory and lifespan (one Runtime per process)."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, FastAPI, Request, Response

from app.api import auth, incidents, market, rules, system, watchlists, ws
from app.auth.security import LoginThrottle
from app.clock import Clock, SystemClock
from app.config import Settings, get_settings
from app.db import make_engine, make_sessionmaker
from app.errors import install_error_handlers
from app.runtime import Runtime

log = logging.getLogger("marketops")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def migration_head() -> str | None:
    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def create_app(
    settings: Settings | None = None, clock: Clock | None = None, *, null_pool: bool = False
) -> FastAPI:
    settings = settings or get_settings()
    clock = clock or SystemClock()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await app.state.runtime.start()
        log.info(
            "runtime started epoch=%s instruments=%d",
            app.state.runtime.hub.epoch,
            len(app.state.runtime.hub.quotes),
        )
        try:
            yield
        finally:
            await app.state.runtime.stop()
            await app.state.engine.dispose()
            log.info("runtime stopped")

    app = FastAPI(
        title="MarketOps API",
        version="1.0.0",
        description="Synthetic market-data monitoring and incident management. All market data "
        "is simulated; no exchange connectivity.",
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
    )
    engine = make_engine(settings.database_url, null_pool=null_pool)
    app.state.settings = settings
    app.state.clock = clock
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.runtime = Runtime(settings, clock, app.state.sessionmaker)
    app.state.login_throttle = LoginThrottle(
        settings.login_max_failures, settings.login_window_seconds
    )
    app.state.migration_head = migration_head()

    @app.middleware("http")
    async def request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    install_error_handlers(app)
    api = APIRouter(prefix="/api/v1")
    for module in (auth, market, watchlists, rules, incidents, system):
        api.include_router(module.router)
    app.include_router(api)
    app.include_router(ws.router)
    return app
