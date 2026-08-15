## Context

v0.2.3's history backfill approximates (current quantities applied retroactively, constant cash) from per-position `tradeAggregateHistory` closes. Live-verified facts (2026-08-15): the official portfolio-chart REST endpoint returns REAL historical positions-only values — range=1y → 258 daily points (2025-08-15..2026-08-14, last = 183012.72 == app total, +51.66 vs our snapshot sum); range=max → 115 coarser points (2024-05-27..2026-08-14, first netValue 0.00); ranges 3y/6m → HTTP 400 (broken). The timeline REST feed (30/page, 335 events to 2024-05-29) enables historical cash reconstruction.

## Goals / Non-Goals

**Goals:**
- Primary source = portfolio-chart REST (1y daily + max coarser), merged (daily wins), leading zeros dropped, snapshot override.
- Historical cash reconstruction from REST timeline transactions with strict cash-moving classification + reconciliation invariant.
- `approximate: false`; granularity + cash notes; contract unchanged; version 0.3.0.
- No real account identifiers in repo/output.

**Non-Goals:**
- Fixing the server-side 3y/6m chart bug.
- tradeAggregateHistory changes (still used for per-position YTD).
- Eve's collector/snapshot persistence (CLI only merges optional snapshots).

## Decisions

### D1: portfolio-chart REST as primary source
`GET /api-gateway/portfolio-chart/v2/chart?secAccNo=..&range=1y&currency=EUR` and `range=max`. Merge: build date→point dict inserting max first, then 1y (daily wins), then optional snapshots (highest priority). Drop leading zero-netValue points. Dates = UTC ms → YYYY-MM-DD. `approximate: false`.
- Alternative rejected: keep the aggregates-based backfill — it is approximate (retroactive quantities) and now unnecessary.

### D2: cash reconstruction
Events: REST `/api/v2/timeline/transactions?limit=100` + `olderThan=<cursors.after>` until exhausted (cap 50 pages). Cash-moving set = the verified signed-amount types; SAVINGS_PLAN_INVOICE_CREATED and other informational types excluded (double-count risk). With S = Σ amounts, P(d) = Σ amounts with date < d: cash(d) = current_cash − S + P(d). Invariant: cash(first event date) ≈ 0 (tolerance ~2 EUR); negative cash mid-series flagged in note, not fatal. current_cash from the WS `cash` topic (1 connection).
- current_cash − S ≈ 0 requires all real movements captured — the invariant test validates the classification against real data before shipping (and is a mock test too).

### D3: flags & granularity
`--since YYYY-MM-DD` filters the start, `--days N` limits the window (default: full curve), `--snapshots <file>` overrides dates from a local snapshots JSON (Eve's collector). Note: "daily since <date>, coarser before; cash reconstructed from N events; snapshots merged: M".

## Risks / Trade-offs

- [Event classification gaps → invariant fails] → Invariant test gates shipping; classification set documented and adjustable.
- [Chart coarser range precision] → Note states granularity; daily data exists only since the 1y range.
- [HTTP 400 on 3y/6m] → Only 1y/max used, documented.
- [Privacy] → secAccNo/cashAccountNumber never printed/committed; mock synthetic.

## Migration Plan

transport params → client history rewrite (chart fetch, merge, cash walk, snapshots) → mock fixtures → tests (invariant, merge, pagination, cash walk, granularity) → version 0.3.0 + docs → live verification (1 WS cash + HTTP chart/timeline, spaced; invariant check on real data) → archive + sync + push.
