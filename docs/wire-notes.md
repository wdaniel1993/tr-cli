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
| `tr_external_id` | external user id (observed on real login, 2026-08-15) |
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
| `cash` | — | **array** `[{accountNumber, currencyId, amount}]` (one entry per cash account; research-derived `{total, available}` object is NOT what the server sends) |
| `instrument` | `{"id": ISIN}` | name/shortName/typeId/currency/exchangeIds/exchanges/tags |
| `ticker` | `{"id": "ISIN.EXCHANGE"}` | `{last:{price,…}, ask:{price}, bid:{price}}` — bond prices ÷ 100 |
| `stockDetails` | `{"id": ISIN}` | company profile, dividend, market data |
| `performance` | `{"id": "ISIN.EXCHANGE"}` | **aggregate price points only** (verified live 2026-08-15): `{high_1d, low_1d, price_5d, price_1m, price_3m, price_6m, price_1y, price_3y, price_5y, high_52w, low_52w}` — NOT a `{perf:[{timestamp,price}],range}` series (research-derived shape was wrong for protocol v31; `range` arg is ignored) |
| `instrumentSuitability` | `{"instrumentId": ISIN}` | suitability flags |
| `neonNews` | `{"isin": ISIN}` | `[{headline, createdAt}]` |

### Other known topics (out of scope for now)

`portfolio`, `portfolioStatus`, `watchlist`, `availableCashForPayout`,
`portfolioAggregateHistory`, `timelineTransactions`, `timelineActivityLog`
(trades/dividends — on ActivityLog, not Transactions), `timelineDetailV2`,
`searchTags`, `watchlists`, `priceForOrder`, `homeInstrumentExchange`,
`savingsPlans`, `compactSavingsPlans`, `pendingTimelineEventCash`.

**History topics status (verified live 2026-08-15):**
- `portfolioAggregateHistory` → **DEAD on protocol v31**: `BAD_SUBSCRIPTION_TYPE
  "Unknown topic type: portfolioAggregateHistory.31"` (the app's portfolio
  chart must use a newer/renamed topic — not yet identified).
- `performance` → aggregate points only (see table above); **no daily series**.
- `timelineActivityLog` → **WORKS**: `{items: [{id, timestamp, title, subtitle,
  action, trailing, eventType, ...}], cursors}` — real event history
  (dividends, transfers, reports). Best available "history" topic.
→ The API serves point-in-time state + aggregate milestones + an event log,
  but NO continuous per-day series. A local snapshot store (like tr-cli's
  `~/.tr-cli/history/` used by the daily watcher) is therefore the correct
  way to build day-over-day position/value history.

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

### Real-account spike — 2026-08-15 ✅ (authenticated, redacted)

All shapes below recorded with `scripts/capture-wire.py` (values masked;
re-runnable with a logged-in session). Spacing: 1 login + 2 HTTP GETs +
4 WS connections over ~10 minutes. **No 429 observed.**

**Login (tokenless v2 push) — WORKS from this IP**
- `POST /api/v2/auth/web/login {phoneNumber, pin}` with the standard
  `login_headers()` (NO `x-aws-waf-token`) → push to app → poll → `CONFIRMED`.
- 6 cookies landed: `JSESSIONID`, `tr_refresh`, `tr_device`, `tr_session`,
  `tr_claims`, `tr_external_id` → persisted to `~/.tr-cli/cookies.txt`.
- Device fingerprint: the 10-field `x-tr-device-info` (stableDeviceId +
  browser/version/os/osVersion/timezone/timezoneOffset/screen/languages/cores)
  was accepted as-is. No extra required fields discovered.

**HTTP (cookie auth)**
- `GET /api/v2/auth/account` → 200. Full profile structure confirmed
  (redacted): `phoneNumber`, `jurisdiction`, `name{first,last}`,
  `email{address,verified}`, `postalAddress{...}`, `birthdate`,
  `mainTaxResidency{tin,countryCode}`, `cashAccount{iban,bic,bankName}`,
  `referenceAccountList[{iban,bic,bankName,logoUrl}]`,
  `securitiesAccountNumber` (string — needed for `compactPortfolioByType`),
  `experience{stock,fund,derivative,crypto,bond}`, `personId`, …
  Response headers: plain (no `set-cookie`, no `x-tr-*` custom headers on 200).
- `GET /api/v1/auth/web/session` → 200, **no cookie rotation observed** on a
  fresh session (research-derived "rotates JSESSIONID + tr_session" did not
  fire; likely only near TTL expiry).

**WebSocket (cookie header auth — confirmed working)**
- `connect 31 {"locale":"en","platformId":"webtrading","platformVersion":"chrome - 94.0.4606","clientId":"app.traderepublic.com","clientVersion":"5582"}` → reply `connected` ✓
- `cash` → **array** `[{accountNumber, currencyId, amount}]`
- `compactPortfolioByType {"secAccNo": …}` → `{categories:[{categoryType, positions:[{isin, averageBuyIn, netSize, virtualSize, status, instrumentType, name, derivativeInfo|null, bondInfo|null, imageId}]}]}`
- `instrument {"id": ISIN}` → `{active, exchangeIds[], exchanges[{slug, active, nameAtExchange, symbolAtExchange, band, firstSeen, lastSeen, fractionalTrading{minOrderSize,stepSize,orderAmountLimitCurrency,minOrderAmount,…}, dmaTrading{…}, settlementRoute}]}`
- `ticker` → `{bid,ask,last,pre,open: {time, price, size}}` (strings for price/size)
- **`ticker` id constraint (new finding):** `ISIN.EXCHANGE` must use a slug the
  instrument actually trades on — the first *active* `exchanges[].slug` works
  (`DE000BASF111.LSX` ✓). Observed failures for `DE000BASF111`:
  - `.XETR` → `E` frame `{"errors":[{"errorCode":"FORBIDDEN",…,"meta":{"source":"MAPPER"}}]}` (XETR was in `exchangeIds` but rejected)
  - `.lsx` (lowercase) → `JSON_PARSE_ERROR` … `meta.source: MAPPER`
  - bare ISIN → `JSON_PARSE_ERROR`
  → `rates`/`details`/enrichment must resolve the slug from the instrument
  response, not hardcode an exchange. tr-cli's `DEFAULT_EXCHANGE=LSX` +
  `exchangeIds[0]` pattern is correct.
- `stockDetails`, `performance`, `instrumentSuitability`, `neonNews` all
  answered on a real account via `tr-cli --json details <ISIN>` (6/6 topics).

**CLI end-to-end on the real account (all verified 2026-08-15)**
- `tr-cli --json rates DE000BASF111` → `{ok, quotes:[{instrumentId, name, price, ask}]}`
- `tr-cli --json details DE000BASF111` → 6/6 topics
- `tr-cli --json portfolio` → `{ok, positions[8] (enriched names + live prices), cash, totalValue}`

### Cash vs availableCashForPayout — 2026-08-15 (authenticated probe, redacted)

- One WS connection, two subscriptions: `cash` and `availableCashForPayout`.
- Both returned the **identical** payload:
  `[{"accountNumber": "<redacted>", "currencyId": "EUR", "amount": 1234.56}]`
- The `cash` amount therefore IS the app's "available cash" (Daniel's app showed
  EUR 1234.56 on the same day). `availableCashForPayout` is a confirmed-identical
  alternative; tr-cli uses `cash` alone.
- `accountNumber` is a 10-digit string (the cash account id) — redacted here;
  tr-cli's CLI JSON output omits it.
- Session refresh on an older session DID rotate `JSESSIONID` + `tr_session`
  (the spike record above noted no rotation on a fresh session — rotation
  happens near TTL expiry).

### Web bundle v2.2632.29 — timeline & chart findings (2026-08-15, passive GETs)

App version served: `2.2632.29` (index.js + HTML meta). TR_APP_VERSION default bumped to match.

**Timeline — two streams, REST + WS both exist:**
- REST (web app): `GET /api/v2/timeline/transactions`, `/activity-log`,
  `/inbox/open`, `/inbox/closed`, `/actions`, `/search`, `/detail/showcase`.
  Feed = inbox/open + inbox/closed merged, deduped by id; paginate with
  `cursor`/`olderThan` (values are base64 keysets; `cursors.after` for next page).
- WS (used by tr-cli): `timelineTransactions` = money events with
  `amount {currency, value, fractionDigits}` (BANK_TRANSACTION_INCOMING/
  OUTGOING, INTEREST_PAYOUT, TRADING_SAVINGSPLAN_EXECUTED,
  SSP_CORPORATE_ACTION_DIVIDEND_EQUIVALENT, ...); `timelineActivityLog` =
  reports/corporate actions/docs (EX_POST_COST_REPORT_CREATED,
  TAX_YEAR_END_REPORT_CREATED, DOCUMENTS_ACCEPTED, ORDER_REJECTED,
  SSP_CORPORATE_ACTION_INFORMATIVE/ACTIVITY, ...). Subscribe args:
  `{type, limit}` and `{type, limit, after: <cursors.after>}` for pages.
- **The app's feed merges both** — that is why activityLog alone missed the
  dividend/transfer/interest events (they live in timelineTransactions).

**Chart series (portfolioAggregateHistory replacement):**
- Portfolio chart is REST: `GET api-gateway/portfolio-chart/v2/chart
  ?secAccNo=<secAccNo>&range=<1d|5d|1m|3m|6m|1y|3y|5y|max>&currency=EUR
  [&instrumentCategories=...]` -> `{points:[{timestamp, netValue,
  performance{absoluteValue, relativeValue}}], openingTime, expectedClosingTime}`.
- Instrument chart (stocks/ETFs) is WS `tradeAggregateHistory` (protobuf-backed
  service `TradeAggregateHistory.V2`, but the WS mapper accepts JSON):
  `{"type":"tradeAggregateHistory","isin":"...","exchangeId":"<active slug>",
  "resolution":86400000|604800000,"from":<ms>,"until":<ms>}`
  -> `{aggregates:[{time, open, close, high, low, volume}]}`.
  ⚠️ Field names are top-level `isin/exchangeId/resolution/from/until` — the
  protobuf names (`instrument_id`, `resolution_millis`, `from_millis`) are
  REJECTED by the mapper (JSON_PARSE_ERROR), verified by probe.
- Crypto chart: WS `aggregateHistoryLightV2`
  `{"type":"aggregateHistoryLightV2","isin":"...","exchangeId":"...",
  "unit":"EUR","range":"1y","resolution":86400000}`.
- YTD basis: first daily bar `open` of the year (first trading day — Jan 1 is a
  market holiday). `performance` topic's `price_6m`/`price_1y` are NOT Jan-1 prices.
- `technical.deltaOpenPricePctYTD` exists in the pro-trading heatmap config but is
  not part of the consumer account data path.

**Other:** `YieldToMaturity` REST endpoint for bonds:
`api-gateway/quotes-api/v1/instruments/{isin}.{exchange}/ytm/aggregateHistory?range=...`.

### timeline + YTD — live verification (2026-08-15, spaced)

- `tr-cli --json timeline --days 60` → 24 events, 1 page: 3 deposits (+600, +5000,
  +600), 1 withdrawal (−2000), 2 interest (+7.63, +0.85), 3 dividends
  (SSP_CORPORATE_ACTION_DIVIDEND_EQUIVALENT, incl. −184.40 on 2026-08-13 —
  matches Daniel's app feed), 12 savings-plan buys, 1 corporate action,
  2 documents. Classification + amounts verified.
- `tr-cli --json portfolio` → `tradeAggregateHistory` daily bars WORK with the
  bundle-derived payload (`isin`, `exchangeId`, `resolution: 86400000`, `from`,
  `until` at top level). All 8 positions got ytd (base = first 2026 bar open,
  e.g. EM IMI 38.912 → 47.116 = +21.08%); ytdTotal +23128.51. Cash EUR 3552.53
  and totalValue 182961.06 unchanged.
- WS budget this session: 7 connections total (3 research probes + 4 verification),
  all spaced, zero 429s.

### history command — full-series verification (2026-08-15, Eve + this session)

- `tradeAggregateHistory` returns the FULL daily-bar series in one reply:
  `{aggregates:[{time(ms), open, high, low, close, volume}], expectedClosingTime,
  resolution, lastAggregateEndTime, unit, sourceCurrency}` — 159 bars YTD for
  IE00B4L5Y983 @ LSX; first open == the YTD base (111.115), last close ==
  current price.
- tr-cli `history` fetches positions+cash → instruments → series in ONE WS
  connection (sequential rounds via `ws.rounds` builder), then computes per-day
  Σ(qty×close) over positions with a bar + constant current cash.
- Missing-bar policy: a position without a bar on a date is excluded that day;
  a position whose series fails is excluded from the whole curve (noted).
- `approximate: true` because current quantities are applied retroactively and
  cash is constant — exact curves require the local snapshot store (Eve's watcher).

### history — start-date auto-detection (steer 2026-08-15)

- Start = earliest of timeline signals: CUSTOMER_CREATED /
  SECURITIES_ACCOUNT_CREATED / VERIFICATION_TRANSFER_ACCEPTED (activityLog) or
  the earliest deposit-bucket event (timelineTransactions). `--since YYYY-MM-DD`
  overrides; `--days` (default 90) is the fallback when no signal is found.
- Server-side daily-bar cap measured: 180d window → full 126 bars; 365d and
  730d windows BOTH → 202 bars starting 2025-10-28 (last bar = last trading
  day). The cap is ~200 daily bars regardless of window; the CLI detects
  truncation (first bar > requested start + 3d) and notes it.
- The last close of each series equals the current price within quote drift
  (verified side-by-side vs ticker last, all EUR, LSX).

### history — live verification (2026-08-15, spaced)

- `tr-cli --json history` (auto-detect): start = `securities account created
  2023-10-07` (detected from timelineActivityLog); series = 202 points
  2025-10-28 → 2026-08-14 (server ~200-bar cap → truncation noted). Curve:
  160.4k (Oct-25) → 186.0k (Jun-26) → 169.7k (Aug-14), cash 3552.53 constant.
- Last-day gap vs today's snapshot explained by the missing-bar policy:
  Stoxx 600 (LU0908500753) last LSX bar is 08-13 (thin trading) → excluded on
  08-14 → "last point covers 7/8 positions". Per-position last closes equal
  ticker prices within <0.3% (checked 8/8 ISINs, all unit EUR @ LSX).
- End-to-end: 2 WS connections per `tr-cli history` run (1 detection + 1
  rounds), 0 HTTP beyond account; zero 429s this session (5 WS total incl.
  probes, all spaced).
