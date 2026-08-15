## ADDED Requirements

### Requirement: portfolio positions and cash
The CLI SHALL fetch portfolio positions and cash balances over the authenticated Trade Republic WebSocket using the `compactPortfolioByType` (with `secAccNo` from `GET /api/v2/auth/account`) and `cash` topics, and render them as a table with totals.

#### Scenario: portfolio with positions and cash
- **WHEN** the user runs `tr-cli portfolio` with a valid session
- **THEN** the CLI prints a table of positions (name, ISIN, quantity, price, avg cost, net value), a cash section, and a portfolio total

#### Scenario: empty portfolio
- **WHEN** the account has no positions
- **THEN** the CLI prints the cash balance and a zero portfolio total without errors

### Requirement: position enrichment
The CLI SHALL enrich positions with instrument names (`instrument` topic) and live prices (`ticker` topic on the position's first exchange) so the portfolio shows readable names and current values.

#### Scenario: names and live prices
- **WHEN** the portfolio contains positions
- **THEN** each row shows the instrument short name and a live last price, and the net value is computed from price × net size

#### Scenario: missing ticker
- **WHEN** no ticker price arrives for a position within the timeout
- **THEN** the CLI reports the position as missing a price instead of failing the whole command
