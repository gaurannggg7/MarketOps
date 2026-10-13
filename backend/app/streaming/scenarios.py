"""Operator-triggered demo scenarios. They only alter the in-process synthetic simulator."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.streaming.simulator import Simulator


class ScenarioKind(enum.StrEnum):
    STALE_QUOTES = "STALE_QUOTES"
    WIDE_SPREAD = "WIDE_SPREAD"


DESCRIPTIONS = {
    ScenarioKind.STALE_QUOTES: (
        "Stops emitting quotes for one instrument. Heartbeats and all other instruments keep "
        "flowing, so the instrument goes stale while the connection stays healthy."
    ),
    ScenarioKind.WIDE_SPREAD: (
        "Widens one instrument's synthetic bid/ask spread to about 150 bps, above the default "
        "50 bps wide-spread rule."
    ),
}


@dataclass
class Scenario:
    id: uuid.UUID
    kind: ScenarioKind
    instrument_id: uuid.UUID
    symbol: str
    started_at: datetime
    expires_at: datetime
    started_by: uuid.UUID


class ScenarioConflictError(Exception):
    pass


class ScenarioManager:
    MAX_ACTIVE = 10

    def __init__(self, simulator: Simulator) -> None:
        self._sim = simulator
        self.active: dict[uuid.UUID, Scenario] = {}

    def start(
        self,
        kind: ScenarioKind,
        instrument_id: uuid.UUID,
        symbol: str,
        duration_s: int,
        user_id: uuid.UUID,
        now: datetime,
    ) -> Scenario:
        if any(s.kind == kind and s.instrument_id == instrument_id for s in self.active.values()):
            raise ScenarioConflictError(f"A {kind.value} scenario is already running for {symbol}.")
        if len(self.active) >= self.MAX_ACTIVE:
            raise ScenarioConflictError("Too many active scenarios; stop one first.")
        sc = Scenario(
            id=uuid.uuid4(),
            kind=kind,
            instrument_id=instrument_id,
            symbol=symbol,
            started_at=now,
            expires_at=now + timedelta(seconds=duration_s),
            started_by=user_id,
        )
        self.active[sc.id] = sc
        self._apply()
        return sc

    def stop(self, scenario_id: uuid.UUID) -> Scenario | None:
        sc = self.active.pop(scenario_id, None)
        self._apply()
        return sc

    def stop_for_instrument(self, instrument_id: uuid.UUID | None) -> list[Scenario]:
        stopped = [
            s
            for s in self.active.values()
            if instrument_id is None or s.instrument_id == instrument_id
        ]
        for s in stopped:
            self.active.pop(s.id, None)
        self._apply()
        return stopped

    def expire(self, now: datetime) -> list[Scenario]:
        expired = [s for s in self.active.values() if s.expires_at <= now]
        for s in expired:
            self.active.pop(s.id, None)
        if expired:
            self._apply()
        return expired

    def _apply(self) -> None:
        self._sim.paused = {
            s.instrument_id for s in self.active.values() if s.kind == ScenarioKind.STALE_QUOTES
        }
        self._sim.widened = {
            s.instrument_id for s in self.active.values() if s.kind == ScenarioKind.WIDE_SPREAD
        }
