## Context

tr-cli v0.1.1 serves login/portfolio/rates/details. Daniel's daily report needs timeline events, deposits-vs-capital-gains, and YTD. Research (web bundle app.traderepublic.com v2.2632.29 + live WS probes, all 2026-08-15):

- **Timeline is two streams.** The web app merges REST `GET /api/v2/timeline/inbox/open` + `/inbox/closed`; the WS topics `timelineTransactions` + `timelineActivityLog` expose the same data over the socket. Live probe: `timelineTransactions` holds the money events (`amount: {currency, value, fractionDigits}`, signed: +incoming/−outgoing/−buy/−dividend-equivalent), `timelineActivityLog` holds reports/corporate actions/account events (no amounts). Eve's earlier top-30 activityLog probe lacked financial events because they live in the *other* topic — puzzle solved.
- **Paginate with `after` cursor** (base64 keyset from `cursors.after`; pytr pattern `{"type": topic, "after": cursor}`), ~30 items/page.
- **YTD series.** The app's instrument chart subscribes `tradeAggregateHistory` with `{type, isin, exchangeId, resolution, from, until}` (resolution 86400000 = 1 day; 604800000 = 1 week) and maps the reply `{aggregates: [{time, open, close, high, low, volume}]}` to OHLC. (My first probe used the protobuf field names from the descriptor — the mapper rejects those; the bundle's builder is authoritative.)
- **Portfolio chart (portfolioAggregateHistory replacement)** is REST: `GET api-gateway/portfolio-chart/v2/chart?secAccNo=&range=1y&currency=EUR` → `{points: [{timestamp, netValue, performance{absoluteValue, relativeValue}}], openingTime, expectedClosingTime}`. Documented for Eve's chart side; not consumed by the CLI YTD (per-position series is authoritative for gains).
- App version in the wild: **2.2632.29** → bump `TR_APP_VERSION` default.

## Goals / Non-Goals

**Goals:**
- `tr-cli timeline [--days 90] [--bucket DEPOSITS]` — dual-topic, paginated, classified, amounts, JSON+human.
- `tr-cli portfolio` gains `ytd` per position + `ytdTotal` (backward compatible).
- Honest YTD basis: first daily bar open of 2026 (first trading day), never `price_6m` or invented precision.
- Version 0.2.0; tests (mock), ruff, openspec validate; commit+push.

**Non-Goals:**
- `timelineDetailV2` deep-dives per event (out of scope; `action.payload` gives the id for a future command).
- Order placement / exports.
- Consuming the REST portfolio-chart endpoint in the CLI (documented for Eve; the WS series is the gain source).

## Decisions

### D1: Timeline via WS dual-topic merge (not REST)
Use `timelineTransactions` + `timelineActivityLog` WS topics on one connection (like the app merges its two inbox streams). REST `/api/v2/timeline/*` endpoints exist but the WS path keeps tr-cli's transport/mock abstraction uniform and the topics are already verified live. Pagination: sequential rounds on one connection — subscribe both topics with `after: <cursor>` per topic, collect, repeat until cutoff/exhausted.

### D2: Classification table
Explicit `eventType` → bucket mapping with prefix rules, e.g.:
- deposits: `BANK_TRANSACTION_INCOMING`, `INCOMING_TRANSFER`, `PAYMENT_INBOUND`, `CASH_DEPOSIT*`, `DEPOSIT*`
- withdrawals: `BANK_TRANSACTION_OUTGOING`, `OUTGOING_TRANSFER`, `PAYMENT_OUTBOUND`, `WITHDRAWAL*`
- interest: `INTEREST_PAYOUT`, `INTEREST*`
- dividends: `*DIVIDEND*` (incl. `SSP_CORPORATE_ACTION_DIVIDEND_EQUIVALENT`)
- orders: `TRADING_SAVINGSPLAN_EXECUTED`, `*ORDER*`, `TRADE_INVOICE`, `SAVINGS_PLAN*`
- corporate_actions: `SSP_CORPORATE_ACTION*` (non-dividend), `*SPLIT`, `*SPINOFF`, `CORPORATE_ACTION*`
- documents: `*REPORT*`, `*STATEMENT*`, `DOCUMENTS*`, `TAX*`, `QUARTERLY*`, `ANNUAL*`, `LEGAL_DOCUMENTS`
- other: fallback
Sign convention documented: amount values are signed from the account's cash perspective (positive inflow, negative outflow/buy/reinvestment).

### D3: YTD from `tradeAggregateHistory` daily bars
Per position: one subscription `{type, isin, exchangeId, resolution: 86400000, from: <2026-01-01 00:00Z>, until: <now>}`; base price = first bar `open` (first trading day of 2026 — honest, documented); `ytdGain = (price_now − base) × netSize`; `ytdPct = ytdGain / (base × netSize)`. Portfolio `ytdTotal` = Σ position gains. Null-safe: no series → null fields; command succeeds. Alternative (documented, not implemented): portfolio-level YTD from the REST chart endpoint.

### D4: One WS connection for all portfolio enrichment
Portfolio already opens a connection for positions/cash and one for instrument/ticker enrichment. YTD adds a third `ws_collect` round (tradeAggregateHistory fan-out, one sub per position) — 3 connections per `tr-cli portfolio` run, matching the rate-limit discipline (~2-3 WS per invocation).

### D5: Mock parity
`MockTransport` gains scripted timeline (multi-page, all buckets, amounts) and `tradeAggregateHistory` (daily bars with a known 2026-01 base) fixtures so mock and real modes render identically.

## Risks / Trade-offs

- [YTD base = first trading day open, not Jan 1 midnight] → Documented explicitly in output metadata + README; do not claim precision.
- [Series topic payload could change] → Centralized in `protocol.py`; single live verification run scheduled; mock covers the logic.
- [timeline event-type vocabulary grows] → Unknown types fall to `other` and are still surfaced; mapping table is one place to extend.
- [Rate limits] → timeline pagination + YTD run on the existing per-invocation connection budget; verification uses exactly one additional WS connection, spaced.

## Migration Plan

1. protocol.py (app-version bump, timeline/ytd constants) → 2. ws.py pagination helper → 3. timeline module + classification → 4. YTD in client.portfolio → 5. mock fixtures → 6. cli + render → 7. tests → 8. docs (README, wire-notes) → 9. one live verification (timeline + YTD on real account) → 10. validate, sync specs, archive, commit + push.

## Open Questions

- None blocking. (Timeline dual-topic + cursor pagination verified live; YTD payload derived from the app bundle with high confidence; single live verification planned.)
