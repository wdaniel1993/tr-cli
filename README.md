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
tr-cli portfolio            # positions + cash + totals
tr-cli rates DE0005140008 US0378331005
tr-cli details US0378331005
```

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
