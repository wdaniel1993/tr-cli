# history Specification

## Purpose
TBD - created by archiving change history-backfill. Update Purpose after archive.
## Requirements
### Requirement: history command
The CLI SHALL provide a `history` command that backfills a daily portfolio value series from current holdings: quantities + current cash from the portfolio snapshot, and per-position daily close prices from the `tradeAggregateHistory` WebSocket topic (resolution 86400000, `from` = now − N days, `until` = now) fetched in ONE batch over a single WS connection.

#### Scenario: full history run
- **WHEN** the user runs `tr-cli history` with a valid session and held positions
- **THEN** the output contains one daily point per trading day in the window, with `total` = Σ (qty × close) over positions that have a bar that day, plus current cash

#### Scenario: window flags
- **WHEN** the user runs `tr-cli history --days 365`
- **THEN** the series covers the last 365 days (default 365, maximum 730, usage error above)

### Requirement: missing-bar exclusion
The CLI SHALL exclude a position from a day's total when that position has no bar for that date (no extrapolation), and SHALL exclude a position entirely from the series when its series fetch fails.

#### Scenario: partial position coverage
- **WHEN** one position lacks a bar on a date that other positions have
- **THEN** that date's total is computed from the positions that DO have bars

#### Scenario: failed series fetch
- **WHEN** a position's `tradeAggregateHistory` subscription fails or times out
- **THEN** the position is omitted from every day's total and the command still succeeds

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

