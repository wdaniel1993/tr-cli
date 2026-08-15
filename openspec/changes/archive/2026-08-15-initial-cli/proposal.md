## Why

Daniel wants a small, safe desktop CLI for his real Trade Republic account (portfolio, rates, instrument details) using the unofficial web API. The companion watch app (tr-pebble) is paused because PebbleKit JS can't read Set-Cookie headers; a desktop CLI can — so this CLI also becomes the vehicle for a real-account spike that records exact endpoint responses, cookie shapes, and header requirements (tr_session/tr_refresh, X-TR-Device-Info) for a future watch-app bridge. The home IP was recently rate-limited by TR, so the CLI must be mock-first and never burst real login attempts.

## What Changes

- Create a new Python CLI (`tr-cli`) built with uv + Typer, implementing the unofficial TR web API protocol:
  - `login`: v2 push-approval flow (`POST /api/v2/auth/web/login` → poll process → harvest `JSESSIONID`/`tr_refresh`/`tr_device` cookies), persisted session, plus a refresh/keepalive mechanism (`GET /api/v1/auth/web/session`).
  - `portfolio`: positions + cash via authenticated WebSocket (`compactPortfolioByType` + `cash`), enriched with names and live prices (`instrument` + `ticker` fan-out).
  - `rates`: quotes for arbitrary ISINs (`instrument` + `ticker`).
  - `details`: instrument detail view (`instrument`, `stockDetails`, `ticker`, `performance`, `instrumentSuitability`).
  - Demo/mock mode (`--mock` / `TR_CLI_MOCK=1`) serving bundled fixtures so every command is exercisable without touching the real account.
  - 429 `TOO_MANY_REQUESTS` handled with a clear cooldown message (parses `nextAttemptTimestamp`); login never auto-retries.
- No secrets in git: credentials and session files live in `~/.tr-cli/` (0600) and are gitignored; PIN via interactive prompt or env var.
- Change docs capture the recorded wire shapes (headers, cookie names, response fields) observed during the real-account spike, for the future tr-pebble bridge.

## Capabilities

### New Capabilities
- `auth`: v2 push-approval web login, persisted session cookies, session refresh/keepalive, and rate-limit (429) handling with cooldown messaging.
- `portfolio`: portfolio positions, cash balances, and enriched position valuation (names + live prices) over the authenticated WebSocket.
- `rates`: quote lookup for arbitrary ISINs (last/ask price + instrument metadata).
- `details`: instrument detail lookup (company data, performance, suitability, news).
- `mock-mode`: offline demo/mock transport with bundled fixture data so the full CLI surface works without network or a real account.

### Modified Capabilities
- None (greenfield repo).

## Impact

- New code under `src/tr_cli/` (auth, HTTP session, WS protocol client, mock transport, Typer CLI, rendering).
- Dependencies: `typer`, `requests`, `websockets` (+ dev: `pytest`, `pytest-asyncio`, `ruff`).
- No existing code affected; repository is currently only an openspec scaffold.
- External: only the unofficial `api.traderepublic.com` endpoints (research-based, no official API); real-account usage is strictly rate-limited and opt-in.
