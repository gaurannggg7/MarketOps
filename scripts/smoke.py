"""Release smoke checks against a running MarketOps origin.

Checks: readiness, login, catalog, WebSocket upgrade + snapshot, live quote update, watchlist
persistence, and one incident transition (stale scenario → incident → acknowledge → stop).

    MARKETOPS_URL=http://localhost:8080 backend/.venv/bin/python scripts/smoke.py

Credentials come from DEMO_OPERATOR_PASSWORD (environment or the repo .env). The incident check
starts a short scenario on the last catalog instrument; it is meant for demo/staging stacks only.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
import websockets
from dotenv import dotenv_values

BASE = os.environ.get("MARKETOPS_URL", "http://localhost:8080").rstrip("/")
ROOT = Path(__file__).resolve().parent.parent
results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{': ' + detail if detail else ''}", flush=True)


def password() -> str:
    pw = os.environ.get("DEMO_OPERATOR_PASSWORD") or dotenv_values(ROOT / ".env").get(
        "DEMO_OPERATOR_PASSWORD"
    )
    if not pw:
        sys.exit("DEMO_OPERATOR_PASSWORD is not set (environment or .env)")
    return pw


async def main() -> int:
    origin = BASE
    async with httpx.AsyncClient(base_url=BASE, headers={"Origin": origin}, timeout=10) as c:
        r = await c.get("/api/v1/health/ready")
        record("readiness", r.status_code == 200, r.text[:120])

        r = await c.post(
            "/api/v1/auth/login",
            json={"email": "operator@marketops.local", "password": password()},
        )
        record("login", r.status_code == 200, f"HTTP {r.status_code}")
        if r.status_code != 200:
            return 1
        c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        cookie = c.cookies.get("marketops_session")

        r = await c.get("/api/v1/instruments", params={"limit": 1000})
        items = r.json().get("items", []) if r.status_code == 200 else []
        record("catalog", len(items) > 0, f"{len(items)} instruments")
        if not items:
            return 1

        ws_url = BASE.replace("http", "ws", 1) + "/ws/market"
        try:
            async with websockets.connect(
                ws_url, origin=origin, additional_headers={"Cookie": f"marketops_session={cookie}"}
            ) as ws:
                snap = json.loads(await asyncio.wait_for(ws.recv(), 5))
                record("websocket upgrade + snapshot", snap.get("type") == "snapshot",
                       f"epoch {snap.get('epoch')} seq {snap.get('seq')}")
                deadline = time.monotonic() + 5
                got_delta = False
                while time.monotonic() < deadline and not got_delta:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    got_delta = msg.get("type") == "delta" and msg.get("seq") == snap["seq"] + 1
                record("quote update (consecutive delta)", got_delta)
        except Exception as exc:  # report and continue with remaining checks
            record("websocket upgrade + snapshot", False, type(exc).__name__)

        target = items[-1]
        name = f"smoke-{int(time.time())}"
        wl = (await c.post("/api/v1/watchlists", json={"name": name})).json()
        await c.post(f"/api/v1/watchlists/{wl['id']}/items/{target['id']}")
        lists = (await c.get("/api/v1/watchlists")).json()
        persisted = any(w["id"] == wl["id"] and target["id"] in w["instrument_ids"] for w in lists)
        record("watchlist persistence", persisted)
        await c.delete(f"/api/v1/watchlists/{wl['id']}")

        r = await c.post("/api/v1/demo/scenarios", json={
            "kind": "STALE_QUOTES", "instrument_id": target["id"], "duration_seconds": 60})
        scenario_id = r.json().get("scenario", {}).get("id") if r.status_code == 201 else None
        incident = None
        deadline = time.monotonic() + 40
        while scenario_id and time.monotonic() < deadline and incident is None:
            await asyncio.sleep(1)
            page = (await c.get("/api/v1/incidents", params={
                "instrument_id": target["id"], "status": ["OPEN"]})).json()
            incident = page["items"][0] if page.get("items") else None
        if incident:
            r = await c.post(f"/api/v1/incidents/{incident['id']}/acknowledge",
                             json={"version": incident["version"]})
            record("incident transition (OPEN → ACKNOWLEDGED)", r.status_code == 200,
                   f"#{incident['number']} {target['symbol']}")
        else:
            record("incident transition (OPEN → ACKNOWLEDGED)", False, "no incident opened")
        if scenario_id:
            await c.delete(f"/api/v1/demo/scenarios/{scenario_id}")
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} smoke checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
