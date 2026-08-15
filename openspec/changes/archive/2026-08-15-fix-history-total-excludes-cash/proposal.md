## Why

The history command's per-day `total` INCLUDES the current cash (constant 3552.53). Daniel's snapshot/`portfolio` `totalValue` is POSITIONS ONLY (matches the TR app exactly). Verified by a live probe (all 8 positions' last aggregate bars vs live prices sum to +316 EUR vs snapshot 182961.06; backfill 08-14 total = 186829.56 = 182961.06 + 316 + 3552.53). Because of the cash add-on, the backfill curve does NOT merge with snapshot totals — a visible ~1.9% step at the boundary.

## What Changes

- `history` per-day `total` = Σ (qty × close) over positions (forward-filled) — **positions only**, cash NOT added.
- The per-point `cash` field stays (constant current cash) for the chart's separate cash line, but is never added to `total`.
- Note wording updated: cash reported separately (constant), not included.
- Regression test: `total` == sum of qty×close, and `cash` is a separate field never added.
- Version 0.2.2 → 0.2.3.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `history`: the per-day total semantics change — positions only (cash excluded from total, reported separately).

## Impact

- `src/tr_cli/client.py` (`history()` total computation + docstring + note), README, wire-notes, `tests/test_history.py` (regression), version 0.2.3.
