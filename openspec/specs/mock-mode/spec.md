# mock-mode Specification

## Purpose
TBD - created by archiving change initial-cli. Update Purpose after archive.
## Requirements
### Requirement: mock mode for offline use
The CLI SHALL provide a `--mock` flag (and `TR_CLI_MOCK=1` env var) that switches the transport to an in-process mock serving bundled fixture data, so the entire command surface works without network access or a real account.

#### Scenario: mock login
- **WHEN** the user runs `tr-cli --mock login`
- **THEN** the CLI simulates the v2 push flow (no real network call) and ends with a usable mock session

#### Scenario: mock data commands
- **WHEN** the user runs `tr-cli --mock portfolio|rates|details`
- **THEN** the CLI renders fixture-based results identical in shape to the real commands

#### Scenario: mock rate-limit
- **WHEN** the user runs `tr-cli --mock login` with the mock configured to return a 429
- **THEN** the CLI prints the cooldown message exactly as it would for a real 429

