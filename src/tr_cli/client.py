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
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .errors import NeedsLogin, ProtocolError
from .transport import Transport

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
class CashBalance:
    total: str = "0"
    available: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Portfolio:
    positions: list[Position] = field(default_factory=list)
    cash: CashBalance = field(default_factory=CashBalance)

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
    if not isinstance(payload, dict):
        return CashBalance()
    total = payload.get("total") or payload.get("available") or "0"
    return CashBalance(
        total=str(total),
        available=str(payload.get("available"))
        if payload.get("available") is not None
        else None,
        raw=payload,
    )


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


def portfolio(transport: Transport, *, timeout: float = 5.0) -> Portfolio:
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
    for pos, item in zip(positions, items):
        pos.name = item.get("name", "")
        pos.price = item.get("price")
        pos.ask = item.get("ask")
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
