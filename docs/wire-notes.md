# Trade Republic wire notes (unofficial)

Reference for tr-cli's protocol layer, derived from cross-checking five
unofficial implementations: **pytr-org/pytr**, **Erim32/Trade-Republic**,
**NightOwl07/trade-republic-api**, **cdamken/tr-api**, **Sawangg/autotr**.

> Status: **research-derived**. Fields marked ⚠️ are to be confirmed/recorded
> during the real-account spike (rate-limited, spaced). This file doubles as
> the recording vehicle for the future **tr-pebble** watch-app bridge: the
> exact response/cookie shapes observed on a real account get appended below.

---

## HTTP auth

### v2 push-approval login (current flow)

1. `POST https://api.traderepublic.com/api/v2/auth/web/login`
   - Body: `{"phoneNumber": "+49…", "pin": "1234"}`
   - Required headers:
     - `x-tr-device-info`: base64 of JSON `{stableDeviceId, browser, browserVersion, os, osVersion, timezone, timezoneOffset, screen, preferredLanguages, numberOfCores}` — `stableDeviceId` is a 64-hex string; TR ties the login process to it.
     - `x-tr-app-version`: web app build (`2.2631.13` per pytr; `15.x.y` per cdamken/NightOwl07 — env-overridable via `TR_APP_VERSION`)
     - `x-tr-platform`: `web-pro` (pytr) / `web` (cdamken, NightOwl07) — `TR_PLATFORM`
     - Chrome `User-Agent`, `Accept`, `Accept-Language`, `Content-Type: application/json`, `Origin`/`Referer: https://app.traderepublic.com/`
   - Optional: `x-aws-waf-token` header + `aws-waf-token` cookie (`TR_WAF_TOKEN`). **pytr skips the WAF token entirely on v2** — tokenless is the default here.
   - Response 200: `{"processId": "…", "countdownInSeconds": 120, "twoFactorMethod": "APP_APPROVAL", …}`
   - TR pushes an **approval prompt to the mobile app** (no code is typed).
2. `GET /api/v2/auth/web/login/processes/{processId}` (same headers)
   - Poll every ~2s; `status` `PENDING` → keep waiting; `CONFIRMED`/`COMPLETED` → done.
   - **Session cookies arrive via `Set-Cookie` during this round-trip.**
   - Timeout ~120s (server enforces `expiresAt`).

### Errors (login)

- `429 TOO_MANY_REQUESTS` → `{"errors":[{"errorCode":"TOO_MANY_REQUESTS","meta":{"nextAttemptInSeconds":…,"nextAttemptTimestamp":"…"}}]}` — **never auto-retry**; show cooldown.
- `PIN_INVALID` / `NUMBER_INVALID` / `USER_NOT_FOUND` (4xx, or occasionally 200-with-`errors`) → bad credentials.
- `405` with empty body (server: awselb) → WAF blocked the request; obtain/refresh `TR_WAF_TOKEN`.

### Session keepalive / refresh

- `GET /api/v1/auth/web/session` (cookie auth) → rotates `JSESSIONID` + `tr_session`; call ~every 290s (pytr's cadence, just under the ~5 min server TTL).
- `GET /api/v2/auth/account` (cookie auth) → validates the session (401 = dead) and returns `securitiesAccountNumber` (needed for the portfolio topic) plus user/profile info.

### Cookie inventory (all `api.traderepublic.com`, HttpOnly)

| Cookie | Purpose |
|---|---|
| `JSESSIONID` | session id — most important |
| `tr_refresh` | refresh token for `/auth/web/session` |
| `tr_device` | device fingerprint TR uses to recognise repeat logins |
| `tr_session` | session token (NightOwl07 harvests this as the primary token) |
| `tr_claims` | JWT-ish payload with sessionId + jurisdiction (app domain) |
| `aws-waf-token` | WAF bypass token (app domain; only when token mode used) |

tr-cli persists `{JSESSIONID, tr_refresh, tr_device, tr_session, tr_claims, …}`
to `~/.tr-cli/cookies.txt` (0600).

---

## WebSocket (wss://api.traderepublic.com)

- Handshake carries the session cookies in the `Cookie:` header (no separate auth message).
- Connect frame: `connect 31 {"locale":"en","platformId":"webtrading","platformVersion":"chrome - 94.0.4606","clientId":"app.traderepublic.com","clientVersion":"5582"}` → reply `connected`
- Subscribe: `sub <id> {"type": "<topic>", …}` (ids start at 1 per connection)
- Frames: `<id> A <json>` (full) · `<id> D <delta>` (patch) · `<id> C` (close) · `<id> E <payload>` (error)
- **Delta format**: tab-separated tokens; `+…` append url-decoded, `-N` skip N chars of previous payload, `=N` copy N chars of previous payload at index i. Result replaces previous payload.

### Topics used by tr-cli

| Topic | Args | Returns |
|---|---|---|
| `compactPortfolioByType` | `{"secAccNo": …}` | `{categories:[{type, positions:[{isin, netSize, averageBuyIn, …}]}]}` — legacy `compactPortfolio` uses `positions:[{instrumentId, …}]` |
| `cash` | — | `{total, available, currency, …}` |
| `instrument` | `{"id": ISIN}` | name/shortName/typeId/currency/exchangeIds/exchanges/tags |
| `ticker` | `{"id": "ISIN.EXCHANGE"}` | `{last:{price,…}, ask:{price}, bid:{price}}` — bond prices ÷ 100 |
| `stockDetails` | `{"id": ISIN}` | company profile, dividend, market data |
| `performance` | `{"id": "ISIN.EXCHANGE"}` | `{perf:[{timestamp, price}], range}` |
| `instrumentSuitability` | `{"instrumentId": ISIN}` | suitability flags |
| `neonNews` | `{"isin": ISIN}` | `[{headline, createdAt}]` |

### Other known topics (out of scope for now)

`portfolio`, `portfolioStatus`, `watchlist`, `availableCashForPayout`,
`portfolioAggregateHistory`, `timelineTransactions`, `timelineActivityLog`
(trades/dividends — on ActivityLog, not Transactions), `timelineDetailV2`,
`searchTags`, `watchlists`, `priceForOrder`, `homeInstrumentExchange`,
`savingsPlans`, `compactSavingsPlans`, `pendingTimelineEventCash`.

Close code `3003 (registered)` = another session claimed the same registration.

---

## Real-account spike record (append-only)

### Passive probe — 2026-08-15 (no auth, no account)

- `GET https://app.traderepublic.com/login` with Chrome UA → `200`, 5414 bytes, no IP block on plain page loads.
- AWS WAF challenge confirmed: `challenge.js` served from
  `https://8dc6d8e337ce.330bb79d.eu-central-1.token.awswaf.com/<id>/<id>/challenge.js`
  (matches pytr's `*.token.awswaf.com` host pin). The v2 API flow does not need
  a token from it (pytr runs tokenless; tr-pebble session memory confirms WAF is
  not enforced on the API), but `TR_WAF_TOKEN` remains the escape hatch.

### Pending — requires Daniel to approve a push in the TR mobile app

Record here, verbatim-ish:
- exact login response bodies (redacted) + cookie names/shapes,
- which `x-tr-device-info` fields TR actually requires,
- whether tokenless v2 login works from this IP,
- portfolio/cash/ticker response shapes observed on a real account,
- any 429 occurrences + their `meta` payloads.

Run (from this repo, one attempt, no auto-retry):

```bash
TR_PHONE=+49... TR_PIN=... uv run tr-cli login   # approve the push on your phone
uv run tr-cli portfolio
uv run tr-cli rates <ISIN>
uv run tr-cli details <ISIN>
```
