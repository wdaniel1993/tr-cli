## Why

The CLI's cash output disagrees with the real Trade Republic app: Daniel's app shows available cash EUR 1234.56, but `tr-cli portfolio` reports `cash total 0 / available null`. Root cause (verified in the real-account spike, `docs/wire-notes.md`): the `cash` WebSocket topic returns an **array** `[{accountNumber, currencyId, amount}]`, while `_parse_cash` in `src/tr_cli/client.py` expects a dict `{total, available}` — so real-mode cash always parses empty. The mock fixture and tests encode the same wrong dict shape. Additionally, `totalValue` semantics (positions only vs positions + cash) are undocumented; the app's "portfolio value" needs to be matched and documented.

## What Changes

- Fix `_parse_cash` to parse the real **array** shape: one entry per cash account/currency, summing amounts per `currencyId`.
- Verified semantics (live probe 2026-08-15): `cash` amount == `availableCashForPayout` amount == app's "available cash" (EUR 1234.56 exactly). So the `cash` topic alone is sufficient; `availableCashForPayout` is a verified-identical alternative that we do NOT need to subscribe to.
- Update `CashBalance` model, portfolio rendering, `--json` output shape, mock fixture (`FIXTURE_CASH` → array), and tests so mock and real mode are consistent.
- Document `totalValue` semantics: **positions only** (matches the app's "portfolio value"; verified by arithmetic — app 180050.00 vs CLI positions 180000.00 ≈ EUR 51 quote drift; positions + cash would be 181234.56, which does not match). No change to the totalValue calculation; add documentation in code, README, and spec.
- Append the verified probe findings (redacted — account number masked) to `docs/wire-notes.md`.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `portfolio`: the "portfolio positions and cash" requirement changes — cash is a per-currency balance array, and totalValue semantics (positions only) are made explicit.

## Impact

- `src/tr_cli/client.py` (`CashBalance`, `_parse_cash`, `portfolio` totalValue doc), `src/tr_cli/render.py` (cash rendering), `src/tr_cli/cli.py` (cash JSON shape), `src/tr_cli/mock.py` (`FIXTURE_CASH`), `tests/` (cash assertions), `README.md`, `docs/wire-notes.md`, `openspec/specs/portfolio/spec.md` (delta → sync on archive).
- No new dependencies. No network-protocol changes.
