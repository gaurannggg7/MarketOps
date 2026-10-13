# Low-fidelity layouts and primary workflow

Honesty note: these layouts were drafted during M0–M1 implementation in this same session (not
as a separate design phase with user research). They document the navigation and workflow that
the implemented screens follow; screenshots of the real screens are referenced in the README.

## Shell (all authenticated screens)

```text
┌────────────┬──────────────────────────────────────────────────────────────────────┐
│ MarketOps  │ [SYNTHETIC DATA] (● Stream live) (● All quotes fresh)   User  Role ⏻ │
│            ├──────────────────────────────────────────────────────────────────────┤
│ ▸ Monitor  │                                                                      │
│ ▸ Incidents│                      <screen content>                                │
│   (badge)  │                                                                      │
│ ▸ System   │                                                                      │
│            │                                                                      │
│ disclaimer │                                                                      │
└────────────┴──────────────────────────────────────────────────────────────────────┘
  ≤768px: the left nav collapses into a horizontal top bar; content stacks.
```
Transport state (stream pill) and quote freshness (stale count) are deliberately separate pills.

## Market monitor
```text
 Market monitor                    [Fresh 199] [Stale 1] [Active incidents 1] [Quotes/s 48.9]
 [Search____] [Show: All ▾] [☐ Stale only] [+ New watchlist]        [☆ adds to: Core ▾] [Open]
 ┌─☆─┬Symbol┬Name──────────┬Bid────┬Ask────┬Mid────┬Spread┬Volume┬Last┬Age─┬Fresh─┬Inc┐
 │ ★ │ BAMT │ Bamt Test…   │200.01 │200.18 │200.10 │ 8.24 │139k  │…   │1.5s│●Fresh│ 0 │
 │ ☆ │ BATL │ …            │       │       │       │      │      │    │    │■Stale│ 1 │
 └───┴──────┴──────────────┴───────┴───────┴───────┴──────┴──────┴────┴────┴──────┴───┘
```

## Instrument detail
```text
 Monitor / BAMT
 BAMT Bamt Test Pharma        [Bid][Ask][Mid][Spread bps][Volume]   (● Fresh) age 1.5s
 ┌ Price & spread history ─────────────────────────────── [5m|15m|1h] ┐
 │ caption: persisted samples, N-second buckets, not a tick archive   │
 │ Mid price (synthetic units)  — mid line + bid–ask band, tooltip    │
 │ Spread (bps) — line + dashed rule threshold                         │
 └─────────────────────────────────────────────────────────────────────┘
 ┌ Alert rules ───────────────┐ ┌ Incidents for BAMT ────────────────┐
 │ Stale: [10] s  ☑ [Save]     │ │ #1001 Stale quotes  OPEN  Active   │
 │ Spread: [50] bps ☑ [Save]   │ └─────────────────────────────────────┘
 └─────────────────────────────┘
 ┌ Historical events (Infinite Row Model, server blocks of 100) [type ▾] ┐
```

## Incident workspace
```text
 Incidents  [Status ▾][Severity ▾][Type ▾][Symbol__]            (table + pagination)
 Incident #1001 · Stale quotes · BAMT     [Status: OPEN][Severity: HIGH][Condition active]
 ┌ Summary / rule version / assignee ┐  ┌ Lifecycle: OPEN → ACKNOWLEDGED → RESOLVED ┐
 ├ Trigger evidence │ Latest evidence ┤  │ [Acknowledge]                              │
 ├ Timeline (audit + comments)       ┤  │ Assignment [operator ▾] [Save]             │
 └───────────────────────────────────┘  │ Comment [______] [Post]                    │
                                        │ Resolve: blocker text, note [___] [Resolve]│
```

## System status
```text
 Client stream: epoch, seq, snapshots, duplicates, gaps/epoch changes, last message, (pill)
 Server: epoch, seq, instruments, quotes/s, stale, incidents, connections, overflow
         [Synthetic feed][Rule evaluator][Database][Quote persistence]  (distinct health)
 Demo scenarios (operator): [kind ▾][instrument ▾][expires s][Run] + description
         Active scenarios with countdown + [Stop];  Reset demo feed… (typed confirmation)
```

## Primary workflow (3-minute demo)
1. Healthy feed: monitor shows all fresh, stream live.
2. Operator starts **Stale symbol** on one instrument (System status).
3. ≈10–11 s later the server evaluator opens an incident; the monitor shows the instrument stale
   while the stream stays live; the nav badge increments.
4. Operator opens the incident → evidence → instrument chart/events.
5. Acknowledge → comment → (resolve is blocked while the condition is active).
6. **Normal recovery** scenario → condition recovered (status unchanged).
7. Resolve with a note → timeline shows opened, acknowledged, comment, recovered, resolved.
