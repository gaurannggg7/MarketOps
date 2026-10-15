"""In-process quote state and ordered snapshot/delta broadcast (single worker, ADR 0002).

Protocol summary (see docs/architecture.md):
- Every delta batch carries the stream ``epoch`` and a globally consecutive ``seq``.
- Heartbeats repeat the current ``seq`` watermark but never advance it.
- Registration and snapshot capture happen under the same lock as delta publication, so a new
  connection receives exactly the batches with ``seq`` greater than its snapshot watermark.
- Each connection has a bounded queue. Overflow drops the backlog and sends a ``resync``
  control message, after which the socket is closed; the client reconnects for a new snapshot.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.services.market_math import fmt, mid_price, spread_bps

# Application-defined WebSocket close codes (4000-4999 range).
CLOSE_RESYNC = 4000
CLOSE_SCENARIO_DISCONNECT = 4001
CLOSE_LOGGED_OUT = 4002
CLOSE_TRY_AGAIN_LATER = 1013
CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN_ORIGIN = 4403


@dataclass
class Quote:
    instrument_id: uuid.UUID
    symbol: str
    bid: Decimal
    ask: Decimal
    volume: int
    source_time: datetime
    received_time: datetime
    needs_sample: bool = True

    def wire(self) -> dict[str, Any]:
        return {
            "id": str(self.instrument_id),
            "symbol": self.symbol,
            "bid": fmt(self.bid),
            "ask": fmt(self.ask),
            "mid": fmt(mid_price(self.bid, self.ask)),
            "spread_bps": fmt(spread_bps(self.bid, self.ask)),
            "volume": self.volume,
            "source_time": self.source_time.isoformat(),
            "received_time": self.received_time.isoformat(),
        }


@dataclass(frozen=True)
class Control:
    """Out-of-band instruction for a single connection: send ``message`` then close."""

    message: str
    close_code: int


@dataclass
class Connection:
    id: uuid.UUID
    user_id: uuid.UUID
    session_id: uuid.UUID
    queue: asyncio.Queue[tuple[int | None, str] | Control]
    closing: bool = False
    sent_batches: int = 0


@dataclass
class HubStats:
    deltas_published: int = 0
    quotes_published: int = 0
    overflow_disconnects: int = 0
    recent_quote_counts: deque[tuple[float, int]] = field(default_factory=lambda: deque(maxlen=200))


def new_epoch() -> str:
    return f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(3)}"


class StreamHub:
    def __init__(
        self, queue_max: int, max_connections: int = 200, max_per_session: int = 4
    ) -> None:
        self.queue_max = queue_max
        self.max_connections = max_connections
        self.max_per_session = max_per_session
        self.epoch = new_epoch()
        self.seq = 0
        self.quotes: dict[uuid.UUID, Quote] = {}
        self._pending: dict[uuid.UUID, Quote] = {}
        self._connections: dict[uuid.UUID, Connection] = {}
        self._lock = asyncio.Lock()
        self.stats = HubStats()
        self.stale_ids: frozenset[uuid.UUID] = frozenset()

    # ---- ingest -------------------------------------------------------------------------
    def ingest(self, quotes: list[Quote]) -> None:
        """Apply producer updates to authoritative state; they are published on next flush."""
        for q in quotes:
            self.quotes[q.instrument_id] = q
            self._pending[q.instrument_id] = q

    async def flush(self, now: datetime, loop_time: float) -> int | None:
        """Publish coalesced pending updates as one delta batch. Returns the new seq or None."""
        async with self._lock:
            if not self._pending:
                return None
            batch = list(self._pending.values())
            self._pending.clear()
            self.seq += 1
            payload = json.dumps(
                {
                    "type": "delta",
                    "epoch": self.epoch,
                    "seq": self.seq,
                    "ts": now.isoformat(),
                    "quotes": [q.wire() for q in batch],
                },
                separators=(",", ":"),
            )
            self.stats.deltas_published += 1
            self.stats.quotes_published += len(batch)
            self.stats.recent_quote_counts.append((loop_time, len(batch)))
            for conn in list(self._connections.values()):
                self._enqueue(conn, (self.seq, payload))
            return self.seq

    async def heartbeat(self, now: datetime) -> None:
        async with self._lock:
            payload = json.dumps(
                {
                    "type": "heartbeat",
                    "epoch": self.epoch,
                    "seq": self.seq,
                    "server_time": now.isoformat(),
                    "stale_ids": sorted(str(i) for i in self.stale_ids),
                },
                separators=(",", ":"),
            )
            for conn in list(self._connections.values()):
                self._enqueue(conn, (None, payload))

    def observed_quotes_per_second(self, loop_time: float, window: float = 10.0) -> float:
        total = sum(n for t, n in self.stats.recent_quote_counts if loop_time - t <= window)
        return round(total / window, 1)

    # ---- connections --------------------------------------------------------------------
    def snapshot_payload(self, now: datetime) -> tuple[str, int]:
        payload = json.dumps(
            {
                "type": "snapshot",
                "epoch": self.epoch,
                "seq": self.seq,
                "server_time": now.isoformat(),
                "stale_ids": sorted(str(i) for i in self.stale_ids),
                "quotes": [q.wire() for q in self.quotes.values()],
            },
            separators=(",", ":"),
        )
        return payload, self.seq

    def admission_error(self, session_id: uuid.UUID) -> str | None:
        """Bounded fan-out: refuse new sockets beyond global and per-session caps."""
        if len(self._connections) >= self.max_connections:
            return "server_busy"
        same = sum(1 for c in self._connections.values() if c.session_id == session_id)
        if same >= self.max_per_session:
            return "too_many_session_connections"
        return None

    async def register(
        self, user_id: uuid.UUID, session_id: uuid.UUID, now: datetime
    ) -> tuple[Connection, str, int]:
        """Atomically register a queue and capture the snapshot watermark."""
        async with self._lock:
            conn = Connection(
                id=uuid.uuid4(),
                user_id=user_id,
                session_id=session_id,
                queue=asyncio.Queue(maxsize=self.queue_max),
            )
            self._connections[conn.id] = conn
            payload, seq = self.snapshot_payload(now)
            return conn, payload, seq

    def unregister(self, conn: Connection) -> None:
        self._connections.pop(conn.id, None)

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def _enqueue(self, conn: Connection, item: tuple[int | None, str]) -> None:
        if conn.closing:
            return
        try:
            conn.queue.put_nowait(item)
        except asyncio.QueueFull:
            self.stats.overflow_disconnects += 1
            self._close(conn, "queue_overflow", CLOSE_RESYNC)

    def _close(self, conn: Connection, reason: str, code: int) -> None:
        """Drop the backlog and leave a single control message for the sender loop."""
        conn.closing = True
        while not conn.queue.empty():
            conn.queue.get_nowait()
        msg = json.dumps({"type": "resync", "reason": reason, "epoch": self.epoch})
        conn.queue.put_nowait(Control(msg, code))

    def disconnect_user(self, user_id: uuid.UUID, reason: str, code: int) -> int:
        conns = [c for c in self._connections.values() if c.user_id == user_id and not c.closing]
        for c in conns:
            self._close(c, reason, code)
        return len(conns)

    def disconnect_session(self, session_id: uuid.UUID) -> None:
        for c in [c for c in self._connections.values() if c.session_id == session_id]:
            self._close(c, "logged_out", CLOSE_LOGGED_OUT)

    async def start_new_epoch(self) -> str:
        """Reset sequencing (e.g. demo reset). Clients detect the epoch change and resync."""
        async with self._lock:
            self.epoch = new_epoch()
            self.seq = 0
            self._pending.clear()
            return self.epoch

    async def close_all(self, reason: str) -> None:
        async with self._lock:
            for c in list(self._connections.values()):
                self._close(c, reason, CLOSE_RESYNC)
