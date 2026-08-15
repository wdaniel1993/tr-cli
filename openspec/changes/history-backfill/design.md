## Context

v0.2.0 ships timeline + YTD. Daniel's chart needs a real value curve; today he has 1 snapshot. The `tradeAggregateHistory` topic returns a full daily-bar series (Eve verified live 2026-08-15: `{aggregates:[{time(ms), open, high, low, close, volume}], expectedClosingTime, resolution, lastAggregateEndTime, unit, sourceCurrency}` — 159 bars YTD for IE00B4L5Y983 @ LSX; first open 111.115 == the YTD base used by v0.2.0; last close == current price). So a historic curve can be backfilled from CURRENT holdings + per-position price series — no prior snapshots needed.

## Goals / Non-Goals

**Goals:**
- `tr-cli history [--days N]` (default 365, max 730) — daily portfolio value curve.
- Series math: per date, Σ (qty × close) over positions with a bar + constant current cash; missing bar → position excluded that day; failed series → position excluded everywhere.
- Exact JSON contract for Eve's cron; compact human table; mock parity; version 0.2.1.

**Non-Goals:**
- Position-level historic quantities (the API has no per-position historical sizes without the local snapshot store — see wire-notes; we document `approximate: true`).
- Intraday resolution, dividend/flow adjustment, currency conversion (TR converts to EUR; qty×close is in trading currency like totalValue today).
- Persisting snapshots (Eve's watcher does that going forward).

## Decisions

### D1: Single-connection sequential rounds for `history`
Instead of calling `portfolio()` (4 WS connections: compact+cash, instrument, ticker, ytd), `history()` uses a new `ws.rounds()` helper — ONE connection with sequential subscribe rounds: round 1 `compactPortfolioByType`+`cash`, round 2 `instrument` per position (names + exchangeIds), round 3 `tradeAggregateHistory` per position. This satisfies the mission's 1-2 WS constraint and the dependency chain (exchangeIds needed before series). Position normalization/parsing helpers are reused from `client.py`.
- **Alternative considered**: reuse `portfolio()` wholesale (mission's literal wording) — rejected: 4 connections for what is a read-only backfill; rate-limit discipline.

### D2: Missing-bar policy
Positions trade on different exchanges (US ETFs vs EU ETFs) with different holidays → bar sets differ. For each date in the union of bar dates: `total = Σ qty×close` over positions with a bar that date + cash. No interpolation (a missing bar means the market was closed for that instrument). A position whose series subscription errors/times out is excluded from the whole series (surfaced in the note). This is the mission-specified policy.

### D3: Cash approximation + `approximate: true`
Current cash (single EUR balance) is added as a constant to every day; the note and `approximate: true` state: "current quantities applied retroactively; cash constant". Positions bought mid-window appear across their whole price history (instrument-level series, not position-level) — documented approximation; the local snapshot store (Eve's watcher) will make future curves exact.

### D4: Series derivation details
- `bar.time` (UTC ms) → `YYYY-MM-DD` (UTC).
- Last point's total ≈ today's snapshot `totalValue` + cash (totalValue is positions-only; history total is the account value curve incl. cash — semantics documented in README).
- `days` = number of series points; `start_date`/`end_date` = first/last point dates (None for empty portfolio).
- Empty portfolio → `series: []`, still `ok: true`.

## Risks / Trade-offs

- [Server caps daily bars for long windows (730d)] → Response includes `lastAggregateEndTime`/`resolution`; if bars < expected the command still returns what exists and the note reports coverage. Verified live at 365d during verification.
- [Position series fetch failure] → Position excluded, note updated; command succeeds (never fail the whole curve for one ISIN).
- [Curve is an approximation (current qty, constant cash)] → Explicit in JSON contract + human output + README.
- [Rate limits] → history = 1 WS connection + 1 HTTP; verification = single spaced invocation.

## Migration Plan

1. `ws.py` rounds helper → 2. `client.history()` → 3. CLI + render → 4. mock fixtures (multi-position bars, missing-bar case) → 5. tests → 6. README + wire-notes → 7. version 0.2.1 → 8. one live verification (`tr-cli --json history --days 365`, single spaced WS) → 9. validate, sync specs, archive, commit + push.

## Open Questions

- None blocking. (Series shape + exchangeId rule verified live by Eve; window cap checked during verification.)
