"""High-level data operations: account, portfolio, rates, details.

All data flows over the authenticated WebSocket using one-shot subscribe/
collect batches (see ws.collect). Wire topics used:
  compactPortfolioByType {secAccNo} -> positions grouped by category
  cash                                   -> cash balances
  instrument   {id: isin}               -> instrument metadata
  ticker      {id: "ISIN.EXCHANGE"}     -> live quote
  stockDetails {id: isin}               -> company snapshot
  performance {id: "ISIN.EXCHANGE"}     -> performance history
  instrumentSuitability {instrumentId}  -> suitability flags
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .errors import NeedsLogin, ProtocolError
from .protocol import (
    PORTFOLIO_CHART_ENDPOINT,
    RESOLUTION_1D_MS,
    TIMELINE_REST_TRANSACTIONS,
    TRADE_AGGREGATE_HISTORY_TOPIC,
    year_start_millis,
)
from .transport import Transport

HISTORY_DEFAULT_DAYS = (
    90  # kept for compat; --days now limits the window (default: full)
)
HISTORY_MAX_DAYS = 730
HISTORY_NOTE = "official portfolio chart (positions only); cash reconstructed from transaction history"

BOND_PATTERN = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|May|June|July|"
    r"August|September|October|November|December|Januar|Februar|März|April|Mai|Juni|Juli|August|"
    r"September|Oktober|November|Dezember)\.?\s+20\d{2}",
    re.IGNORECASE,
)

DEFAULT_EXCHANGE = "LSX"


@dataclass
class Account:
    securities_account_number: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Position:
    instrument_id: str
    name: str = ""
    net_size: str = "0"
    average_buy_in: str = "0"
    price: str | None = None
    ask: str | None = None
    # YTD (2026): base price = first daily bar open of the year (first trading
    # day — NOT midnight Jan 1; honest approximation), gain = (price − base) × netSize.
    ytd_base_price: str | None = None
    ytd_gain: Decimal | None = None
    ytd_pct: Decimal | None = None

    @property
    def net_value(self) -> Decimal | None:
        if self.price is None:
            return None
        return (Decimal(self.price) * Decimal(self.net_size)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    @property
    def buy_cost(self) -> Decimal:
        return (Decimal(self.average_buy_in) * Decimal(self.net_size)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )


@dataclass
class CashItem:
    """One cash balance entry (real wire shape: `{accountNumber, currencyId, amount}`).

    `amount` is the *available* cash for that currency — verified live
    (2026-08-15) to equal the `availableCashForPayout` topic and the TR app's
    "available cash" display.
    """

    currency_id: str
    amount: str
    account_number: str | None = None


@dataclass
class CashBalance:
    """Aggregated cash balances, one item per currency (per cash account).

    `total` sums all item amounts. Note: the TR app's "portfolio value" does
    NOT include cash — see `Portfolio.total_value`.
    """

    items: list[CashItem] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        total = Decimal(0)
        for item in self.items:
            try:
                total += Decimal(item.amount)
            except (ValueError, TypeError, ArithmeticError):
                continue
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def amount_for(self, currency_id: str) -> Decimal | None:
        """Sum of all item amounts for a currency (aggregates per currencyId)."""
        total = Decimal(0)
        found = False
        for item in self.items:
            if item.currency_id == currency_id:
                try:
                    total += Decimal(item.amount)
                    found = True
                except (ValueError, TypeError, ArithmeticError):
                    continue
        return total if found else None


@dataclass
class Portfolio:
    positions: list[Position] = field(default_factory=list)
    cash: CashBalance = field(default_factory=CashBalance)

    @property
    def ytd_total(self) -> Decimal | None:
        """Sum of per-position YTD gains where a series was available (null when none)."""
        gains = [p.ytd_gain for p in self.positions if p.ytd_gain is not None]
        if not gains:
            return None
        return sum(gains, Decimal(0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def total_value(self) -> Decimal:
        total = Decimal(0)
        for pos in self.positions:
            if pos.net_value is not None:
                total += pos.net_value
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class Quote:
    instrument_id: str
    name: str = ""
    price: str | None = None
    ask: str | None = None


def account(transport: Transport) -> Account:
    """GET /api/v2/auth/account. Raises NeedsLogin on 401 (session dead)."""
    resp = transport.request("GET", "/api/v2/auth/account")
    if resp.status_code == 401:
        raise NeedsLogin(
            "Session expired or rejected (401). Run `tr-cli login` to re-authenticate."
        )
    if not resp.ok:
        raise ProtocolError(
            f"GET /api/v2/auth/account failed: HTTP {resp.status_code} {resp.body[:200]!r}"
        )
    j = resp.json()
    return Account(
        securities_account_number=j.get("securitiesAccountNumber"),
        raw=j,
    )


def _normalize_positions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten compactPortfolioByType (categories[].positions, key 'isin')
    and legacy compactPortfolio ({positions: [...], key 'instrumentId'})."""
    positions: list[dict[str, Any]] = []
    for cat in payload.get("categories", []) or []:
        for pos in cat.get("positions", []) or []:
            if "isin" in pos and "instrumentId" not in pos:
                pos["instrumentId"] = pos["isin"]
            positions.append(pos)
    if not positions:
        positions = list(payload.get("positions", []) or [])
    return positions


def _parse_cash(payload: Any) -> CashBalance:
    """Parse the real `cash` topic payload.

    Real wire shape (verified 2026-08-15): an ARRAY of per-account/per-currency
    balances `[{accountNumber, currencyId, amount}, ...]`. Defensively also
    accepts a single dict with `amount` (and the legacy `{total, available}`
    object, mapped to one item with an unknown currency) so a shape change does
    not silently zero out the cash section.
    """
    entries: list[Any]
    if isinstance(payload, list):
        entries = payload
    elif isinstance(payload, dict):
        if payload.get("amount") is not None:
            entries = [payload]
        elif payload.get("total") is not None or payload.get("available") is not None:
            entries = [
                {
                    "currencyId": "?",
                    "amount": payload.get("total") or payload.get("available") or "0",
                }
            ]
        else:
            return CashBalance()
    else:
        return CashBalance()

    items: list[CashItem] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("amount") is None:
            continue
        items.append(
            CashItem(
                currency_id=str(entry.get("currencyId") or "?"),
                amount=str(entry["amount"]),
                account_number=str(entry["accountNumber"])
                if entry.get("accountNumber") is not None
                else None,
            )
        )
    return CashBalance(items=items)


def _enrich(transport: Transport, items: list[dict[str, Any]], timeout: float) -> None:
    """Populate name + exchangeIds via `instrument`, then price/ask via `ticker`."""
    if not items:
        return
    # Phase A: instrument metadata.
    subs = [
        (idx, {"type": "instrument", "id": it["instrumentId"]})
        for idx, it in enumerate(items)
    ]
    instruments = transport.ws_collect(subs, timeout=timeout)
    for idx, resp in instruments.items():
        if isinstance(resp, dict):
            items[idx]["name"] = (
                resp.get("shortName")
                or resp.get("name")
                or items[idx].get("instrumentId")
            )
            ex = resp.get("exchangeIds") or []
            items[idx]["exchangeIds"] = ex
    # Phase B: tickers (first exchange; LSX fallback like pytr's details view).
    ticker_subs = []
    for idx, it in enumerate(items):
        ex = (it.get("exchangeIds") or [None])[0] or DEFAULT_EXCHANGE
        ticker_subs.append(
            (idx, {"type": "ticker", "id": f"{it['instrumentId']}.{ex}"})
        )
    tickers = transport.ws_collect(ticker_subs, timeout=timeout)
    for idx, resp in tickers.items():
        if isinstance(resp, dict):
            last = resp.get("last") or {}
            if isinstance(last, dict) and last.get("price") is not None:
                price = str(last["price"])
                if BOND_PATTERN.search(str(items[idx].get("name", ""))):
                    price = str(Decimal(price) / 100)
                items[idx]["price"] = price
            ask = resp.get("ask") or {}
            if isinstance(ask, dict) and ask.get("price") is not None:
                items[idx]["ask"] = str(ask["price"])


def _fetch_ytd(
    transport: Transport, items: list[dict[str, Any]], *, timeout: float = 6.0
) -> None:
    """Populate items[idx]['ytdBasePrice'] from tradeAggregateHistory daily bars.

    The year-start base price is the FIRST bar's `open` — the first trading
    day of the year (markets are closed Jan 1), not midnight Jan 1. This is
    the best available YTD base; positions without a series keep null.
    """
    from datetime import datetime

    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    subs: list[tuple[int, dict[str, Any]]] = []
    for idx, it in enumerate(items):
        ex = (it.get("exchangeIds") or [None])[0]
        if not ex:
            continue
        subs.append(
            (
                idx,
                {
                    "type": TRADE_AGGREGATE_HISTORY_TOPIC,
                    "isin": it["instrumentId"],
                    "exchangeId": ex,
                    "resolution": RESOLUTION_1D_MS,
                    "from": year_start_millis(),
                    "until": now_ms,
                },
            )
        )
    if not subs:
        return
    series = transport.ws_collect(subs, timeout=timeout)
    for idx, resp in series.items():
        if not isinstance(resp, dict):
            continue
        aggregates = resp.get("aggregates") or []
        if not aggregates or not isinstance(aggregates[0], dict):
            continue
        base = aggregates[0].get("open")
        if base is None:
            continue
        items[idx]["ytdBasePrice"] = str(base)


def portfolio(transport: Transport, *, timeout: float = 5.0) -> Portfolio:
    """Portfolio positions + cash.

    `totalValue` semantics: sum of position net values ONLY — cash is NOT
    included. This matches the TR app's "portfolio value" (verified against
    Daniel's same-day numbers: app 180050.00 vs positions-sum 180000.00 with
    ~EUR 50 quote drift; positions + cash would have been 181234.56, which
    does not match the app).
    """
    acct = account(transport)
    sec_acc_no = acct.securities_account_number
    if not sec_acc_no:
        raise ProtocolError(
            "Account response did not include securitiesAccountNumber; cannot fetch portfolio."
        )
    collected = transport.ws_collect(
        [
            ("portfolio", {"type": "compactPortfolioByType", "secAccNo": sec_acc_no}),
            ("cash", {"type": "cash"}),
        ],
        timeout=timeout,
    )
    raw_positions = (
        _normalize_positions(collected.get("portfolio", {}))
        if isinstance(collected.get("portfolio"), dict)
        else []
    )
    cash = _parse_cash(collected.get("cash"))

    positions = [
        Position(
            instrument_id=pos["instrumentId"],
            net_size=str(pos.get("netSize") or "0"),
            average_buy_in=str(pos.get("averageBuyIn") or "0"),
        )
        for pos in raw_positions
    ]
    items = [{"instrumentId": p.instrument_id} for p in positions]
    _enrich(transport, items, timeout=timeout)
    _fetch_ytd(transport, items, timeout=timeout)
    for pos, item in zip(positions, items):
        pos.name = item.get("name", "")
        pos.price = item.get("price")
        pos.ask = item.get("ask")
        base = item.get("ytdBasePrice")
        if base is not None and pos.price is not None:
            try:
                base_dec = Decimal(base)
                pos.ytd_base_price = str(base_dec)
                pos.ytd_gain = (
                    (Decimal(pos.price) - base_dec) * Decimal(pos.net_size)
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if base_dec != 0:
                    pos.ytd_pct = (
                        (Decimal(pos.price) - base_dec) / base_dec * 100
                    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            except (ValueError, TypeError, ArithmeticError):
                pass
    return Portfolio(positions=positions, cash=cash)


def rates(
    transport: Transport, isins: list[str], *, timeout: float = 5.0
) -> list[Quote]:
    if not isins:
        return []
    items = [{"instrumentId": isin} for isin in isins]
    _enrich(transport, items, timeout=timeout)
    return [
        Quote(
            instrument_id=it["instrumentId"],
            name=it.get("name", ""),
            price=it.get("price"),
            ask=it.get("ask"),
        )
        for it in items
    ]


def details(transport: Transport, isin: str, *, timeout: float = 6.0) -> dict[str, Any]:
    """Fetch the detail topics for one ISIN. Returns {topic: payload} for
    every topic that answered (partial results allowed)."""
    subs = [
        ("instrument", {"type": "instrument", "id": isin}),
        ("stockDetails", {"type": "stockDetails", "id": isin}),
        ("ticker", {"type": "ticker", "id": f"{isin}.{DEFAULT_EXCHANGE}"}),
        ("performance", {"type": "performance", "id": f"{isin}.{DEFAULT_EXCHANGE}"}),
        (
            "instrumentSuitability",
            {"type": "instrumentSuitability", "instrumentId": isin},
        ),
        ("neonNews", {"type": "neonNews", "isin": isin}),
    ]
    return dict(transport.ws_collect(subs, timeout=timeout))


@dataclass
class HistoryPoint:
    """One day of the historical curve. `total` = positions (official chart
    netValue); `cash` = reconstructed cash at the start of that day (UTC);
    `deposits` = cumulative net external money flow (deposits + withdrawals +
    card) at the start of that day (UTC); `invested` = cumulative net cash
    invested into the portfolio (orders: standing plans, trades, saveback)."""

    date: str  # YYYY-MM-DD (UTC)
    total: Decimal
    cash: str | None
    deposits: str | None = None
    invested: str | None = None
    interest: str | None = None  # cumulative interest income (signed)


@dataclass
class HistoryResult:
    series: list[HistoryPoint]
    start_date: str | None
    end_date: str | None
    cash: str | None  # current cash (the anchor of the reconstruction)
    note: str
    approximate: bool = False
    snapshots_merged: int = 0
    cash_events: int = 0
    deposits_events: int = 0  # money-flow events feeding the deposits curve
    invested_events: int = 0  # order events feeding the invested curve
    interest_events: int = 0  # interest events feeding the interest curve
    cash_residual: Decimal | None = None  # current_cash - sum(all events)


def _fetch_portfolio_chart(
    transport: Transport, sec_acc_no: str, range_: str, *, timeout: float = 8.0
) -> list[tuple[str, Decimal]]:
    """GET the official portfolio chart; returns [(date, netValue)] (UTC days)."""
    resp = transport.request(
        "GET",
        PORTFOLIO_CHART_ENDPOINT,
        params={"secAccNo": sec_acc_no, "range": range_, "currency": "EUR"},
    )
    if resp.status_code != 200:
        raise ProtocolError(
            f"portfolio-chart {range_} failed: HTTP {resp.status_code} {resp.body[:200]!r}"
        )
    try:
        j = resp.json()
    except Exception as e:
        raise ProtocolError(
            f"portfolio-chart {range_} body not JSON: {resp.body[:120]!r}"
        ) from e
    points = j.get("points") if isinstance(j, dict) else j
    if not isinstance(points, list):
        raise ProtocolError(
            f"portfolio-chart {range_}: unexpected payload {str(j)[:120]!r}"
        )

    out: list[tuple[str, Decimal]] = []
    for pt in points:
        if (
            not isinstance(pt, dict)
            or pt.get("timestamp") is None
            or pt.get("netValue") is None
        ):
            continue
        try:
            day = (
                datetime.fromtimestamp(int(pt["timestamp"]) / 1000, tz=UTC)
                .date()
                .isoformat()
            )
            net = Decimal(str(pt["netValue"]))
        except (ValueError, TypeError, ArithmeticError):
            continue
        out.append((day, net))
    return out


def _fetch_cash_events(
    transport: Transport, *, timeout: float = 8.0, max_pages: int = 50
) -> list[tuple[str, Decimal, str]]:
    """REST timeline transactions (paginated via olderThan cursor); returns
    [(date, signed amount, bucket)] for CASH-MOVING event types only. The
    bucket (timeline.classify of eventType) lets callers separate external
    money flow (deposits/withdrawals/card) from internal events
    (orders/dividends/interest)."""
    from . import timeline as timeline_mod

    events: list[tuple[str, Decimal, str]] = []
    cursor: str | None = None
    for _page in range(max_pages):
        params: dict[str, Any] = {"limit": 100}
        if cursor:
            params["olderThan"] = cursor
        resp = transport.request("GET", TIMELINE_REST_TRANSACTIONS, params=params)
        if resp.status_code != 200:
            raise ProtocolError(
                f"timeline transactions failed: HTTP {resp.status_code} {resp.body[:200]!r}"
            )
        try:
            j = resp.json()
        except Exception as e:
            raise ProtocolError(
                f"timeline transactions body not JSON: {resp.body[:120]!r}"
            ) from e
        items = j.get("items") if isinstance(j, dict) else []
        for it in items:
            if not isinstance(it, dict):
                continue
            # The REST transactions feed is the cash-movement feed: every item
            # carries a signed amount. Any amount-bearing event counts (verified
            # live: all 335 items had amounts; no informational duplicates).
            amt = it.get("amount")
            if not isinstance(amt, dict) or amt.get("value") is None:
                continue
            ts = it.get("timestamp") or ""
            try:
                day = timeline_mod.parse_timestamp(ts).date().isoformat()
            except (ValueError, TypeError):
                continue
            try:
                events.append(
                    (
                        day,
                        Decimal(str(amt["value"])),
                        timeline_mod.classify(it.get("eventType")),
                    )
                )
            except (ValueError, TypeError, ArithmeticError):
                continue
        cursors = j.get("cursors") if isinstance(j, dict) else {}
        cursor = cursors.get("after") if isinstance(cursors, dict) else None
        if not cursor or not items:
            break
    return events


def _reconstruct_cash(
    events: list[tuple[str, Decimal, str]],
    current_cash: Decimal,
    series_dates: list[str] | None = None,
) -> tuple[dict[str, Decimal], int, Decimal]:
    """cash(date) = current_cash - S + P(<date) where S = sum of all amounts and
    P(<date) = sum of amounts with event date BEFORE date. Returns
    ({date: cash for requested dates}, total_S, event_count)."""
    from collections import defaultdict

    by_date: dict[str, Decimal] = defaultdict(Decimal)
    for day, amt, _bucket in events:
        by_date[day] += amt
    event_dates = sorted(by_date)
    prefix: list[Decimal] = []
    acc = Decimal(0)
    for d in event_dates:
        prefix.append(acc)
        acc += by_date[d]
    total_s = acc
    prefix.append(total_s)  # sentinel for bisect_left == len(event_dates)

    import bisect

    def cash_at(day: str) -> Decimal:
        idx = bisect.bisect_left(event_dates, day)
        return current_cash - total_s + prefix[idx]

    target = series_dates if series_dates is not None else event_dates
    return {d: cash_at(d) for d in target}, total_s, len(events)


def _invested_curve(
    events: list[tuple[str, Decimal, str]],
    series_dates: list[str] | None = None,
) -> tuple[dict[str, Decimal], int]:
    """Cumulative net cash invested into the portfolio per date: standing
    orders, one-off trades and saveback (bucket 'orders', buys are negative
    amounts so the curve grows; sells reduce it). Excludes external money
    flow (deposits/withdrawals/card) — those are cash-account movements, not
    invested capital. Mirror of the cash walk semantics: invested(date) =
    cumulative orders strictly BEFORE date."""
    from collections import defaultdict
    import bisect

    flow: dict[str, Decimal] = defaultdict(Decimal)
    count = 0
    for day, amt, bucket in events:
        if bucket == "orders":
            flow[day] -= amt  # buys negative -> invested grows
            count += 1
    dates = sorted(flow)
    prefix: list[Decimal] = []
    acc = Decimal(0)
    for d in dates:
        prefix.append(acc)
        acc += flow[d]
    prefix.append(acc)

    def inv_at(day: str) -> Decimal:
        idx = bisect.bisect_left(dates, day)
        return prefix[idx]

    target = series_dates if series_dates is not None else dates
    return {d: inv_at(d) for d in target}, count


def _interest_curve(
    events: list[tuple[str, Decimal, str]],
    series_dates: list[str] | None = None,
) -> tuple[dict[str, Decimal], int]:
    """Cumulative interest income per date (bucket 'interest', signed — loan
    interest would be negative). Cash gains = interest only; reinvested
    dividends belong to portfolio gains. Mirrors the cash-walk semantics:
    interest(date) = cumulative interest strictly BEFORE date."""
    from collections import defaultdict
    import bisect

    flow: dict[str, Decimal] = defaultdict(Decimal)
    count = 0
    for day, amt, bucket in events:
        if bucket == "interest":
            flow[day] += amt
            count += 1
    dates = sorted(flow)
    prefix: list[Decimal] = []
    acc = Decimal(0)
    for d in dates:
        prefix.append(acc)
        acc += flow[d]
    prefix.append(acc)

    def int_at(day: str) -> Decimal:
        idx = bisect.bisect_left(dates, day)
        return prefix[idx]

    target = series_dates if series_dates is not None else dates
    return {d: int_at(d) for d in target}, count


MONEY_FLOW_BUCKETS = ("deposits", "withdrawals", "card")


def _deposit_curve(
    events: list[tuple[str, Decimal, str]],
    series_dates: list[str] | None = None,
) -> tuple[dict[str, Decimal], int]:
    """Cumulative net external money flow per date — deposits + withdrawals +
    card spending ONLY. Orders/dividends/interest are internal or income and
    belong to gains, not deposits. Mirrors the cash-walk semantics:
    deposits(date) = cumulative flow strictly BEFORE date. Returns
    ({date: cumulative deposits}, money_flow_event_count)."""
    from collections import defaultdict
    import bisect

    flow: dict[str, Decimal] = defaultdict(Decimal)
    count = 0
    for day, amt, bucket in events:
        if bucket in MONEY_FLOW_BUCKETS:
            flow[day] += amt
            count += 1
    dates = sorted(flow)
    prefix: list[Decimal] = []
    acc = Decimal(0)
    for d in dates:
        prefix.append(acc)
        acc += flow[d]
    prefix.append(acc)  # sentinel for bisect_left == len(dates)

    def dep_at(day: str) -> Decimal:
        idx = bisect.bisect_left(dates, day)
        return prefix[idx]

    target = series_dates if series_dates is not None else dates
    return {d: dep_at(d) for d in target}, count


def _load_snapshots(snapshots: Any) -> list[tuple[str, Decimal]]:
    """Normalize an optional snapshot list [{date, total}] -> [(date, total)]."""
    out: list[tuple[str, Decimal]] = []
    if not snapshots:
        return out
    for snap in snapshots:
        if not isinstance(snap, dict) or not snap.get("date"):
            continue
        try:
            out.append((str(snap["date"]), Decimal(str(snap["total"]))))
        except (ValueError, TypeError, ArithmeticError):
            continue
    return out


def history(
    transport: Transport,
    *,
    since: str | None = None,
    days: int | None = None,
    timeout: float = 8.0,
    snapshots: list[dict[str, Any]] | None = None,
) -> HistoryResult:
    """Historical portfolio value + reconstructed cash.

    PRIMARY SOURCE: the official portfolio-chart REST endpoint
    (api-gateway/portfolio-chart/v2/chart?range=1y daily + range=max coarser).
    Merge order: max (coarser) -> 1y (daily wins on overlap) -> optional local
    snapshots (highest priority). The curve starts at the first NON-ZERO
    netValue point. total = positions only (netValue — matches portfolio
    totalValue and the TR app). approximate = False: the chart reflects real
    historical holdings (no retroactive-quantity approximation).

    CASH: reconstructed from the REST timeline transactions feed — cash(date) =
    current_cash - sum(signed amounts of cash-moving events with timestamp
    > date at 00:00 UTC), constant between events, ~0 before the first event.
    """
    if days is not None and (days < 1 or days > HISTORY_MAX_DAYS):
        from .errors import UsageError

        raise UsageError(f"--days must be between 1 and {HISTORY_MAX_DAYS}.")
    if since is not None:
        from datetime import date as _date

        try:
            _date.fromisoformat(since)
        except ValueError:
            from .errors import UsageError

            raise UsageError(f"Invalid --since {since!r}; expected YYYY-MM-DD.")

    acct = account(transport)
    sec_acc_no = acct.securities_account_number
    if not sec_acc_no:
        raise ProtocolError("Account response did not include securitiesAccountNumber.")

    # --- 1) portfolio chart (1y daily + max coarser) -------------------------
    chart_1y = _fetch_portfolio_chart(transport, sec_acc_no, "1y", timeout=timeout)
    chart_max = _fetch_portfolio_chart(transport, sec_acc_no, "max", timeout=timeout)
    y1_start = chart_1y[0][0] if chart_1y else None

    merged: dict[str, Decimal] = {}
    for day, net in chart_max:
        merged[day] = net
    for day, net in chart_1y:
        merged[day] = net  # daily wins over coarser on overlap

    snapshot_pairs = _load_snapshots(snapshots)
    for day, total in snapshot_pairs:
        merged[day] = total  # collector snapshots override everything

    # drop leading zero-netValue points (account held nothing before first buy)
    dates = sorted(merged)
    first_nonzero = next((i for i, d in enumerate(dates) if merged[d] != 0), None)
    if first_nonzero is None:
        return HistoryResult(
            series=[],
            start_date=None,
            end_date=None,
            cash=None,
            note=HISTORY_NOTE,
            approximate=False,
        )
    dates = dates[first_nonzero:]

    # --- 2) current cash + reconstruction -------------------------------------
    cash_resp = transport.ws_collect([("cash", {"type": "cash"})], timeout=timeout)
    cash = _parse_cash(cash_resp.get("cash"))
    current_cash = cash.total if cash.items else Decimal(0)
    cash_str = str(current_cash) if cash.items else None

    events = _fetch_cash_events(transport, timeout=timeout)
    cash_map, total_s, n_events = _reconstruct_cash(
        events, current_cash, series_dates=dates
    )
    dep_map, n_dep_events = _deposit_curve(events, series_dates=dates)
    inv_map, n_inv_events = _invested_curve(events, series_dates=dates)
    int_map, n_int_events = _interest_curve(events, series_dates=dates)

    # --- 3) series --------------------------------------------------------------
    series: list[HistoryPoint] = []
    negative_days: list[str] = []
    for day in dates:
        day_total = merged[day].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        cash_at = cash_map.get(day)
        if cash_at is None:
            # day outside any event dates: use prefix walk via the map's nearest
            cash_at = current_cash - total_s
        cash_at_q = cash_at.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if cash_at_q < 0:
            negative_days.append(day)
        dep_at_q = (dep_map.get(day) or Decimal(0)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        inv_at_q = (inv_map.get(day) or Decimal(0)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        int_at_q = (int_map.get(day) or Decimal(0)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        series.append(
            HistoryPoint(
                date=day,
                total=day_total,
                cash=str(cash_at_q) if cash_str is not None else None,
                deposits=str(dep_at_q) if cash_str is not None else None,
                invested=str(inv_at_q) if cash_str is not None else None,
                interest=str(int_at_q) if cash_str is not None else None,
            )
        )

    # --- 4) filters + note -------------------------------------------------------
    if since is not None:
        series = [p for p in series if p.date >= since]
    if days is not None and series:
        cutoff = (
            datetime.fromisoformat(series[-1].date).date() - timedelta(days=days)
        ).isoformat()
        series = [p for p in series if p.date >= cutoff]

    residual = current_cash - total_s
    note = HISTORY_NOTE
    granularity = f"daily since {y1_start}" if y1_start else "coarser only"
    note += f"; {granularity} (coarser before)"
    note += f"; cash reconstructed from {n_events} events"
    note += f"; deposits curve from {n_dep_events} money-flow events"
    note += f"; invested curve from {n_inv_events} order events"
    note += f"; interest curve from {n_int_events} interest events"
    if residual != 0:
        note += f"; cash residual (current - sum events): {residual:.2f}"
    if snapshot_pairs:
        note += f"; snapshots merged: {len(snapshot_pairs)}"
    if negative_days:
        note += (
            f"; WARNING cash went negative on {len(negative_days)} day(s) "
            f"starting {negative_days[0]} (classification may be incomplete)"
        )

    return HistoryResult(
        series=series,
        start_date=series[0].date if series else None,
        end_date=series[-1].date if series else None,
        cash=cash_str,
        note=note,
        approximate=False,
        snapshots_merged=len(snapshot_pairs),
        cash_events=n_events,
        deposits_events=n_dep_events,
        invested_events=n_inv_events,
        interest_events=n_int_events,
        cash_residual=residual,
    )
