## Why

Daniel's daily-watcher chart has a single snapshot; it should show a real value curve immediately. The `tradeAggregateHistory` WebSocket topic (verified live 2026-08-15 by Eve: full daily-bar series `{aggregates:[{time(ms), open, high, low, close, volume}], expectedClosingTime, resolution, lastAggregateEndTime, unit, sourceCurrency}`, 159 bars YTD for IE00B4L5Y983, first open == YTD base, last close == current price) lets tr-cli backfill a historic portfolio value curve from current holdings alone — no prior snapshots needed.

## What Changes

- New `tr-cli history` command: fetches positions (quantities, exchangeIds, names) + current cash, then ONE `tradeAggregateHistory` daily-bar batch (resolution 86400000, `from` = now − N days, `until` = now) for all positions over a **single WS connection** (sequential subscribe rounds: portfolio+cash → instrument → series), and builds a daily series:
  - per date (UTC ms → YYYY-MM-DD), `total` = Σ over positions of (qty × close) for dates where the position HAS a bar (missing bar → position excluded that day), + current cash (constant; documented approximation).
  - Flags: `--days N` (default 365, max 730).
  - JSON contract for Eve's cron: `{ok, start_date, end_date, days, approximate: true, note, series: [{date, total, cash|null}]}`.
  - Human output: compact date/total/Δ-vs-prev table.
- `approximate: true` documented: current quantities applied retroactively (positions bought mid-period appear for their whole price history), cash held constant at today's value.
- Mock fixtures + tests (series math, missing-bar exclusion, date conversion, empty portfolio). Version bump 0.2.0 → 0.2.1.

## Capabilities

### New Capabilities
- `history`: historic portfolio value backfill from current holdings + daily price series.

### Modified Capabilities
- None (additive).

## Impact

- `src/tr_cli/`: `ws.py` (one-connection sequential-rounds helper `rounds`), `client.py` (`history()` reusing position/cash/instrument helpers), `cli.py` (`history` command), `render.py` (compact table), `mock.py` (multi-position series fixtures), `protocol.py` (history constants).
- `tests/`: new history tests; all existing 58 stay green.
- Version 0.2.1; README + wire-notes updated.
