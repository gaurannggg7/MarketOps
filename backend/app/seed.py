"""Deterministic demo seed and fixture generation.

    python -m app.seed                      # idempotent demo seed (users, 200 instruments, rules)
    python -m app.seed --reset              # LOCAL ONLY: wipe business data first, then seed
    python -m app.seed --instruments 1000   # larger grid fixture
    python -m app.seed events --count 100000  # synthetic historical events for grid benchmarks
    python -m app.seed prune                # apply the quote-sample retention window now

Demo passwords come from DEMO_OPERATOR_PASSWORD / DEMO_OPERATOR2_PASSWORD / DEMO_VIEWER_PASSWORD.
When unset, new users get generated passwords printed once to stdout; existing users keep theirs.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import secrets
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.config import get_settings
from app.db import make_engine, make_sessionmaker
from app.models import (
    AlertRule,
    Instrument,
    MarketEvent,
    Role,
    RuleType,
    ThresholdUnit,
    User,
    Watchlist,
    WatchlistItem,
)
from app.runtime import prune_samples

SEED = 20261013
_ONSETS = ["B", "C", "D", "F", "G", "K", "L", "M", "N", "P", "R", "S", "T", "V", "Z", "QU", "TR"]
_VOWELS = ["A", "E", "I", "O", "U", "Y"]
_CODAS = ["X", "N", "R", "L", "S", "T", "M", "K"]
_SUFFIXES = [
    "Synthetic Holdings",
    "Simulated Industries",
    "Sample Systems",
    "Mock Energy",
    "Placeholder Bancorp",
    "Fictional Materials",
    "Demo Logistics",
    "Test Pharma",
]

DEMO_USERS = [
    ("operator@marketops.local", "Olivia Operator", Role.OPERATOR, "DEMO_OPERATOR_PASSWORD"),
    ("operator2@marketops.local", "Oscar Operator", Role.OPERATOR, "DEMO_OPERATOR2_PASSWORD"),
    ("viewer@marketops.local", "Vera Viewer", Role.VIEWER, "DEMO_VIEWER_PASSWORD"),
]
DEFAULT_STALE_SECONDS = Decimal(10)
DEFAULT_SPREAD_BPS = Decimal(50)

BUSINESS_TABLES = [
    "incident_comments",
    "audit_events",
    "market_events",
    "quote_samples",
    "watchlist_items",
    "watchlists",
    "sessions",
    "alert_episodes",
    "incidents",
    "alert_rules",
    "instruments",
    "users",
]


def instrument_catalog(count: int) -> list[tuple[str, str, str, Decimal]]:
    rng = random.Random(SEED)
    seen: set[str] = set()
    out: list[tuple[str, str, str, Decimal]] = []
    while len(out) < count:
        sym = (
            rng.choice(_ONSETS)
            + rng.choice(_VOWELS)
            + rng.choice(_CODAS)
            + rng.choice(_VOWELS[:5] + _CODAS)
        )[:5]
        if sym in seen or len(sym) < 3:
            continue
        seen.add(sym)
        label = "Synthetic ETF" if rng.random() < 0.15 else "Synthetic equity"
        name = f"{sym.title()} {rng.choice(_SUFFIXES)}"
        price = Decimal(str(round(rng.uniform(8, 450), 2)))
        out.append((sym, name, label, price))
    return sorted(out)


def demo_password(env_key: str) -> str | None:
    """Environment first, then the local gitignored .env files."""
    if os.environ.get(env_key):
        return os.environ[env_key]
    for candidate in (Path(".env"), Path(__file__).resolve().parents[2] / ".env"):
        if candidate.exists():
            value = dotenv_values(candidate).get(env_key)
            if value:
                return value
    return None


async def seed(db: AsyncSession, instruments: int, update_passwords: bool = True) -> list[str]:
    notes: list[str] = []
    now = datetime.now(UTC)
    users: dict[str, User] = {}
    for email, display, role, env_key in DEMO_USERS:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        password = demo_password(env_key)
        if user is None:
            if password is None:
                password = secrets.token_urlsafe(14)
                notes.append(f"Generated password for {email}: {password}")
            user = User(
                email=email,
                display_name=display,
                role=role,
                password_hash=hash_password(password),
                is_active=True,
            )
            db.add(user)
        elif password is not None and update_passwords:
            user.password_hash = hash_password(password)
        users[email] = user
    await db.flush()

    existing = {s for (s,) in (await db.execute(select(Instrument.symbol))).all()}
    for sym, name, label, price in instrument_catalog(instruments):
        if sym not in existing:
            db.add(Instrument(symbol=sym, name=name, asset_label=label, base_price=price))
    await db.flush()

    inst_rows = (await db.execute(select(Instrument).order_by(Instrument.symbol))).scalars().all()
    have_rules = {
        (iid, rt)
        for iid, rt in (
            await db.execute(select(AlertRule.instrument_id, AlertRule.rule_type))
        ).all()
    }
    operator = users["operator@marketops.local"]
    for inst in inst_rows:
        for rule_type, unit, threshold in (
            (RuleType.STALE, ThresholdUnit.SECONDS, DEFAULT_STALE_SECONDS),
            (RuleType.WIDE_SPREAD, ThresholdUnit.BPS, DEFAULT_SPREAD_BPS),
        ):
            if (inst.id, rule_type) not in have_rules:
                db.add(
                    AlertRule(
                        instrument_id=inst.id,
                        rule_type=rule_type,
                        unit=unit,
                        threshold=threshold,
                        enabled=True,
                        version=1,
                        created_by=operator.id,
                        created_at=now,
                        updated_at=now,
                    )
                )
    for email, user in users.items():
        has_list = (
            await db.execute(select(func.count()).where(Watchlist.owner_id == user.id))
        ).scalar_one()
        if has_list:
            continue
        wl = Watchlist(owner_id=user.id, name="Core", created_at=now, updated_at=now)
        db.add(wl)
        await db.flush()
        offset = 0 if email.startswith("operator@") else 5
        for inst in inst_rows[offset : offset + 6]:
            db.add(WatchlistItem(watchlist_id=wl.id, instrument_id=inst.id))
    await db.commit()
    notes.append(
        f"Seeded {len(DEMO_USERS)} users, {len(inst_rows)} instruments, default rules "
        f"(STALE {DEFAULT_STALE_SECONDS}s, WIDE_SPREAD {DEFAULT_SPREAD_BPS} bps)."
    )
    return notes


async def generate_events(db: AsyncSession, count: int) -> str:
    rng = random.Random(SEED + 1)
    ids = [i for (i,) in (await db.execute(select(Instrument.id))).all()]
    if not ids:
        return "No instruments; run the seed first."
    types = ["SIM_PRICE_JUMP", "SIM_VOLUME_SPIKE", "SIM_SPREAD_SAMPLE", "SIM_QUOTE_GAP"]
    end = datetime.now(UTC) - timedelta(minutes=1)
    batch: list[dict[str, object]] = []
    for n in range(count):
        batch.append(
            {
                "instrument_id": rng.choice(ids),
                "event_type": rng.choice(types),
                "observed_at": end - timedelta(seconds=rng.uniform(0, 7 * 24 * 3600)),
                "evidence": {"fixture": True, "n": n, "magnitude": round(rng.uniform(0.1, 9.9), 2)},
            }
        )
        if len(batch) == 5000:
            await db.execute(insert(MarketEvent), batch)
            batch.clear()
    if batch:
        await db.execute(insert(MarketEvent), batch)
    await db.commit()
    return f"Inserted {count} synthetic fixture events (types {', '.join(types)})."


async def reset_all(db: AsyncSession) -> None:
    await db.execute(text(f"TRUNCATE {', '.join(BUSINESS_TABLES)} RESTART IDENTITY CASCADE"))
    await db.execute(text("ALTER SEQUENCE incident_number_seq RESTART WITH 1001"))
    await db.commit()


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.seed")
    parser.add_argument("command", nargs="?", default="seed", choices=["seed", "events", "prune"])
    parser.add_argument("--reset", action="store_true", help="wipe business tables first (local)")
    parser.add_argument("--instruments", type=int, default=200)
    parser.add_argument("--count", type=int, default=100_000)
    args = parser.parse_args(argv)
    settings = get_settings()
    if args.reset and settings.environment == "production":
        print("Refusing --reset when MARKETOPS_ENVIRONMENT=production.", file=sys.stderr)
        return 2
    engine = make_engine(settings.database_url, null_pool=True)
    factory = make_sessionmaker(engine)
    try:
        async with factory() as db:
            if args.command == "events":
                print(await generate_events(db, args.count))
            elif args.command == "prune":
                n = await prune_samples(factory, datetime.now(UTC), settings.quote_retention_hours)
                print(f"Pruned {n} quote samples older than {settings.quote_retention_hours}h.")
            else:
                if args.reset:
                    await reset_all(db)
                    print("Wiped business tables.")
                for line in await seed(db, args.instruments):
                    print(line)
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
