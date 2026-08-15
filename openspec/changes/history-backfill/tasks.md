## 1. Transport

- [ ] 1.1 `ws.py`: `rounds()` helper — one connection, sequential subscribe rounds (each round = list of (key, payload), collect, unsub); `Transport.ws_rounds` abstract + RealTransport + MockTransport

## 2. History module

- [ ] 2.1 `client.py`: `history(transport, days)` — account → rounds[compact+cash, instrument, tradeAggregateHistory]; build date-indexed totals (missing-bar exclusion, cash constant); HistoryResult dataclass
- [ ] 2.2 CLI `history` command: `--days` (default 365, max 730, usage error above), JSON contract `{ok, start_date, end_date, days, approximate, note, series:[{date,total,cash|null}]}`, compact human table (date, total, Δ)

## 3. Mock + tests

- [ ] 3.1 `mock.py`: multi-position daily-bar fixtures (aligned + a missing-bar ISIN case); ws_rounds emulation
- [ ] 3.2 Tests: series math (qty×close+cash), missing-bar exclusion, date conversion, empty portfolio, --days cap, JSON contract shape, mock/real consistency
- [ ] 3.3 Full suite green (existing 58 + new) + ruff + format

## 4. Docs + version

- [ ] 4.1 README: history command + approximation semantics; version 0.2.1
- [ ] 4.2 wire-notes: record Eve's full-series verification + history design

## 5. Verify + ship

- [ ] 5.1 Live verification (single spaced invocation, ~1 new WS connection): `tr-cli --json history --days 365` — bar count sanity, first-total vs YTD arithmetic (Σ qty×base + cash ≈ totalValue − ytdTotal + cash), last total ≈ totalValue + cash
- [ ] 5.2 openspec validate, sync specs, archive, commit + push origin/main
