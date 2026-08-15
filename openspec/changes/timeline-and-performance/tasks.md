## 1. Protocol + transport

- [ ] 1.1 `protocol.py`: bump TR_APP_VERSION default to 2.2632.29; add timeline/YTD constants (topics, resolution_ms, jan-1 helper)
- [ ] 1.2 `ws.py`: add multi-round pagination helper (one connection, subscribe page N with `after` cursors, collect, repeat)

## 2. Timeline module

- [ ] 2.1 `timeline.py`: fetch both topics, merge + dedupe by id, paginate to 90-day cutoff
- [ ] 2.2 Classification table (deposits/withdrawals/interest/dividends/orders/corporate_actions/documents/other) + bucket aggregation with signed amounts
- [ ] 2.3 CLI `timeline` command (human + JSON; `--days`, `--bucket` filters) + render

## 3. YTD

- [ ] 3.1 `client.py`: per-position YTD via `tradeAggregateHistory` daily bars (base = first bar open), null-safe; portfolio `ytdTotal`
- [ ] 3.2 Portfolio JSON gains `ytd` fields (backward compatible) + human render line

## 4. Mock + tests

- [ ] 4.1 `mock.py`: timeline fixtures (multi-page, all buckets, amounts) + tradeAggregateHistory daily-bar fixtures
- [ ] 4.2 Tests: timeline merge/dedupe/pagination/classification/amounts; YTD math + null-safety; CLI JSON shape + backward compat
- [ ] 4.3 Full suite (pytest) + ruff check + format

## 5. Docs + version

- [ ] 5.1 README: timeline command, YTD semantics (first-trading-day base), version 0.2.0
- [ ] 5.2 wire-notes: REST timeline endpoints, timeline topic taxonomy, tradeAggregateHistory/aggregateHistoryLightV2 payloads, portfolio-chart endpoint, app version bump
- [ ] 5.3 Version bump 0.1.1 -> 0.2.0 (pyproject + __init__)

## 6. Verify + ship

- [ ] 6.1 One live verification (spaced, single WS connection): `tr-cli timeline` (financial events present) + `tr-cli --json portfolio` ytd fields; record findings in wire-notes
- [ ] 6.2 openspec validate, sync specs, archive change, commit + push origin/main
