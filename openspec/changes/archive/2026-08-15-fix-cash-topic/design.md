## Context

The initial-cli change shipped and the real-account spike (2026-08-15) recorded true wire shapes in `docs/wire-notes.md`. The spike exposed a bug: the `cash` WS topic returns an **array** `[{accountNumber, currencyId, amount}]`, but `_parse_cash` expects a dict `{total, available}` — so real-mode cash is always `0 / null`. Daniel's app (same day): available cash EUR 1234.56; portfolio value EUR 180050.00. CLI (10:10): cash 0/null; totalValue 180000.00.

## Goals / Non-Goals

**Goals:**
- Cash parses the real array shape and renders per-currency available amounts that match the app (EUR 1234.56).
- `totalValue` semantics made explicit and consistent between real and mock mode.
- Small change: no new dependencies, no protocol changes; mock + tests updated to the real shape.

**Non-Goals:**
- Chasing exact quote parity with the app (weekend/stale quotes; ~EUR 50 drift is expected and fine).
- Subscribing to `availableCashForPayout` (verified identical to `cash` on a live account — noted as alternative).
- Any login/auth changes.

## Decisions

### D1: Parse the `cash` array; aggregate per currencyId
`cash` → `[{accountNumber, currencyId, amount}, …]` (one entry per cash account). `CashBalance` becomes a list of `CashItem{currency_id, amount, account_number}` with a `total` = sum of amounts. `_parse_cash` handles: list of dicts (real), single dict (defensive fallback: treat as one item), empty/missing → empty balance.
- **Alternative considered**: subscribe `availableCashForPayout` instead. **Live probe 2026-08-15 proved both topics return the identical value** (EUR 1234.56 == app's available cash), so `cash` alone is the simplest correct approach; the alternative is documented here and in wire-notes.

### D2: totalValue = positions only (matches app), documented
Verified by arithmetic from Daniel's same-day numbers: app portfolio value 180050.00 vs CLI positions 180000.00 (Δ ≈ EUR 50.00 = quote drift); positions + cash would be 181234.56 ≠ 180050.00. So the app's "portfolio value" excludes cash. tr-cli keeps `totalValue` = Σ position net values and renders cash separately. This is documented in the code (docstring), README, and the portfolio spec. Note: pytr's own "Total" includes cash — we deliberately follow the TR app instead.

### D3: Mock and CLI JSON shape follow the real array
`FIXTURE_CASH` becomes `[{accountNumber, currencyId, amount}, …]`. `--json portfolio` emits `"cash": {"items": [{"currencyId", "amount"}], "total": "…"}` (accountNumber omitted from CLI JSON to avoid leaking account ids into scripts/logs). Human render shows one `CASH  <currency>: <amount>` line per currency and a summed total when >1 currency.

### D4: Redaction discipline
The probe revealed a real cash account number; wire-notes gets only the masked structure (`<redacted>`), never account numbers or amounts beyond what Daniel already shared publicly in this task.

## Risks / Trade-offs

- [Multi-currency accounts render multiple cash lines] → Summed `total` and per-currency lines; trivial for the common single-currency case.
- [TR changes the cash shape again] → `_parse_cash` is defensive (list or dict); protocol constants centralized; wire-notes updated on next spike.
- [Session expires mid-verification] → Constraint says stop network work and finish from wire-notes + mock; all logic is covered by mock tests regardless.

## Migration Plan

1. Update `client.py` (model + parser) → 2. `mock.py` fixture → 3. `render.py` + `cli.py` shapes → 4. tests → 5. docs (README, wire-notes) → 6. one live verification run (single WS connection, budget allows) → 7. sync specs, archive, commit + push.

## Open Questions

- None blocking. (Confirmed: cash == available; totalValue = positions only; both empirically verified.)
