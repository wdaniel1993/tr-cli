## Context

v0.2.2's `history` curve is gap-free (forward-filled) but its per-day `total` adds the constant current cash (3552.53), while Daniel's snapshot `totalValue` (and the TR app) is positions only. Live probe: 8/8 last-bar sums = totalValue + 316 (quote drift), backfill 08-14 total = 186829.56 = 182961.06 + 316 + 3552.53 → a ~1.9% boundary step. This change makes `total` positions-only so the curve merges with snapshot totals.

## Goals / Non-Goals

**Goals:**
- `history` per-day `total` = Σ (qty × close), positions only.
- Per-point `cash` field kept (constant) for the chart's separate cash line; never added to total.
- Boundary gap vs `portfolio.totalValue` < 0.5% (quote drift only).
- Regression test; version 0.2.3.

**Non-Goals:**
- Changing the `portfolio` totalValue semantics (already positions-only, correct).
- Any timeline/ytd changes.

## Decisions

### D1: total = positions only; cash is a separate constant field
Remove the `cash_dec` addition from the per-day sum in `client.history()`. `HistoryPoint.cash` remains the constant current cash string (or None) — the chart layer can render a cash line from it without corrupting the value curve. The note becomes: "current quantities applied retroactively; cash reported separately (constant)".

### D2: Boundary verification
The last backfill point (positions only) is compared against `portfolio.totalValue` (positions only) — both exclude cash, so the only difference is quote timing (last bar close vs live ticker), observed at ~0.17% (316/182961) in the live probe.

## Risks / Trade-offs

- [Chart loses the combined positions+cash view] → The `cash` field is still per-point; Eve's chart can layer it. The curve now matches Daniel's app semantics exactly.
- [None other] — small, well-scoped change.

## Migration Plan

Implement → regression tests → version 0.2.3 → live verification (last point vs totalValue, boundary < 0.5%) → archive + sync spec → commit + push.
