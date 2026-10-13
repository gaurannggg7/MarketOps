"""MarketOps workload benchmark. Measures; does not assert targets.

    scripts/bench_backend.sh &                 # isolated backend on :8002 (fresh DB + fixtures)
    backend/.venv/bin/python scripts/benchmark.py --duration 600 --clients 5

Definitions (see docs/performance.md):
- REST latency: wall time per request from this client over loopback, sequential per worker,
  `--rest-concurrency` workers. Percentiles use the nearest-rank method on all samples.
- Stream lag: client receive time − the delta's server `ts` (same host, same clock).
- Gaps: any delta whose seq is not previous+1 within one connection.
- Recovery: time from requesting the disconnect scenario until the replacement connection
  receives its snapshot (reconnect is immediate in this script; browser clients add backoff).
- RSS: resident set size of the backend PID sampled every 5 s via `ps`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parent.parent
PASSWORD = os.environ.get("DEMO_OPERATOR_PASSWORD") or os.environ.get("BENCH_PASSWORD")


def pct(samples: list[float], p: float) -> float | None:
    if not samples:
        return None
    s = sorted(samples)
    rank = max(1, math.ceil(p / 100 * len(s)))
    return round(s[rank - 1], 2)


def summary(samples: list[float]) -> dict[str, float | int | None]:
    return {
        "n": len(samples),
        "p50": pct(samples, 50),
        "p95": pct(samples, 95),
        "p99": pct(samples, 99),
        "max": round(max(samples), 2) if samples else None,
    }


async def login(base: str) -> tuple[httpx.AsyncClient, str]:
    c = httpx.AsyncClient(base_url=base, headers={"Origin": base}, timeout=30)
    r = await c.post(
        "/api/v1/auth/login",
        json={"email": "operator@marketops.local", "password": PASSWORD},
    )
    r.raise_for_status()
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return c, str(c.cookies.get("marketops_session"))


async def stream_client(base: str, cookie: str, stop: asyncio.Event, out: dict) -> None:
    url = base.replace("http", "ws", 1) + "/ws/market"
    lags: list[float] = []
    gaps = deltas = quotes = reconnects = 0
    while not stop.is_set():
        try:
            async with websockets.connect(
                url,
                origin=base,
                max_size=8_000_000,
                additional_headers={"Cookie": f"marketops_session={cookie}"},
            ) as ws:
                snap = json.loads(await ws.recv())
                last = snap["seq"]
                while not stop.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), 1.0)
                    except TimeoutError:
                        continue
                    now = time.time()
                    msg = json.loads(raw)
                    if msg["type"] == "delta":
                        if msg["seq"] != last + 1:
                            gaps += 1
                        last = msg["seq"]
                        deltas += 1
                        quotes += len(msg["quotes"])
                        lags.append(
                            (now - datetime.fromisoformat(msg["ts"]).timestamp()) * 1000
                        )
                    elif msg["type"] == "resync":
                        break
        except (websockets.ConnectionClosed, OSError):
            pass
        if not stop.is_set():
            reconnects += 1
            await asyncio.sleep(0.2)
    out.update(
        {
            "lag_ms": summary(lags),
            "gaps": gaps,
            "deltas": deltas,
            "quotes": quotes,
            "reconnects": reconnects,
        }
    )


async def rest_worker(
    c: httpx.AsyncClient,
    paths: list[tuple[str, str]],
    stop: asyncio.Event,
    samples: dict[str, list[float]],
    errors: dict[str, int],
) -> None:
    i = 0
    while not stop.is_set():
        label, path = paths[i % len(paths)]
        i += 1
        t0 = time.perf_counter()
        r = await c.get(path)
        elapsed = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            samples.setdefault(label, []).append(elapsed)
        else:
            errors[label] = errors.get(label, 0) + 1
        await asyncio.sleep(0.05)


def rss_mb(pid: int) -> float | None:
    try:
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=True,
        )
        return round(int(out.stdout.strip()) / 1024, 1)
    except (subprocess.CalledProcessError, ValueError):
        return None


def backend_pid(port: int) -> int | None:
    out = subprocess.run(
        ["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True
    )
    pids = [int(p) for p in out.stdout.split()]
    return pids[0] if pids else None


async def measure_recovery(base: str) -> float | None:
    c, cookie = await login(base)
    url = base.replace("http", "ws", 1) + "/ws/market"
    headers = {"Cookie": f"marketops_session={cookie}"}
    async with websockets.connect(
        url, origin=base, additional_headers=headers, max_size=8_000_000
    ) as ws:
        await ws.recv()
        t0 = time.perf_counter()
        await c.post("/api/v1/demo/scenarios", json={"kind": "DISCONNECT_STREAM"})
        try:
            while True:
                await ws.recv()
        except websockets.ConnectionClosed:
            pass
    async with websockets.connect(
        url, origin=base, additional_headers=headers, max_size=8_000_000
    ) as ws:
        snap = json.loads(await ws.recv())
        elapsed = (
            (time.perf_counter() - t0) * 1000 if snap["type"] == "snapshot" else None
        )
    await c.aclose()
    return round(elapsed, 1) if elapsed else None


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8002")
    ap.add_argument("--duration", type=int, default=600)
    ap.add_argument("--clients", type=int, default=5)
    ap.add_argument("--rest-concurrency", type=int, default=4)
    args = ap.parse_args()
    if not PASSWORD:
        raise SystemExit(
            "Set DEMO_OPERATOR_PASSWORD (the bench DB uses the .env demo passwords)."
        )
    base = args.url.rstrip("/")
    port = int(base.rsplit(":", 1)[1])
    pid = backend_pid(port)

    c, cookie = await login(base)
    insts = (await c.get("/api/v1/instruments", params={"limit": 1000})).json()["items"]
    iid = insts[len(insts) // 2]["id"]
    raw_paths = [
        "/api/v1/instruments?limit=1000",
        "/api/v1/market/snapshot",
        "/api/v1/events?offset=0&limit=100&sort=-observed_at",
        "/api/v1/events?offset=50000&limit=100&sort=-observed_at",
        "/api/v1/events?offset=0&limit=100&sort=symbol&event_type=SIM_PRICE_JUMP",
        f"/api/v1/instruments/{iid}/history?range=1h",
        "/api/v1/incidents?limit=25",
        "/api/v1/system/status",
    ]
    paths = [(p.replace(iid, "{id}"), p) for p in raw_paths]
    stop = asyncio.Event()
    stream_results: list[dict] = [{} for _ in range(args.clients)]
    rest_samples: dict[str, list[float]] = {}
    rest_errors: dict[str, int] = {}
    rss: list[tuple[float, float | None]] = []
    started = time.monotonic()
    started_at = datetime.now(UTC).isoformat()
    tasks = [
        asyncio.create_task(stream_client(base, cookie, stop, stream_results[i]))
        for i in range(args.clients)
    ]
    clients = [(await login(base))[0] for _ in range(args.rest_concurrency)]
    tasks += [
        asyncio.create_task(rest_worker(cl, paths, stop, rest_samples, rest_errors))
        for cl in clients
    ]
    while time.monotonic() - started < args.duration:
        if pid:
            rss.append((round(time.monotonic() - started, 1), rss_mb(pid)))
        await asyncio.sleep(5)
    stop.set()
    await asyncio.gather(*tasks)
    status = (await c.get("/api/v1/system/status")).json()
    recovery = [await measure_recovery(base) for _ in range(5)]
    for cl in clients:
        await cl.aclose()
    await c.aclose()

    rss_values = [v for _, v in rss if v is not None]
    warm = [v for t, v in rss if v is not None and t >= 60]
    result = {
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "machine": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
        },
        "workload": {
            "duration_s": args.duration,
            "stream_clients": args.clients,
            "rest_concurrency": args.rest_concurrency,
            "instruments": len(insts),
            "configured_updates_per_second": status["configured_updates_per_second"],
        },
        "server_observed_quotes_per_second_at_end": status[
            "observed_quotes_per_second"
        ],
        "stream": stream_results,
        "stream_client_quotes_per_second": [
            round(r["quotes"] / args.duration, 1) for r in stream_results
        ],
        "rest_ms": {k: summary(v) for k, v in sorted(rest_samples.items())},
        "rest_errors": rest_errors,
        "recovery_ms": recovery,
        "backend_rss_mb": {
            "first": rss_values[0] if rss_values else None,
            "after_60s_min": min(warm) if warm else None,
            "after_60s_max": max(warm) if warm else None,
            "last": rss_values[-1] if rss_values else None,
            "samples": rss,
        },
        "overflow_disconnects": status["overflow_disconnects"],
    }
    out_dir = ROOT / "benchmarks" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"bench-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(result, indent=2))
    printable = {k: v for k, v in result.items() if k != "backend_rss_mb"}
    printable["backend_rss_mb"] = {
        k: v for k, v in result["backend_rss_mb"].items() if k != "samples"
    }
    print(json.dumps(printable, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
