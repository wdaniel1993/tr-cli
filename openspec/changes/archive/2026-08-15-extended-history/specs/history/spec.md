## MODIFIED Requirements

### Requirement: history command
The CLI SHALL provide a `history` command that builds a daily portfolio value series from Trade Republic's official portfolio-chart REST endpoint `GET /api-gateway/portfolio-chart/v2/chart?secAccNo=<secAccNo>&range=<1y|max>&currency=EUR` (secAccNo from `GET /api/v2/auth/account`; ranges 3y/6m return HTTP 400 server-side and SHALL NOT be used). `range=1y` daily points SHALL win over `range=max` coarser points on overlapping dates; the curve SHALL start at the first NON-ZERO netValue point; optional local collector snapshots SHALL override chart points on matching dates. The series total SHALL be the chart `netValue` (positions only, matching `portfolio.totalValue` and the TR app), and `approximate` SHALL be `false` (the chart reflects real historical holdings — no retroactive-quantity approximation). The old per-position tradeAggregateHistory-based backfill is replaced (tradeAggregateHistory remains only for per-position YTD).

The CLI SHALL reconstruct historical cash from the REST timeline transactions feed (`GET /api/v2/timeline/transactions?limit=100`, paginated via `olderThan=<cursors.after>`), counting ANY amount-bearing event (the feed is the cash-movement feed by construction; verified live: all items carry signed amounts). cash(date) = current_cash − Σ(signed amounts with timestamp > date at 00:00 UTC); constant between events; ~0 before the first event (a reconciliation invariant: current_cash − Σ(events) must be small, else the classification is wrong). The per-point `cash` field is the reconstructed value (NOT constant).

#### Scenario: full history from portfolio chart
- **WHEN** the user runs `tr-cli history`
- **THEN** the series covers the merged 1y+daily / max-coarser points from the first non-zero netValue date, with `total` = positions-only netValue

#### Scenario: merge order
- **WHEN** a date exists in both the 1y and max ranges
- **THEN** the 1y (daily) point is used; max fills only dates before the 1y range; collector snapshots override both on matching dates

#### Scenario: leading zero dropped
- **WHEN** the coarser range starts with a netValue of 0.00
- **THEN** the curve starts at the first non-zero point

#### Scenario: granularity note
- **WHEN** the merged series spans both ranges
- **THEN** the note states "daily since <1y start date>, coarser before"

#### Scenario: cash reconstruction invariant
- **WHEN** the series is built
- **THEN** reconstructed cash is ~0 before the first event (within a small residual, noted when non-zero) and never goes negative mid-series (negative values are flagged, not fatal)

#### Scenario: cash pagination
- **WHEN** the transactions feed has more than one page
- **THEN** the CLI follows `cursors.after` via `olderThan` until the feed is exhausted

### Requirement: JSON output contract
The CLI SHALL emit `--json` as `{ok, start_date, end_date, days, approximate, note, coverage, series:[{date, total, cash}]}` where `total` = positions (netValue), `cash` = reconstructed cash (string; null only when unavailable), `approximate` = false, the note includes granularity + cash reconstruction summary, and `coverage` describes the sources. Real account numbers (secAccNo, cashAccountNumber) SHALL NOT appear in any output or committed artifact.

#### Scenario: contract shape
- **WHEN** the user runs `tr-cli --json history`
- **THEN** stdout is exactly one JSON document matching the contract with no real account identifiers

#### Scenario: human output
- **WHEN** the user runs `tr-cli history` without `--json`
- **THEN** a compact date/total/cash/Δ table is rendered with the note line
