## MODIFIED Requirements

### Requirement: history command
The CLI SHALL provide a `history` command that builds a daily portfolio value series from Trade Republic's official portfolio-chart REST endpoint `GET /api-gateway/portfolio-chart/v2/chart?secAccNo=<secAccNo>&range=<1y|max>&currency=EUR` (secAccNo from `GET /api/v2/auth/account`; ranges 3y/6m return HTTP 400 server-side and SHALL NOT be used). `range=1y` daily points SHALL win over `range=max` coarser points on overlapping dates; the curve SHALL start at the first NON-ZERO netValue point; optional local collector snapshots SHALL override chart points on matching dates. The series total SHALL be the chart `netValue` (positions only, matching `portfolio.totalValue` and the TR app). The old per-position tradeAggregateHistory-based backfill is replaced (tradeAggregateHistory remains only for per-position YTD).

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

### Requirement: historical cash reconstruction
The CLI SHALL reconstruct historical cash from the REST timeline transactions feed (`GET /api/v2/timeline/transactions?limit=100`, paginated via `olderThan=<cursors.after>`), using only CASH-MOVING event types (BANK_TRANSACTION_INCOMING/OUTGOING, INTEREST_PAYOUT, SSP_CORPORATE_ACTION_DIVIDEND_EQUIVALENT, TRADING_SAVINGSPLAN_EXECUTED, TRADING_TRADE_EXECUTED, CARD_TRANSACTION, CARD_AFT, PAYMENT_INBOUND/OUTBOUND, SAVEBACK_AGGREGATE, SSP_CORPORATE_ACTION_CASH). Informational events (e.g. SAVINGS_PLAN_INVOICE_CREATED) SHALL be excluded to avoid double counting. cash(date) = current_cash − Σ(signed amounts with timestamp > date at 00:00 UTC); constant between events; ~0 before the first event. The per-point `cash` field is the reconstructed value (NOT constant).

#### Scenario: reconciliation invariant
- **WHEN** the series starts at the first event date
- **THEN** reconstructed cash at that date is ~0 (within a small tolerance); a violation flags the event classification as wrong (the test fails before shipping)

#### Scenario: cash walk
- **WHEN** events are sorted by date
- **THEN** cash is constant between events, steps by each event's signed amount, and never goes negative mid-series (negative values are flagged in the note, not fatal)

#### Scenario: pagination
- **WHEN** the transactions feed has more than one page
- **THEN** the CLI follows `cursors.after` via `olderThan` until the feed is exhausted

### Requirement: output contract
The CLI SHALL emit `--json` as `{ok, start_date, end_date, days, approximate, note, series:[{date, total, cash}]}` where `total` = positions (netValue), `cash` = reconstructed cash (string; null only when unavailable), `approximate` = false (the chart reflects real historical holdings), and the note includes granularity + cash reconstruction summary. Real account numbers (secAccNo, cashAccountNumber) SHALL NOT appear in any output or committed artifact.

#### Scenario: contract shape
- **WHEN** the user runs `tr-cli --json history`
- **THEN** stdout is exactly one JSON document matching the contract with no real account identifiers
