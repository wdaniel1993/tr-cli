## 1. Protocol + transport

- [x] 1.1 `protocol.py`: bump TR_APP_VERSION default to 2.2632.29; add timeline/YTD constants (topics, resolution_ms, jan-1 helper)
- [x] 1.2 `ws.py`: add multi-round pagination helper (one connection, subscribe page N with `after` cursors, collect, repeat)

## 2. Timeline module

- [x] 2.1 `timeline.py`: fetch both topics, merge + dedupe by id, paginate to 90-day cutoff
- [x] 2.2 Classification table (deposits/withdrawals/interest/dividends/orders/corporate_actions/documents/other) + bucket aggregation with signed amounts
- [x] 2.3 CLI `timeline` command (human + JSON; `--days`, `--bucket` filters) + render

## 3. YTD

- [x] 3.1 `client.py`: per-position YTD via `tradeAggregateHistory` daily bars (base = first bar open), null-safe; portfolio `ytdTotal`
- [x] 3.2 Portfolio JSON gains `ytd` fields (backward compatible) + human render line

## 4. Mock + tests

- [x] 4.1 `mock.py`: timeline fixtures (multi-page, all buckets, amounts) + tradeAggregateHistory daily-bar fixtures
- [x] 4.2 Tests: timeline merge/dedupe/pagination/classification/amounts; YTD math + null-safety; CLI JSON shape + backward compat
- [x] 4.3 Full suite (pytest) + ruff check + format

## 5. Docs + version

- [x] 5.1 README: timeline command, YTD semantics (first-trading-day base), version 0.2.0
- [x] 5.2 wire-notes: REST timeline endpoints, timeline topic taxonomy, tradeAggregateHistory/aggregateHistoryLightV2 payloads, portfolio-chart endpoint, app version bump
- [x] 5.3 Version bump 0.1.1 -> 0.2.0 (pyproject + __init__)

## 6. Verify + ship

- [x] 6.1 One live verification (spaced, single WS connection): `tr-cli timeline` (financial events present) + `tr-cli --json portfolio` ytd fields; record findings in wire-notes
- [x] 6.2 openspec validate, sync specs, archive change, commit + push origin/main
