## Context

Greenfield repo (`wdaniel1993/tr-cli`), currently only an openspec scaffold. Daniel wants a small Trade Republic CLI: `login`, `portfolio` (positions/cash), `rates` (quotes), `details`. The companion watch app (tr-pebble) is paused because PebbleKit JS cannot read `Set-Cookie`; this CLI must therefore also record exact wire shapes (endpoint responses, cookie names, `x-tr-device-info` requirements) for a future watch-app bridge. The home IP was recently rate-limited (`TOO_MANY_REQUESTS`) by watch-app dev testing, so real login attempts are high-risk and must be mock-first, spaced, and never auto-retried.

Protocol knowledge comes from five unofficial implementations (pytr-org/pytr, Erim32/Trade-Republic, NightOwl07/trade-republic-api, cdamken/tr-api, Sawangg/autotr), cross-checked as research (see session notes). No official API exists.

## Goals / Non-Goals

**Goals:**
- Small, installable Python CLI (`uv` + Typer) with `login`, `portfolio`, `rates`, `details`, `session` commands.
- v2 push-approval login with persisted session + refresh; correct, friendly 429 cooldown handling.
- `--mock` mode with bundled fixtures so the full surface works offline — used for all tests and demos.
- A thin, own HTTP layer so raw request/response shapes can be logged and documented for the watch-app bridge.
- No secrets in git (session/credentials under `~/.tr-cli/`, 0600, gitignored).

**Non-Goals:**
- Order placement, savings plans, alarms, document download, transactions export (pytr covers those; Daniel explicitly wants small scope).
- A GUI, daemon, or server.
- Full emulation of the AWS WAF challenge (v2 login works without it, per pytr); we only support injecting a token via env var as an escape hatch.
- Guaranteeing TR won't change the protocol (unofficial API — accepted risk).

## Decisions

### D1: Build a thin client; do NOT depend on pytr
We implement our own protocol client (`requests` for HTTP, `websockets` for WS) instead of reusing pytr as a dependency.
- **Why**: (1) the CLI's mission includes recording exact endpoint responses, cookie shapes, and header requirements for the watch-app bridge — that requires owning the HTTP layer; (2) pytr drags in `curl_cffi` (compiled Rust), `certifi`, optional playwright, and its own argparse CLI — heavy for a small tool; (3) we need fine control over rate limiting and mock mode.
- **Alternatives considered**: pytr as dependency (rejected: heavy, opaque wire, awkward to mock); cdamken/tr-api (rejected: smaller/younger, cookie-import oriented, needs playwright for programmatic login).
- **Reuse instead**: protocol knowledge only. Delta decoding, topic names, header shapes are re-implemented from the documented protocol (~100 lines), all tested.

### D2: v2 push login without WAF token by default
`POST /api/v2/auth/web/login` + poll `GET /api/v2/auth/web/login/processes/{id}` with TR headers only (`x-tr-device-info`, `x-tr-app-version`, `x-tr-platform`, Chrome UA). pytr (most battle-tested) does exactly this and explicitly skips the WAF token on v2. cdamken/NightOwl07 use a WAF token (Playwright/puppeteer) — heavier and more bot-detection-prone.
- **Escape hatch**: `TR_WAF_TOKEN` env var; when set, the CLI sends it as `x-aws-waf-token` header + `aws-waf-token` cookie, matching cdamken. If TR starts rejecting tokenless v2 logins (405 empty body), the CLI reports the hint to obtain a token.
- Defaults mirror pytr: `x-tr-app-version: 2.2631.13`, `x-tr-platform: web-pro`, env-overridable (`TR_APP_VERSION`, `TR_PLATFORM`).

### D3: Session model
- Cookie jar (Netscape format) at `~/.tr-cli/cookies.txt` (0600), written atomically via temp file + rename.
- `JSESSIONID` + `tr_refresh` + `tr_device` are the required auth cookies; `tr_claims`/`aws-waf-token` stored when present.
- Session validity check: `GET /api/v2/auth/account` (returns `securitiesAccountNumber` needed for the portfolio topic too).
- Refresh: `GET /api/v1/auth/web/session` (pytr's keepalive trick, ~290s cadence documented; `session refresh` command).
- Device id: stable 64-hex `stableDeviceId` persisted at `~/.tr-cli/device_id` so re-logins reuse identity (cdamken pattern).

### D4: WebSocket protocol client
- `wss://api.traderepublic.com`, cookies in the upgrade `Cookie:` header.
- `connect 31 {"locale":..., "platformId":"webtrading", "platformVersion":"chrome - 94.0.4606", "clientId":"app.traderepublic.com", "clientVersion":"5582"}` (pytr's cookie-authed handshake).
- `sub <id> {"type": ...}`; frames `<id> A|D|C|E <payload>`; delta decode: split on `\t`, `+` → append url-decoded, `-N` → skip N, `=N` → copy N chars from previous payload (pytr algorithm, re-implemented + unit-tested against fixture deltas).
- Fan-out pattern for enrichment: subscribe N topics, collect responses keyed by subscription id, unsubscribe, timeout ~5s per batch.

### D5: Transport abstraction for mock mode
- `Transport` protocol with `request(...)` (HTTP) and `ws_request(...)`/`ws_collect(...)` (one-shot subscribe→collect).
- `RealTransport` (requests + websockets) and `MockTransport` (bundled fixture JSON, deterministic, includes a 429-mode).
- CLI resolves transport: `--mock` flag or `TR_CLI_MOCK=1` wins; global Typer option. Tests run against `MockTransport`; wire-protocol units (delta decode, cookie harvesting, header building) run against synthetic HTTP/WS fixtures via `responses`-style fakes (hand-rolled, no extra dep).

### D6: CLI surface (Typer)
```
tr-cli [--mock] [--json] login                 # v2 push login
tr-cli [--mock] session status                 # local check only
tr-cli [--mock] session refresh                # GET /api/v1/auth/web/session
tr-cli [--mock] portfolio                      # positions + cash + totals
tr-cli [--mock] rates <ISIN...>                # quotes
tr-cli [--mock] details <ISIN>                 # instrument detail view
```
- PIN via `TR_PIN` env or `getpass` prompt; phone via `TR_PHONE` env or prompt. No credentials file (avoids plaintext PIN on disk; Daniel's constraint is no secrets in git — home-dir 0600 session file only).
- `--json` output for scriptability; human table otherwise. Exit codes: 0 ok, 1 generic, 2 usage, 3 needs-login, 4 rate-limited, 5 login-failed.
- All data commands auto-refresh the session if `_web_request`-style keepalive window expired (pytr pattern), else 401 → "run tr-cli login".

### D7: Rendering
Simple stdlib formatting (no `rich`): fixed-width columns, totals row. Bond prices divided by 100 when instrument name matches a bond pattern (pytr behavior). Values as strings from TR (they arrive as strings); compute netValue as Decimal.

## Risks / Trade-offs

- [Unofficial API can change / break at any time] → All endpoints/headers are env-overridable and centralized in one `protocol.py` module; wire shapes recorded in change docs during the real-account spike.
- [WAF may start blocking tokenless v2 logins] → `TR_WAF_TOKEN` escape hatch + clear 405 hint message (no silent retries).
- [Real login bursts re-trigger IP/account rate limit] → Mock-first development; real login attempts are deliberate, spaced, and only on Daniel's explicit account; 429 handled with cooldown message and zero auto-retry; login timeout 120s with visible countdown.
- [WS delta format undocumented] → Delta decoder unit-tested against fixtures derived from the reference implementations; any decode failure surfaces as a clear protocol error.
- [Session expiry mid-run] → 401 on account check → "session expired, run tr-cli login"; refresh keepalive before expiry window.
- [No secrets in git] → All secrets under `~/.tr-cli/` outside the repo; `.gitignore` also covers `.env`, local `.tr-cli/` and cookies as defense-in-depth.

## Migration Plan

- Greenfield: nothing to migrate. Steps: scaffold uv project → implement protocol/auth → mock transport + fixtures → commands → tests → real-account spike (rate-limited, spaced) → record wire shapes in `docs/wire-notes.md` (committed) → archive change.

## Open Questions

- Exact `x-tr-device-info` tolerances (which fields are mandatory) — resolved empirically during the real-account spike; defaults follow pytr.
- Whether TR requires the WAF token for v2 from this IP — unknown until the spike; tokenless works per pytr.
