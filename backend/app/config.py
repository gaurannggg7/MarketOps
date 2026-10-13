"""Runtime configuration, read from environment variables (see `.env.example`)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
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

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
