"""Consistent error payloads: {"error": {code, message, details, request_id}}."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("marketops.errors")


class AppError(Exception):
    def __init__(
        self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def not_found(entity: str) -> AppError:
    return AppError(404, "NOT_FOUND", f"{entity} was not found.")


def forbidden(message: str = "Your role does not allow this action.") -> AppError:
    return AppError(403, "FORBIDDEN", message)


def version_conflict(entity: str, current_version: int) -> AppError:
    return AppError(
        409,
        "VERSION_CONFLICT",
        f"This {entity} was changed by someone else. Reload to see the latest version, "
        "then reapply your change.",
        {"current_version": current_version},
    )


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def error_body(
    request: Request, code: str, message: str, details: Any | None = None
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": _request_id(request),
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            error_body(request, exc.code, exc.message, exc.details), status_code=exc.status_code
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return JSONResponse(
            error_body(
                request,
                "VALIDATION_ERROR",
                "Some fields are invalid. Correct them and retry.",
                details,
            ),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(error_body(request, code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(OperationalError)
    @app.exception_handler(InterfaceError)
    @app.exception_handler(OSError)
    async def _db_unavailable(request: Request, exc: Exception) -> JSONResponse:
        log.warning(
            "persistence unavailable request_id=%s: %s", _request_id(request), type(exc).__name__
        )
        return JSONResponse(
            error_body(
                request,
                "PERSISTENCE_UNAVAILABLE",
                "The database is unavailable. Live "
                "quotes may continue, but changes cannot be saved. Retry shortly.",
            ),
            status_code=503,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error request_id=%s", _request_id(request))
        return JSONResponse(
            error_body(
                request,
                "INTERNAL_ERROR",
                "Unexpected server error. Retry, and check System Status if it persists.",
            ),
            status_code=500,
        )
