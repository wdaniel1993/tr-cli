## 1. Implementation (done in 0b7be21, v0.2.2)

- [x] 1.1 Forward-fill per-position closes; series start = max(first bar date); note documents the rule
- [x] 1.2 JSON `coverage` object {positions, forward_filled, start_rule}
- [x] 1.3 Mock middle-gap support (`history_gaps`, `_history_bars gap_indices`, visible-bar pricing)
- [x] 1.4 Regression tests (no-drop, start-covers-all) + full suite green + ruff clean
- [x] 1.5 Version bump 0.2.2, README + wire-notes updated, commit + push 0b7be21
- [x] 1.6 Live verification: July drop cluster gone, coverage 8/8, last total ≈ totalValue + cash

## 2. Documentation change

- [x] 2.1 Create openspec change fix-history-forward-fill (proposal/design/specs/tasks referencing 0b7be21)
- [x] 2.2 openspec validate

## 3. Archive + ship

- [x] 3.1 Archive change, sync history spec, commit + push openspec artifacts
