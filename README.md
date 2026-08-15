# tr-cli

Small, unofficial Trade Republic CLI: v2 push-approval login, portfolio (positions + cash),
rates (quotes), and instrument details. Built for macOS/Linux with Python + uv + Typer.

> ⚠️ **Unofficial.** This uses Trade Republic's internal web API (no official API exists).
> Use at your own risk. **Respect rate limits**: never script repeated logins; the CLI
> never auto-retries a login and shows a cooldown message on `429 TOO_MANY_REQUESTS`.

## Install

```bash
uv sync          # create venv + install
uv run tr-cli --help
```

## Commands

```bash
tr-cli login                # v2 push flow: approve the prompt in the TR mobile app
tr-cli session status       # local check of the saved session (no network)
tr-cli session refresh      # rotate session cookies via /api/v1/auth/web/session
tr-cli portfolio            # positions + cash + totals + YTD
tr-cli history              # daily value curve, start auto-detected from account history
tr-cli timeline             # merged event feed (transactions + activity log), ~90 days
tr-cli timeline --bucket dividends
tr-cli rates DE0005140008 US0378331005
tr-cli details US0378331005
```

### History (value curve backfill)

`tr-cli history` builds a daily portfolio value curve from CURRENT holdings +
per-position daily close series (`tradeAggregateHistory`), over one WS
connection. The **start date is auto-detected** from the account timeline
(earliest of `CUSTOMER_CREATED` / `SECURITIES_ACCOUNT_CREATED` /
`VERIFICATION_TRANSFER_ACCEPTED` / earliest deposit), overridable with
`--since YYYY-MM-DD`. `--days N` (default 90, max 730) is the fallback window
when no start signal is detectable. The `note` states the detected source
(e.g. `account created 2025-11-02`); the server caps daily bars at ~200, so
very long windows are truncated with a note.

For each day, `total` = Σ (qty × close) over positions, **forward-filled per
position** (each position's last known close is carried across gaps from thin
trading or differing market calendars — never summed with fewer positions).
`total` is **positions only** — matching `portfolio.totalValue` and the TR app —
and the per-point `cash` field carries the constant current cash separately for
the chart's cash line (never added to `total`). The series starts at the
**latest first bar date across positions** so every day covers ALL positions
(no artificial drops); the JSON `coverage` object and the note document this.
Positions bought mid-window appear across their whole price history — hence
`approximate: true`. `--json` contract for scripts: `{ok, start_date, end_date,
days, approximate, note, coverage, series: [{date, total, cash|null}]}`. Human
output is a compact date/total/Δ table. `history` totals are positions-only and
merge with `portfolio.totalValue` (cash excluded in both).

### Timeline

`tr-cli timeline` merges the two streams the app itself merges:
- `timelineTransactions` — money events (dividends, transfers, interest,
  savings-plan buys), each with a signed `amount {currency, value, fractionDigits}`
  (positive = inflow, negative = outflow/buy/reinvestment).
- `timelineActivityLog` — reports, corporate actions, document/account events (no amounts).

Events are paginated via the `after` cursor back to `--days` (default 90),
deduplicated by id, and classified into `deposits | withdrawals | interest |
dividends | orders | corporate_actions | documents | other`. `--json` gives the
raw events plus per-bucket sums.

### YTD (portfolio)

`tr-cli portfolio` includes per-position YTD (JSON: `position.ytd`, top-level
`ytdTotal`). The year-start base price is the **first trading day's open** from
the daily `tradeAggregateHistory` series (markets are closed Jan 1 — this is an
honest approximation, not midnight-Jan-1 precision). Positions without a series
get `null`; the CLI never substitutes `price_6m` or other proxies.

### Output semantics (verified against the real app, 2026-08-15)

- **Cash**: the `cash` topic returns one balance per cash account/currency
  (`[{accountNumber, currencyId, amount}]`). The amount is the **available**
  cash for that currency — verified identical to the `availableCashForPayout`
  topic and to the app's "available cash" display (EUR 1234.56 matched exactly).
- **TOTAL VALUE**: sum of position net values **only** — cash is NOT included.
  This matches the app's "portfolio value" (verified by arithmetic: positions
  180000.00 vs app 180050.00 ≈ EUR 51 quote drift; positions + cash would be
  181234.56, which does not match).

Phone and PIN: `--phone`/`--pin` flags, `TR_PHONE`/`TR_PIN` env vars, or interactive prompts.
Session cookies are stored at `~/.tr-cli/cookies.txt` (0600) — never in this repo.

## Demo / mock mode (no network, no account)

```bash
tr-cli --mock login
tr-cli --mock portfolio
tr-cli --mock rates US0378331005
tr-cli --mock details US0378331005
# also via env: TR_CLI_MOCK=1
# mock failure modes: TR_CLI_MOCK_MODE=rate_limited|pending_forever|expired_session
```

## Scripting

`--json` (global flag, before the subcommand) prints one JSON document to stdout:

```bash
tr-cli --json portfolio
tr-cli --json rates US0378331005
```

Exit codes: `0` ok · `1` generic · `2` usage · `3` needs-login · `4` rate-limited ·
`5` login-failed · `6` protocol error.

## Protocol notes

See `docs/wire-notes.md` for the endpoint/header/cookie/WebSocket reference derived from
research of the unofficial implementations (pytr, cdamken/tr-api, NightOwl07, Erim32, autotr).
