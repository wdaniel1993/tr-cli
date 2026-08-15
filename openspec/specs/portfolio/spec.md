# portfolio Specification

## Purpose
TBD - created by archiving change initial-cli. Update Purpose after archive.
## Requirements
### Requirement: portfolio positions and cash
The CLI SHALL fetch portfolio positions and cash balances over the authenticated Trade Republic WebSocket using the `compactPortfolioByType` (with `secAccNo` from `GET /api/v2/auth/account`) and `cash` topics, and render them as a table with totals.

The `cash` topic returns an **array** of per-account/per-currency balances `[{accountNumber, currencyId, amount}]`; the CLI SHALL parse this array and aggregate the amounts per `currencyId`. The per-currency amount equals the available cash for that currency (verified live: `cash` and `availableCashForPayout` return identical values). The CLI SHALL NOT assume a dict-shaped `{total, available}` payload.

The CLI SHALL compute `totalValue` as the sum of position net values **only** (matching the TR app's "portfolio value"); cash is displayed separately and MUST NOT be added to `totalValue`.

#### Scenario: portfolio with positions and cash
- **WHEN** the user runs `tr-cli portfolio` with a valid session
- **THEN** the CLI prints a table of positions (name, ISIN, quantity, price, avg cost, net value), a cash section listing each currency's available amount, and a portfolio total that excludes cash

#### Scenario: cash topic returns an array with multiple currencies
- **WHEN** the `cash` topic answers `[{accountNumber, currencyId, amount}, ...]` with multiple entries
- **THEN** the CLI aggregates amounts per currencyId and renders one cash line per currency plus the summed total

#### Scenario: empty portfolio
- **WHEN** the account has no positions
- **THEN** the CLI prints the cash balance and a zero portfolio total without errors

#### Scenario: mock and real cash shapes agree
- **WHEN** the user runs `tr-cli --mock portfolio`
- **THEN** the mock renders the same array-shaped cash structure (per-currency amounts) as real mode

### Requirement: position enrichment
The CLI SHALL enrich positions with instrument names (`instrument` topic) and live prices (`ticker` topic on the position's first exchange) so the portfolio shows readable names and current values.

#### Scenario: names and live prices
- **WHEN** the portfolio contains positions
- **THEN** each row shows the instrument short name and a live last price, and the net value is computed from price × net size

#### Scenario: missing ticker
- **WHEN** no ticker price arrives for a position within the timeout
- **THEN** the CLI reports the position as missing a price instead of failing the whole command

