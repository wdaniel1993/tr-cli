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
from collections.abc import Hashable
from dataclasses import dataclass, field
from datetime import UTC, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .errors import NeedsLogin, ProtocolError
from .protocol import (
    RESOLUTION_1D_MS,
    TRADE_AGGREGATE_HISTORY_TOPIC,
    year_start_millis,
)
from .transport import Transport

HISTORY_DEFAULT_DAYS = 90  # fallback when no account-start signal is detectable
HISTORY_MAX_DAYS = 730
HISTORY_NOTE = (
    "current quantities applied retroactively; cash reported separately (constant)"
)

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
    """One day of the backfilled curve. `total` includes the constant cash."""

    date: str  # YYYY-MM-DD (UTC)
    total: Decimal
    cash: str | None


@dataclass
class HistoryResult:
    series: list[HistoryPoint]
    start_date: str | None
    end_date: str | None
    cash: str | None
    note: str
    positions_covered: int
    positions_without_series: list[str] = field(default_factory=list)


def history(
    transport: Transport,
    *,
    since: str | None = None,
    days: int = HISTORY_DEFAULT_DAYS,
    timeout: float = 8.0,
) -> HistoryResult:
    """Backfill a daily portfolio value curve from current holdings.

    Start-date resolution (in priority order):
      1. `since` (explicit YYYY-MM-DD override);
      2. auto-detected account start from the timeline (CUSTOMER_CREATED /
         SECURITIES_ACCOUNT_CREATED / VERIFICATION_TRANSFER_ACCEPTED / earliest
         deposit);
      3. fallback: now − `days` (default 90) when no signal is found.

    ONE WS connection, three sequential rounds (portfolio+cash → instruments →
    daily bars). Per date: total = Σ (qty × close) over positions
    (forward-filled) — POSITIONS ONLY, matching `portfolio.totalValue`
    semantics; the current cash is reported separately as a constant per-point
    `cash` field and is NEVER added into `total`. Positions whose series fetch
    fails are excluded from the whole curve.
    """
    if days < 1 or days > HISTORY_MAX_DAYS:
        from .errors import UsageError

        raise UsageError(f"--days must be between 1 and {HISTORY_MAX_DAYS}.")

    from datetime import date as _date
    from datetime import datetime

    start_label: str
    start_date: _date
    if since is not None:
        try:
            start_date = _date.fromisoformat(since)
        except ValueError:
            from .errors import UsageError

            raise UsageError(f"Invalid --since {since!r}; expected YYYY-MM-DD.")
        start_label = f"explicit --since {since}"
    else:
        from . import timeline as timeline_mod

        detected = timeline_mod.detect_account_start(transport, timeout=timeout)
        if detected is not None:
            dstr, source = detected
            start_date = _date.fromisoformat(dstr)
            if source == "CUSTOMER_CREATED":
                start_label = f"account created {dstr}"
            elif source == "SECURITIES_ACCOUNT_CREATED":
                start_label = f"securities account created {dstr}"
            elif source == "VERIFICATION_TRANSFER_ACCEPTED":
                start_label = f"first verification transfer {dstr}"
            else:
                start_label = f"earliest deposit {dstr}"
        else:
            from datetime import datetime as _dt
            from datetime import timedelta as _td

            start_date = (_dt.now(UTC) - _td(days=days)).date()
            start_label = f"no creation events found; last {days} days"

    start_ms = int(
        datetime(
            start_date.year, start_date.month, start_date.day, tzinfo=UTC
        ).timestamp()
        * 1000
    )
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    from_millis = start_ms
    acct = account(transport)
    sec_acc_no = acct.securities_account_number
    if not sec_acc_no:
        raise ProtocolError("Account response did not include securitiesAccountNumber.")

    # ONE connection: round 0 = portfolio+cash, round 1 = instruments,
    # round 2 = daily series (built from the earlier rounds' replies).
    def build_round(
        r_index: int, so_far: dict[int, dict[Hashable, Any]]
    ) -> list[tuple[Hashable, dict[str, Any]]] | None:
        if r_index == 0:
            return [
                (
                    "portfolio",
                    {"type": "compactPortfolioByType", "secAccNo": sec_acc_no},
                ),
                ("cash", {"type": "cash"}),
            ]
        if r_index == 1:
            pf = so_far.get(0, {}).get("portfolio", {})
            raw = _normalize_positions(pf) if isinstance(pf, dict) else []
            return [
                (idx, {"type": "instrument", "id": pos["instrumentId"]})
                for idx, pos in enumerate(raw)
            ]
        if r_index == 2:
            raw = _normalize_positions(so_far.get(0, {}).get("portfolio", {}))
            instruments = so_far.get(1, {})
            batch = []
            for idx, pos in enumerate(raw):
                ex = (instruments.get(idx) or {}).get("exchangeIds") or []
                ex = ex[0] if ex else None
                if not ex:
                    continue
                batch.append(
                    (
                        idx,
                        {
                            "type": TRADE_AGGREGATE_HISTORY_TOPIC,
                            "isin": pos["instrumentId"],
                            "exchangeId": ex,
                            "resolution": RESOLUTION_1D_MS,
                            "from": from_millis,
                            "until": now_ms,
                        },
                    )
                )
            return batch
        return None

    rounds_out = transport.ws_rounds(build_round, timeout=timeout)

    portfolio_payload = rounds_out.get(0, {}).get("portfolio", {})
    raw_positions = (
        _normalize_positions(portfolio_payload)
        if isinstance(portfolio_payload, dict)
        else []
    )
    cash = _parse_cash(rounds_out.get(0, {}).get("cash"))
    cash_total = str(cash.total) if cash.items else None

    positions: list[dict[str, Any]] = [
        {"instrumentId": pos["instrumentId"], "netSize": str(pos.get("netSize") or "0")}
        for pos in raw_positions
    ]
    if not positions:
        return HistoryResult(
            series=[],
            start_date=None,
            end_date=None,
            cash=cash_total,
            note=HISTORY_NOTE,
            positions_covered=0,
        )

    instruments = rounds_out.get(1, {})
    for idx, resp in instruments.items():
        if isinstance(resp, dict):
            positions[idx]["name"] = resp.get("shortName") or resp.get("name")
            ex = resp.get("exchangeIds") or []
            positions[idx]["exchangeIds"] = ex

    covered: set[str] = set()
    bars_by_position: dict[int, dict[str, Decimal]] = {}
    series_map = rounds_out.get(2, {})
    for idx, resp in series_map.items():
        if not isinstance(resp, dict):
            continue
        aggregates = resp.get("aggregates") or []
        dates: dict[str, Decimal] = {}
        for bar in aggregates:
            if (
                not isinstance(bar, dict)
                or bar.get("time") is None
                or bar.get("close") is None
            ):
                continue
            try:
                day = (
                    datetime.fromtimestamp(int(bar["time"]) / 1000, tz=UTC)
                    .date()
                    .isoformat()
                )
                dates[day] = Decimal(str(bar["close"]))
            except (ValueError, TypeError, ArithmeticError):
                continue
        if dates:
            bars_by_position[idx] = dates
            covered.add(positions[idx]["instrumentId"])

    missing = [
        it["instrumentId"] for it in positions if it["instrumentId"] not in covered
    ]
    if not bars_by_position:
        return HistoryResult(
            series=[],
            start_date=None,
            end_date=None,
            cash=cash_total,
            note=HISTORY_NOTE,
            positions_covered=0,
            positions_without_series=missing,
        )

    # Series range: start at the LATEST first-bar date across positions so
    # every series day covers ALL positions; dates = union of bar dates
    # (trading days), filtered to the range.
    first_dates = [min(dates) for dates in bars_by_position.values()]
    series_start = max(first_dates)
    all_dates = sorted(
        d
        for d in {d for dates in bars_by_position.values() for d in dates}
        if d >= series_start
    )

    # Forward-fill per position: carry the last known close forward across
    # gaps (thin trading / different market calendars). Nothing is filled
    # BEFORE a position's first bar, so starting at `series_start` every day
    # has a value for every position — no artificial drops from missing bars.
    filled: dict[int, dict[str, Decimal]] = {}
    for idx, dates in bars_by_position.items():
        last_close: Decimal | None = None
        fwd: dict[str, Decimal] = {}
        for day in all_dates:
            close = dates.get(day)
            if close is not None:
                last_close = close
            if last_close is not None:
                fwd[day] = last_close
        filled[idx] = fwd

    series: list[HistoryPoint] = []
    for day in all_dates:
        day_total = Decimal(0)
        for idx, fwd in filled.items():
            close = fwd.get(day)
            if close is None:
                continue  # before this position's first bar (should not happen >= series_start)
            day_total += close * Decimal(positions[idx]["netSize"])
        day_total = day_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        # total = positions only (cash reported separately, never added).
        series.append(HistoryPoint(date=day, total=day_total, cash=cash_total))

    note = f"{HISTORY_NOTE}; start: {start_label}"
    if missing:
        note += f"; positions without series: {', '.join(missing)}"
    if series:
        # Server returns at most ~200 daily bars; detect truncation vs the
        # requested start (allow a few days for the first trading day).
        try:
            first_bar = datetime.fromisoformat(series[0].date).date()
            if first_bar > start_date + timedelta(days=3):
                note += f"; series truncated server-side (oldest bar {series[0].date})"
        except (ValueError, TypeError):
            pass
        # Forward-fill policy documentation (start = max first bar date).
        note += (
            f"; start = max first bar date ({series_start}) -> every day covers "
            f"{len(bars_by_position)}/{len(bars_by_position)} positions (forward-filled)"
        )
    return HistoryResult(
        series=series,
        start_date=series[0].date if series else None,
        end_date=series[-1].date if series else None,
        cash=cash_total,
        note=note,
        positions_covered=len(covered),
        positions_without_series=missing,
    )
