# rates Specification

## Purpose
TBD - created by archiving change initial-cli. Update Purpose after archive.
## Requirements
### Requirement: quote lookup for ISINs
The CLI SHALL fetch current quotes for one or more ISINs via the `instrument` and `ticker` WebSocket topics and render name, ISIN, last price, and ask price.

#### Scenario: single ISIN quote
- **WHEN** the user runs `tr-cli rates DE0005140008`
- **THEN** the CLI prints the instrument name and its last/ask prices

#### Scenario: multiple ISINs and separators
- **WHEN** the user passes multiple ISINs separated by commas, semicolons, or spaces
- **THEN** the CLI fetches and prints a quote row for each valid ISIN

#### Scenario: invalid ISIN token
- **WHEN** a token does not match the ISIN pattern `[A-Z]{2}[A-Z0-9]{10}`
- **THEN** the CLI warns and skips the token without failing the command

#### Scenario: missing price
- **WHEN** no ticker price arrives for an ISIN within the timeout
- **THEN** the CLI reports that ISIN as having no price instead of failing the whole command

