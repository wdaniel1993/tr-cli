## 1. Project Scaffold

- [ ] 1.1 Initialize uv project (`pyproject.toml`, src layout `src/tr_cli/`) with deps typer, requests, websockets; dev deps pytest, pytest-asyncio, ruff
- [ ] 1.2 Add `.gitignore` (`.env`, `.tr-cli/`, `cookies.txt`, `__pycache__/`, `.venv/`, dist artifacts)
- [ ] 1.3 Add README skeleton (install, usage, safety/rate-limit warnings)

## 2. Protocol Core

- [ ] 2.1 Implement `protocol.py`: endpoint constants, TR header builders (`x-tr-device-info` base64 device payload, `x-tr-app-version`, `x-tr-platform`, UA) with env overrides
- [ ] 2.2 Implement WS delta decoder (`A`/`D`/`C`/`E` frame parsing, `+`/`-N`/`=N` delta algorithm)
- [ ] 2.3 Unit tests for delta decoder and header builders with fixture payloads

## 3. Auth & Session

- [ ] 3.1 Implement `auth.py`: v2 initiate (POST), process poll (GET), cookie harvesting from Set-Cookie, 429/credential error mapping with `RateLimited(next_attempt_at)` errors
- [ ] 3.2 Implement session persistence: Netscape cookie jar at `~/.tr-cli/cookies.txt` (0600, atomic write), load/validate, device_id persistence
- [ ] 3.3 Implement session refresh (`GET /api/v1/auth/web/session`) and keepalive window logic
- [ ] 3.4 Unit tests: mock HTTP round-trips for login success, approval timeout, invalid creds, 429 cooldown, cookie persistence (chmod 600), refresh rotation

## 4. WebSocket Client & Data Commands

- [ ] 4.1 Implement `ws.py`: connect with cookie header, `connect` handshake, subscribe/unsubscribe, response collection with timeout
- [ ] 4.2 Implement `client.py`: `account()` (GET /api/v2/auth/account), portfolio (compactPortfolioByType + cash + instrument/ticker fan-out), rates (instrument + ticker), details (instrument, stockDetails, ticker, performance, instrumentSuitability)
- [ ] 4.3 Implement `render.py`: fixed-width tables, cash section, totals, bond price /100, Decimal net value
- [ ] 4.4 Unit tests with fake WS/HTTP: portfolio assembly incl. empty portfolio + missing ticker, rates parsing, details partial data

## 5. Mock Mode

- [ ] 5.1 Implement `mock.py`: `MockTransport` with bundled fixtures (login, account, portfolio, cash, instrument, ticker, stockDetails, performance, suitability) and a 429-mode switch
- [ ] 5.2 Wire `--mock` global flag + `TR_CLI_MOCK=1` env into transport resolution

## 6. CLI Surface

- [ ] 6.1 Implement Typer app: `login`, `session status`, `session refresh`, `portfolio`, `rates`, `details`; phone/PIN via env or prompt; `--json` output; exit codes
- [ ] 6.2 CLI-level tests via `typer.testing.CliRunner` against MockTransport (login, status, refresh, portfolio, rates, details, 429 message, JSON shape)

## 7. Docs & Wire Recording

- [ ] 7.1 Write `docs/wire-notes.md` template documenting endpoints, headers, cookie inventory, WS topics and frame format (from research; to be confirmed during real spike)
- [ ] 7.2 Verify openspec change (`openspec validate`), run full test suite + ruff, commit and push to origin/main

## 8. Real-Account Spike (rate-limited, opt-in)

- [ ] 8.1 With Daniel's approval flow only: single v2 login attempt (spaced, no retries on 429), record exact responses/cookie shapes into `docs/wire-notes.md`
- [ ] 8.2 Verify portfolio/rates/details against the real account once, spaced, and record any discrepancies
- [ ] 8.3 Final verification (`openspec verify`), archive change, final commit + push
