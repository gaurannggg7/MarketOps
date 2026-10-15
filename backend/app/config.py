"""Runtime configuration, read from environment variables (see `.env.example`)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MARKETOPS_", env_file=(".env", "../.env"), extra="ignore"
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://marketops:marketops@localhost:55432/marketops"

    # Origins allowed for cookie-authenticated writes and WebSocket handshakes.
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    # Secure cookies are required outside explicit local HTTP development (see ADR 0003).
    cookie_secure: bool = False
    session_cookie_name: str = "marketops_session"
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    login_max_failures: int = 5
    login_window_seconds: int = 300

    # Simulator / streaming
    simulator_enabled: bool = True
    simulator_seed: int = 20261013
    simulator_updates_per_second: int = 50
    batch_interval_ms: int = 100
    heartbeat_interval_ms: int = 1000
    client_queue_max: int = 256
    sample_interval_seconds: float = 1.0
    evaluator_interval_seconds: float = 1.0
    warmup_seconds: float = 15.0
    default_stale_seconds: int = 10
    quote_retention_hours: int = 24
    max_scenario_seconds: int = 900
    default_scenario_seconds: int = 300

    # Public portfolio demo (off by default). When enabled, POST /auth/demo issues a read-only
    # session for the viewer account without a password; every write from it is rejected.
    public_demo_enabled: bool = False
    public_demo_viewer_email: str = "viewer@marketops.local"
    public_demo_session_hours: int = 2
    demo_login_max_per_window: int = 30
    demo_login_window_seconds: int = 600
    # Automated operator that periodically runs a scenario and walks the resulting incident
    # through acknowledge → comment → resolve, so read-only visitors can watch the workflow.
    demo_autopilot_enabled: bool = False
    demo_autopilot_interval_seconds: int = 300
    demo_autopilot_email: str = "autopilot@marketops.local"
    api_docs_enabled: bool = True
    # Split-origin hosting (frontend on another site, e.g. Vercel → Render): the browser cannot
    # send the session cookie to the stream host, so it authenticates the socket with a
    # single-use, short-lived ticket sent as the first WebSocket message (never in the URL).
    # Run Alembic migrations and the idempotent seed inside the app process at startup (one
    # Python import instead of three; matters on tiny CPUs such as Render Free's 0.1 vCPU).
    startup_bootstrap: bool = False
    stream_ticket_auth_enabled: bool = False
    stream_ticket_ttl_seconds: int = 30
    max_stream_connections: int = 200
    max_stream_connections_per_session: int = 4

    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def _driver(cls, v: str) -> str:
        return normalize_database_url(v)


def normalize_database_url(url: str) -> str:
    """Accept provider URLs (postgres://, postgresql://) and select the psycopg 3 driver."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
