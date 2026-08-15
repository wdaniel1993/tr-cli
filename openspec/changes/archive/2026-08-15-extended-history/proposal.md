## Why

The history curve is currently backfilled from per-position `tradeAggregateHistory` closes with current quantities applied retroactively (an approximation) and a constant cash. Trade Republic's OWN portfolio-chart REST endpoint (`api-gateway/portfolio-chart/v2/chart`) returns the REAL historical portfolio value (verified live today: range=1y → 258 daily points 2025-08-15..2026-08-14, netValue positions-only, last point 183012.72 == the app total; range=max → 115 coarser points back to 2024-05-27). Historical cash can be reconstructed from the timeline transactions REST endpoint (verified: 335 events back to 2024-05-29). This makes the curve EXACT (real historical holdings) instead of approximate.

## What Changes

- **History source switch**: `history` uses the portfolio-chart REST endpoint (`range=1y` daily + `range=max` coarser) as PRIMARY; the tradeAggregateHistory-based per-position backfill is REPLACED (kept only for per-position YTD). Merge: daily 1y points win over coarser max points on overlap; the curve starts at the first NON-ZERO netValue point; optional local collector snapshots override everything. The "current quantities applied retroactively" approximation is GONE (`approximate: false`).
- **Cash history**: reconstruct historical cash from the REST timeline transactions feed (paginated via `olderThan` cursor): cash(date) = current_cash − Σ(signed amounts of cash-moving events with timestamp > date). Cash is constant between events, ~0 before the first event. Event classification excludes informational events (e.g. SAVINGS_PLAN_INVOICE_CREATED) to avoid double counting; a reconciliation invariant test (cash ≈ 0 at the first event date) guards the classification.
- Contract unchanged: `{ok, start_date, end_date, days, approximate, note, series:[{date, total, cash}]}` — total = positions (netValue), cash = reconstructed (no longer constant); note adds granularity info (daily since <date>, coarser before).
- Ranges 3y/6m are broken server-side (HTTP 400) — only 1y + max are used.
- Privacy: secAccNo and cashAccountNumber are REAL — never committed or printed; mock uses synthetic fixtures only.
- Version 0.3.0.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `history`: PRIMARY source changes from per-position aggregate closes to the official portfolio-chart REST endpoint; cash becomes reconstructed history (not constant); approximation removed.

## Impact

- `src/tr_cli/`: `client.py` (`history()` rewrite: REST chart fetch, merge, cash reconstruction, snapshot override), `transport.py` (`request()` gains query `params`), `mock.py` (portfolio-chart + timeline REST fixtures), `cli.py` (`--snapshots`), `render.py`.
- `tests/`: reconciliation invariant, merge order (daily>coarser>snapshot), pagination loop, cash walk, granularity note.
- Version 0.3.0; README + wire-notes updated.
