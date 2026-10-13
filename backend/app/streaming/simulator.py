"""Deterministic synthetic quote producer. Never contacts external market services.

Each tick updates the next slice of a seeded shuffled cycle of instruments, so at the default
200 instruments / 50 updates per second every instrument updates about once every four seconds
(and never waits more than two cycles) unless a scenario pauses it.
"""

from __future__ import annotations

import math
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.services.market_math import quantize_price
from app.streaming.hub import Quote

WIDE_SPREAD_TARGET_BPS = 150.0


@dataclass
class InstrumentSpec:
    instrument_id: uuid.UUID
    symbol: str
    base_price: Decimal


@dataclass
class _SimState:
    spec: InstrumentSpec
    mid: float
    spread_bps: float
    volume: int


class Simulator:
    def __init__(
        self, specs: list[InstrumentSpec], seed: int, updates_per_second: int, tick_seconds: float
    ) -> None:
        self.seed = seed
        self.updates_per_second = updates_per_second
        self.tick_seconds = tick_seconds
        self._specs = specs
        self.paused: set[uuid.UUID] = set()
        self.widened: set[uuid.UUID] = set()
        self.reset()

    def reset(self) -> None:
        self._rng = random.Random(self.seed)
        self._states = {
            s.instrument_id: _SimState(
                spec=s,
                mid=float(s.base_price),
                spread_bps=self._rng.uniform(2.0, 12.0),
                volume=self._rng.randint(10_000, 500_000),
            )
            for s in self._specs
        }
        self._cycle: list[uuid.UUID] = []
        self._carry = 0.0
        self.ticks = 0

    @property
    def instrument_count(self) -> int:
        return len(self._states)

    def _quote(self, st: _SimState, now: datetime) -> Quote:
        spread = WIDE_SPREAD_TARGET_BPS if st.spec.instrument_id in self.widened else st.spread_bps
        half = st.mid * spread / 20_000
        bid = quantize_price(Decimal(repr(max(st.mid - half, 0.01))))
        ask = quantize_price(Decimal(repr(st.mid + half)))
        if ask < bid:  # pragma: no cover - quantization guard
            ask = bid
        latency_ms = self._rng.uniform(2.0, 40.0)
        return Quote(
            instrument_id=st.spec.instrument_id,
            symbol=st.spec.symbol,
            bid=bid,
            ask=ask,
            volume=st.volume,
            source_time=now - timedelta(milliseconds=latency_ms),
            received_time=now,
        )

    def initial_quotes(self, now: datetime) -> list[Quote]:
        return [self._quote(st, now) for st in self._states.values()]

    def _next_ids(self, count: int) -> list[uuid.UUID]:
        out: list[uuid.UUID] = []
        while len(out) < count and self._states:
            if not self._cycle:
                self._cycle = list(self._states)
                self._rng.shuffle(self._cycle)
            out.append(self._cycle.pop())
        return out

    def step(self, now: datetime) -> list[Quote]:
        """Advance one tick and return the quotes produced (paused instruments emit nothing)."""
        self.ticks += 1
        self._carry += self.updates_per_second * self.tick_seconds
        count = int(self._carry)
        self._carry -= count
        quotes: list[Quote] = []
        for iid in self._next_ids(count):
            st = self._states[iid]
            st.mid = max(0.05, st.mid * math.exp(self._rng.gauss(0.0, 0.0008)))
            st.spread_bps = min(20.0, max(1.0, st.spread_bps * math.exp(self._rng.gauss(0, 0.05))))
            st.volume += self._rng.randint(1, 50) * 100
            if iid in self.paused:
                continue
            quotes.append(self._quote(st, now))
        return quotes

    def force_quote(self, instrument_id: uuid.UUID, now: datetime) -> Quote | None:
        """Emit an immediate quote for one instrument (used when a scenario starts or ends)."""
        st = self._states.get(instrument_id)
        if st is None or instrument_id in self.paused:
            return None
        return self._quote(st, now)
