## 1. Transport + protocol

- [ ] 1.1 `transport.py`: `request()` gains query `params` (Real + Mock)
- [ ] 1.2 `protocol.py`: chart range constants (1y/max only), timeline REST pagination constants, cash-moving event-type set

## 2. History rewrite

- [ ] 2.1 `client.py`: fetch portfolio-chart 1y + max (HTTP), merge (daily>coarser>snapshots), drop leading zeros, granularity note, approximate=false
- [ ] 2.2 `client.py`: cash reconstruction (REST timeline paginated, cash-moving classification, cash(date) formula, invariant + negative-flag)
- [ ] 2.3 CLI `--snapshots` + `--since`/`--days` filters; render; JSON contract with reconstructed cash

## 3. Mock + tests

- [ ] 3.1 `mock.py`: portfolio-chart fixtures (1y daily + max coarser with leading zero) + paginated timeline REST fixtures (self-consistent: Σ amounts == current cash)
- [ ] 3.2 Tests: reconciliation invariant, merge order, pagination loop, cash walk (constant between events, ~0 at start), granularity note, privacy (no account numbers in JSON)
- [ ] 3.3 Full suite green + ruff + format

## 4. Docs + version

- [ ] 4.1 README + wire-notes (verified chart/timeline facts); version 0.3.0

## 5. Verify + ship

- [ ] 5.1 Live verification (spaced): chart merge + cash invariant on real data; record findings redacted in wire-notes
- [ ] 5.2 openspec validate, archive, sync history spec, commit + push origin/main
