# details Specification

## Purpose
TBD - created by archiving change initial-cli. Update Purpose after archive.
## Requirements
### Requirement: instrument details
The CLI SHALL fetch and render instrument details for an ISIN from the `instrument`, `stockDetails`, `ticker`, `performance`, and `instrumentSuitability` WebSocket topics.

#### Scenario: full detail view
- **WHEN** the user runs `tr-cli details <ISIN>` with a valid session
- **THEN** the CLI prints instrument identity (name, short name, type, exchanges), a live quote, company snapshot, and recent news headlines

#### Scenario: details without optional topics
- **WHEN** some optional detail topics return no data
- **THEN** the CLI renders the fields it did receive and notes the missing ones without failing

