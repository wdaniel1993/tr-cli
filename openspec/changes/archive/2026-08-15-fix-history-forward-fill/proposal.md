## Why

The history backfill curve showed ARTIFICIAL DROPS (verified: 15 days with >2% sudden drops, worst -15.8%, each fully recovering the next day — textbook missing-bar symptom). Root cause: per-position `tradeAggregateHistory` daily series have differing date ranges and gaps (thin trading / different market calendars), and the per-day sum silently dropped positions lacking a bar that day, collapsing the total.

**Status: already implemented and committed as `0b7be21` (v0.2.2). This change documents the fix retroactively per the openspec workflow and archives it.**

## What Changes

- Per-position `{date: close}` maps are **forward-filled** across the series range (last known close carried forward; nothing filled before a position's first bar).
- Series **start = max(first bar date) across positions** so every day covers ALL positions (coverage 8/8) — no artificial drops from missing bars.
- JSON contract gains a `coverage` object `{positions, forward_filled, start_rule}` (additive; existing keys unchanged); the `note` documents the rule.
- Regression tests: synthetic middle gap must not drop the total; series must start at the max first-bar date.
- Version 0.2.1 → 0.2.2.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `history`: the series-building requirement changes — forward-fill instead of naive per-day exclusion; start = max first bar date; gap-free curve; coverage documented.

## Impact

- `src/tr_cli/client.py` (`history()` series building + note), `src/tr_cli/cli.py` (`coverage` in JSON), `src/tr_cli/mock.py` (`_history_bars` middle-gap support), `tests/test_history.py` (regression tests), README, wire-notes, version 0.2.2.
