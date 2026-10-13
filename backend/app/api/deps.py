from __future__ import annotations

from datetime import datetime

from fastapi import Request

from app.runtime import Runtime


def runtime_of(request: Request) -> Runtime:
    runtime: Runtime = request.app.state.runtime
    return runtime


def now_of(request: Request) -> datetime:
    return runtime_of(request).clock.now()


def correlation_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))
