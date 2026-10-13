from __future__ import annotations

from typing import Any

from httpx import AsyncClient


async def instruments(client: AsyncClient) -> list[dict[str, Any]]:
    r = await client.get("/api/v1/instruments")
    assert r.status_code == 200
    items: list[dict[str, Any]] = r.json()["items"]
    return items


async def rule_for(client: AsyncClient, instrument_id: str, rule_type: str) -> dict[str, Any]:
    r = await client.get(
        "/api/v1/rules", params={"instrument_id": instrument_id, "rule_type": rule_type}
    )
    assert r.status_code == 200
    rules: list[dict[str, Any]] = [x for x in r.json() if x["enabled"]]
    assert len(rules) == 1
    return rules[0]


def error_code(response: Any) -> str:
    code: str = response.json()["error"]["code"]
    return code
