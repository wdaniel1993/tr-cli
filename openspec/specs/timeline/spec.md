# timeline Specification

## Purpose
TBD - created by archiving change timeline-and-performance. Update Purpose after archive.
## Requirements
### Requirement: timeline command
The CLI SHALL provide a `timeline` command that fetches the account's event history from BOTH the `timelineTransactions` and `timelineActivityLog` WebSocket topics (the app merges these streams; financial events live in `timelineTransactions`, reports/corporate actions/documents in `timelineActivityLog`), merges them, deduplicates by event id, and renders them newest-first.

#### Scenario: merged feed with financial events
- **WHEN** the user runs `tr-cli timeline`
- **THEN** the output contains financial events (dividends, transfers, interest, savings-plan executions) from `timelineTransactions` alongside reports/corporate actions/documents from `timelineActivityLog`, without duplicate ids

### Requirement: timeline pagination (90 days)
The CLI SHALL paginate using the `after` cursor from each topic's `cursors` object on a single WebSocket connection, continuing until events older than the requested window (default ~90 days) are reached or the cursor is exhausted.

#### Scenario: multi-page fetch
- **WHEN** the timeline spans more than one page (30 items per page observed)
- **THEN** the CLI fetches subsequent pages with the `after` cursor and returns events back to the 90-day cutoff

#### Scenario: cursor exhausted
- **WHEN** the server returns no further `after` cursor
- **THEN** the CLI stops paginating

### Requirement: timeline classification
The CLI SHALL classify each event by its `eventType` into exactly one of the buckets {deposits, withdrawals, interest, dividends, orders, corporate_actions, documents, other} and expose the bucket per event and as aggregated sums (amounts, signed, per bucket).

#### Scenario: known event types map to buckets
- **WHEN** events have eventTypes such as `BANK_TRANSACTION_INCOMING`, `BANK_TRANSACTION_OUTGOING`, `INTEREST_PAYOUT`, `SSP_CORPORATE_ACTION_DIVIDEND_EQUIVALENT`, `TRADING_SAVINGSPLAN_EXECUTED`, `TAX_YEAR_END_REPORT_CREATED`, `SSP_CORPORATE_ACTION_INFORMATIVE`
- **THEN** they are classified as deposits, withdrawals, interest, dividends, orders, documents, corporate_actions respectively

#### Scenario: unknown event type
- **WHEN** an eventType is not recognized
- **THEN** the event is classified as `other` and still included in the output

### Requirement: timeline amounts and JSON output
The CLI SHALL include the signed `amount` (`{currency, value, fractionDigits}`) in the JSON output whenever the event carries one, and render it in human output.

#### Scenario: amount present
- **WHEN** a timeline event has an amount object
- **THEN** the JSON output includes `amount: {currency, value, fractionDigits}` and human output shows the formatted signed amount

#### Scenario: no amount
- **WHEN** an event has no amount (typical for `timelineActivityLog` items)
- **THEN** the output omits the amount without error

