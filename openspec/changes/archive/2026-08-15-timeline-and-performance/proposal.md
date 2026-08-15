## Why

Daniel wants a daily report with (a) timeline events explaining cash/position changes, (b) deposits-vs-capital-gains breakdown, (c) YTD gains. Eve builds the chart/cron side consuming tr-cli output. Investigation (bundle v2.2632.29 + live probes 2026-08-15) established: the financial events (dividends, transfers, interest, savings-plan buys) live in the `timelineTransactions` WS topic — NOT `timelineActivityLog` (reports/corporate actions/docs) — and the app merges both streams. YTD needs a price series: the app's instrument chart uses the `tradeAggregateHistory` WS topic (daily OHLC series) and its portfolio chart uses a REST endpoint `api-gateway/portfolio-chart/v2/chart` (the `portfolioAggregateHistory` replacement). tr-cli has neither timeline nor YTD today.

## What Changes

- New `tr-cli timeline` command: fetches `timelineTransactions` + `timelineActivityLog` over one WS connection, paginates via the `after` cursor to cover ~90 days, merges + dedupes by id, classifies `eventType` into buckets {deposits, withdrawals, interest, dividends, orders, corporate_actions, documents, other}, and renders human (terminal) + `--json` output with amounts (`{currency, value, fractionDigits}`) when present.
- Extend `tr-cli portfolio` with YTD: per-position `ytd` (base price from the first daily `tradeAggregateHistory` bar of 2026 — the first trading day's open; honestly documented as such), `ytdGain = (price_now − base) × netSize`, and a portfolio `ytdTotal`. Backward compatible (new fields only).
- App-version default bump: `TR_APP_VERSION` 2.2631.13 → 2.2632.29 (current web bundle).
- Version bump 0.1.1 → 0.2.0.
- Record bundle findings in `docs/wire-notes.md`: REST timeline endpoints, timeline topic taxonomy, `tradeAggregateHistory` + `aggregateHistoryLightV2` payloads, portfolio-chart REST endpoint (the `portfolioAggregateHistory` replacement — relevant for Eve's chart side).

## Capabilities

### New Capabilities
- `timeline`: timeline event history (dual-topic fetch, pagination, classification, amounts, JSON/human output).
- `ytd`: per-position and portfolio YTD gains from the daily OHLC series topic.

### Modified Capabilities
- None (greenfield additions).

## Impact

- `src/tr_cli/`: new `timeline` module + `client.py` YTD additions + `ws.py` multi-round pagination helper + `protocol.py` app-version bump + `mock.py` timeline/ytd fixtures + `cli.py` commands + `render.py`.
- `tests/`: timeline classification/pagination, YTD computation, mock consistency.
- Version 0.2.0; docs (README, wire-notes).
