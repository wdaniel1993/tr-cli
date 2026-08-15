## 1. Cash parsing fix

- [ ] 1.1 Update `CashBalance` model in `client.py`: per-currency `CashItem` list + `total`; rewrite `_parse_cash` to parse the real array shape `[{accountNumber, currencyId, amount}]` (with defensive single-dict handling)
- [ ] 1.2 Add a docstring to `portfolio()` documenting totalValue = positions only (excludes cash, matches TR app "portfolio value")

## 2. Mock + CLI + rendering

- [ ] 2.1 Update `FIXTURE_CASH` in `mock.py` to the real array shape (multi-currency sample)
- [ ] 2.2 Update `render.py` cash section: one line per currency + summed total
- [ ] 2.3 Update `cli.py` `--json` cash shape: `{"items": [{currencyId, amount}], "total": ...}` (no account numbers)

## 3. Tests

- [ ] 3.1 Update `tests/test_client.py`: array-shape cash assertions (single + multi-currency aggregation, empty cash)
- [ ] 3.2 Update `tests/test_cli.py` + any mock-shape assertions; add a mock/real shape consistency test
- [ ] 3.3 Run full suite (pytest) + ruff check + format

## 4. Docs

- [ ] 4.1 Update README: cash semantics (per-currency available cash) and totalValue = positions only
- [ ] 4.2 Append redacted live-probe findings (cash == availableCashForPayout == app available cash; account number masked) to `docs/wire-notes.md`

## 5. Verification + ship

- [ ] 5.1 One live verification run (`tr-cli --json portfolio`) — single WS connection, spaced after previous probe — confirm cash renders EUR 1234.56 and totalValue ≈ positions only
- [ ] 5.2 openspec validate, sync portfolio spec, archive change, commit + push to origin/main
