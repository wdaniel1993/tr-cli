# ytd Specification

## Purpose
TBD - created by archiving change timeline-and-performance. Update Purpose after archive.
## Requirements
### Requirement: per-position YTD gains
The CLI SHALL extend `tr-cli portfolio` with per-position YTD: fetch the daily OHLC series for each position via the `tradeAggregateHistory` WebSocket topic (`{type, isin, exchangeId, resolution: 86400000, from: <2026-01-01T00:00Z>, until: <now>}`), take the first bar's `open` as the year-start base price (the first trading day of the year — documented, not faked as midnight Jan 1), and compute `ytdGain = (price_now − base) × netSize`. When no series is available the ytd fields MUST be `null` rather than approximate values.

#### Scenario: YTD for a held position
- **WHEN** the user runs `tr-cli portfolio --json` and the series topic answers
- **THEN** each position includes `ytd: {basePrice, ytdGain, ytdPct}` and the top level includes `ytdTotal` (sum of position gains)

#### Scenario: series unavailable
- **WHEN** the series topic does not answer for a position (timeout/error)
- **THEN** the position's ytd fields are null and the command still succeeds (backward compatible)

### Requirement: backward-compatible portfolio output
The YTD additions SHALL NOT remove or rename existing portfolio JSON fields.

#### Scenario: old consumers still work
- **WHEN** a script consumes the pre-YTD portfolio JSON
- **THEN** every previously existing field (positions, cash, totalValue) keeps its shape and values

