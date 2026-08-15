## 1. Implementation

- [ ] 1.1 `client.py`: per-day total = Σ qty×close (positions only); remove cash from total; keep per-point `cash` field; update docstring + note wording
- [ ] 1.2 Regression test: total == sum of qty×close and cash is a separate field never added
- [ ] 1.3 Update affected history tests (last-point totals, JSON contract expectations)
- [ ] 1.4 Full suite green + ruff clean; version bump 0.2.3; README + wire-notes updated

## 2. Verify + ship

- [ ] 2.1 Live verification (spaced): last backfill point vs portfolio totalValue, boundary gap < 0.5%
- [ ] 2.2 openspec validate, archive change, sync history spec, commit + push origin/main
