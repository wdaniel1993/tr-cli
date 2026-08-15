# history Specification

## Purpose
Backfill a daily portfolio value curve from current holdings (positions + cash + per-position daily close series), with account-start auto-detection and per-position forward-filling so the curve is gap-free.
## Requirements
### Requirement: history command
The CLI SHALL provide a `history` command that backfills a daily portfolio value series from current holdings: quantities + current cash from the portfolio snapshot, and per-position daily close prices from the `tradeAggregateHistory` WebSocket topic (resolution 86400000, `from` = start, `until` = now) fetched in ONE batch over a single WS connection.

The CLI SHALL build the series by **forward-filling each position's close prices** across the series range: a position's last known close is carried forward over dates where it has no bar (thin trading / different market calendars), and nothing is filled before a position's first bar. The series SHALL start at the **latest first-bar date across positions** so every day in the series covers ALL positions (no artificial drops from missing bars). The JSON output SHALL include a `coverage` object (`{positions, forward_filled, start_rule}`) and the note SHALL document the forward-fill/start rule.

The per-day `total` SHALL be **positions only**: `total` = Σ (qty × close) over positions (forward-filled) — the current cash MUST NOT be added. The per-point `cash` field SHALL still be emitted (constant current cash, `null` when unavailable) for the chart's separate cash line, and the curve MUST merge with the portfolio snapshot `totalValue` (positions only) within quote drift (<0.5%).

#### Scenario: full history run
- **WHEN** the user runs `tr-cli history` with a valid session and held positions
- **THEN** the output contains one daily point per trading day in the range, each covering every position (forward-filled), with `total` = Σ (qty × close) (positions only, cash NOT added), `cash` = the constant current cash, and `coverage.forward_filled` is true

#### Scenario: cash is separate from total (regression)
- **WHEN** a series point is produced
- **THEN** `total` equals exactly the sum of qty×close over positions and the `cash` field is never added into `total` (regression test asserts total == Σ qty×close with cash as an independent field)

#### Scenario: boundary merges with snapshot
- **WHEN** the last backfill point is compared with the current portfolio `totalValue`
- **THEN** the difference is within quote drift (<0.5% of totalValue)

#### Scenario: window flags
- **WHEN** the user runs `tr-cli history --days 365`
- **THEN** the series covers the requested window (default 90, maximum 730, usage error above), subject to the server-side daily-bar cap (noted when truncated)

#### Scenario: gap-free curve (regression)
- **WHEN** a position lacks bars for a stretch of dates (middle gap)
- **THEN** the position's last close is carried forward across the gap and the daily total does NOT drop artificially

#### Scenario: start covers all positions
- **WHEN** positions have different first-bar dates
- **THEN** the series starts at the latest first-bar date and every day covers all positions, with the note stating `start = max first bar date`

### Requirement: missing-bar exclusion
The CLI SHALL exclude a position from the WHOLE series when its series fetch fails entirely (no bars at all), and SHALL never fill prices before a position's first bar.

#### Scenario: failed series fetch
- **WHEN** a position's `tradeAggregateHistory` subscription fails or times out
- **THEN** the position is omitted from every day's total (listed in the note) and the command still succeeds

### Requirement: JSON output contract
The CLI SHALL emit `--json` in the fixed shape `{ok, start_date, end_date, days, approximate: true, note, series: [{date, total, cash|null}]}` where `total` includes the constant current cash, `cash` is the current cash total (null when unavailable), and `approximate`/`note` document that current quantities are applied retroactively and cash is constant.

#### Scenario: contract shape
- **WHEN** the user runs `tr-cli --json history`
- **THEN** stdout is exactly one JSON document matching the contract

#### Scenario: empty portfolio
- **WHEN** the account has no positions
- **THEN** the command succeeds with an empty `series` (no bar dates exist to derive trading days)

### Requirement: human output
The CLI SHALL render a compact table (date, total, Δ vs previous day) for terminal use.

#### Scenario: compact table
- **WHEN** the user runs `tr-cli history` without `--json`
- **THEN** the output shows one row per date with total and day-over-day change

