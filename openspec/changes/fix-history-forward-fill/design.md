## Context

v0.2.1's `history` curve showed artificial drops (15 days >2%, worst -15.8%, full recovery next day). Diagnosis: per-position `tradeAggregateHistory` series have differing ranges/gaps (Health Care 32 bars/60d; Stoxx 600 last bar 08-13), and the naive per-day sum excluded positions without a bar that day. Fix implemented in commit `0b7be21` (v0.2.2); this document records the design retroactively.

## Goals / Non-Goals

**Goals:**
- Gap-free curve: every day covers ALL positions (no missing-bar exclusion within the series range).
- Forward-fill per position; start = max(first bar date); documented in note + JSON `coverage`.
- Regression tests; version 0.2.2.

**Non-Goals:**
- Chunked series fetches to beat the ~200-bar server cap (documented separately).
- Interpolating prices (forward-fill only — last known close).

## Decisions

### D1: Per-position forward-fill, start = max(first bar date)
For each position: walk the union of all bar dates (trading days) in order; carry the last known close forward across dates where the position has no bar; do NOT emit values before the position's first bar. The series starts at the latest first-bar date across positions, so every series day has a value for every position → no artificial drops. This replaced the naive `continue`-on-missing-bar sum (the bug).

### D2: Coverage contract
JSON adds `coverage: {positions, forward_filled: true, start_rule: "max(first bar date)"}` — additive, existing keys unchanged. The note states the rule (`start = max first bar date (...) -> every day covers N/N positions (forward-filled)`). Positions whose series fails entirely remain excluded everywhere (listed in the note).

### D3: Regression coverage
- `test_history_forward_fill_no_drop_regression`: middle gap in one position → min daily delta ≥ -0.01 and no cliff at the gap boundary.
- `test_history_start_is_max_first_bar`: series starts at the later first-bar date, both positions covered from day 1.
- Mock `_history_bars` gained `gap_indices` and prices by VISIBLE bar (gaps don't create price cliffs in fixtures).

## Risks / Trade-offs

- [Forward-fill hides real day-level price moves for thinly traded positions] → Better than fake drops; note documents it; last close is a real price.
- [Start truncation when series fetch is partial] → The max-first-bar rule is applied per fetched series; a wholly failed series is excluded and noted.

## Migration Plan

Implemented + verified live (0b7be21, v0.2.2): July 2026 drop cluster eliminated, coverage 8/8, last total 186,829.56 ≈ totalValue + cash. This change documents + archives it.
