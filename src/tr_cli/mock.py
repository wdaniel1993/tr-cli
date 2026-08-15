"""MockTransport: offline demo/test transport with bundled fixtures.

Every shape mirrors the real TR protocol (see research): login process poll,
Set-Cookie harvesting, compactPortfolioByType categories, cash, instrument,
ticker (ISIN.EXCHANGE ids), stockDetails, performance, instrumentSuitability,
neonNews. Values are invented — no real account data.

Modes (set `mode` attribute or TR_CLI_MOCK_MODE env):
  "ok"              normal fixture flow
  "rate_limited"    login POST answers 429 TOO_MANY_REQUESTS with cooldown meta
  "pending_forever" login poll never approves -> ApprovalTimeout path
  "expired_session" account check answers 401 -> NeedsLogin path

`missing_tickers` (set of ISINs) makes the mock omit ticker responses so the
"missing price" path can be exercised.
"""

from __future__ import annotations

import os
import time
from collections.abc import Hashable
from datetime import UTC
from typing import Any

from .transport import HttpResponse, Transport

MOCK_PROCESS_ID = "mock-process-0001"

# --- fixtures ---------------------------------------------------------------

FIXTURE_ACCOUNT = {
    "id": "user-000000000000",
    "phoneNumber": "+491234567890",
    "securitiesAccountNumber": "1234567890123",
    "jurisdiction": "DE",
    "name": "Daniel Demo",
}

FIXTURE_INSTRUMENTS = {
    "US0378331005": {
        "id": "US0378331005",
        "name": "Apple Inc.",
        "shortName": "Apple",
        "typeId": "STOCK",
        "exchangeIds": ["LSX", "XNAS"],
        "currency": "USD",
        "tags": [{"type": "ISIN_COUNTRY", "name": "USA"}],
    },
    "DE0005140008": {
        "id": "DE0005140008",
        "name": "Deutsche Bank AG",
        "shortName": "Deutsche Bank",
        "typeId": "STOCK",
        "exchangeIds": ["LSX", "XETR"],
        "currency": "EUR",
        "tags": [{"type": "ISIN_COUNTRY", "name": "Germany"}],
    },
    "US88160R1014": {
        "id": "US88160R1014",
        "name": "Tesla Inc.",
        "shortName": "Tesla",
        "typeId": "STOCK",
        "exchangeIds": ["LSX", "XNAS"],
        "currency": "USD",
    },
}

FIXTURE_TICKERS = {
    "US0378331005.LSX": {
        "last": {"price": "232.05", "timestamp": int(time.time() * 1000)},
        "ask": {"price": "232.1"},
        "bid": {"price": "231.95"},
    },
    "DE0005140008.LSX": {
        "last": {"price": "16.44", "timestamp": int(time.time() * 1000)},
        "ask": {"price": "16.45"},
        "bid": {"price": "16.42"},
    },
    "US88160R1014.LSX": {
        "last": {"price": "248.5", "timestamp": int(time.time() * 1000)},
        "ask": {"price": "248.6"},
        "bid": {"price": "248.4"},
    },
}

FIXTURE_PORTFOLIO = {
    "categories": [
        {
            "type": "STOCK",
            "positions": [
                {"isin": "US0378331005", "netSize": "10", "averageBuyIn": "150.25"},
                {"isin": "DE0005140008", "netSize": "5", "averageBuyIn": "23.4"},
            ],
        }
    ]
}

# Real wire shape (verified 2026-08-15): array of per-account/per-currency balances.
FIXTURE_CASH = [
    {"accountNumber": "0000000001", "currencyId": "EUR", "amount": 1234.56},
    {"accountNumber": "0000000002", "currencyId": "USD", "amount": 1000.00},
]

FIXTURE_STOCK_DETAILS = {
    "US0378331005": {
        "company": {
            "name": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "marketCapitalization": 3500000000000,
            "employees": 161000,
            "foundingYear": 1976,
            "headquarters": "Cupertino, USA",
        },
        "isin": "US0378331005",
        "wkn": "865985",
    }
}

FIXTURE_PERFORMANCE = {
    "perf": [{"timestamp": int(time.time() * 1000) - 86400000, "price": "230.0"}],
    "range": "1Y",
}

FIXTURE_SUITABILITY = {
    "instrumentId": "US0378331005",
    "suitability": {"suitability": "SUITABLE"},
}

FIXTURE_NEWS = [
    {
        "headline": "Mock headline: Apple announces quarterly results",
        "createdAt": int(time.time() * 1000) - 3600000,
    }
]


# --- timeline fixtures (dynamic timestamps; pages of 5 to exercise pagination) ---


def _ts(days_ago: float, hour: int = 9) -> str:
    from datetime import datetime, timedelta

    dt = datetime.now(UTC) - timedelta(days=days_ago)
    dt = dt.replace(hour=hour % 24, minute=5, second=5, microsecond=920000)
    return dt.isoformat().replace("+00:00", "+0000")


def _timeline_tx_items() -> list[dict]:
    return [
        {
            "id": "tx-01",
            "timestamp": _ts(0.5),
            "title": "Core MSCI EM IMI USD (Acc)",
            "eventType": "SSP_CORPORATE_ACTION_DIVIDEND_EQUIVALENT",
            "amount": {"currency": "EUR", "value": -184.4, "fractionDigits": 2},
            "status": "EXECUTED",
        },
        {
            "id": "tx-02",
            "timestamp": _ts(2),
            "title": "Wallner  Daniel",
            "eventType": "BANK_TRANSACTION_INCOMING",
            "amount": {"currency": "EUR", "value": 600.0, "fractionDigits": 2},
            "status": "EXECUTED",
        },
        {
            "id": "tx-03",
            "timestamp": _ts(4),
            "title": "Interest",
            "eventType": "INTEREST_PAYOUT",
            "amount": {"currency": "EUR", "value": 7.63, "fractionDigits": 2},
            "status": "EXECUTED",
        },
        {
            "id": "tx-04",
            "timestamp": _ts(6),
            "title": "MSCI World USD (Acc)",
            "eventType": "TRADING_SAVINGSPLAN_EXECUTED",
            "amount": {"currency": "EUR", "value": -150.0, "fractionDigits": 2},
            "status": "EXECUTED",
        },
        {
            "id": "tx-05",
            "timestamp": _ts(8),
            "title": "Core S&P 500 USD (Acc)",
            "eventType": "TRADING_SAVINGSPLAN_EXECUTED",
            "amount": {"currency": "EUR", "value": -50.0, "fractionDigits": 2},
            "status": "EXECUTED",
        },
        # page 2 (older)
        {
            "id": "tx-06",
            "timestamp": _ts(10),
            "title": "Wallner  Daniel",
            "eventType": "BANK_TRANSACTION_OUTGOING",
            "amount": {"currency": "EUR", "value": -2000.0, "fractionDigits": 2},
            "status": "EXECUTED",
        },
        {
            "id": "tx-07",
            "timestamp": _ts(12),
            "title": "Daniel Wallner",
            "eventType": "BANK_TRANSACTION_INCOMING",
            "amount": {"currency": "EUR", "value": 5000.0, "fractionDigits": 2},
            "status": "EXECUTED",
        },
        {
            "id": "tx-08",
            "timestamp": _ts(14),
            "title": "Physical Gold USD (Acc)",
            "eventType": "TRADING_SAVINGSPLAN_EXECUTED",
            "amount": {"currency": "EUR", "value": -50.0, "fractionDigits": 2},
            "status": "EXECUTED",
        },
        {
            "id": "tx-09",
            "timestamp": _ts(40),
            "title": "Interest",
            "eventType": "INTEREST_PAYOUT",
            "amount": {"currency": "EUR", "value": 1.02, "fractionDigits": 2},
            "status": "EXECUTED",
        },
        {
            "id": "tx-10",
            "timestamp": _ts(120),
            "title": "Wallner  Daniel",
            "eventType": "BANK_TRANSACTION_INCOMING",
            "amount": {"currency": "EUR", "value": 300.0, "fractionDigits": 2},
            "status": "EXECUTED",
        },
    ]


def _timeline_log_items() -> list[dict]:
    return [
        {
            "id": "log-01",
            "timestamp": _ts(1),
            "title": "Ex-post cost report",
            "eventType": "EX_POST_COST_REPORT_CREATED",
            "icon": "logos/bank_traderepublic/v2",
        },
        {
            "id": "log-02",
            "timestamp": _ts(3),
            "title": "Annual Tax Report 2025",
            "eventType": "TAX_YEAR_END_REPORT_CREATED",
        },
        {
            "id": "log-03",
            "timestamp": _ts(5),
            "title": "FTSE All-World High Dividend Yield USD (Acc)",
            "eventType": "SSP_CORPORATE_ACTION_INFORMATIVE",
            "subtitle": "Change",
        },
        {
            "id": "log-04",
            "timestamp": _ts(7),
            "title": "Mystery event",
            "eventType": "SOME_UNKNOWN_EVENT_TYPE",
        },
        {
            "id": "log-05",
            "timestamp": _ts(9),
            "title": "Legal Documents",
            "subtitle": "Accepted",
            "eventType": "DOCUMENTS_ACCEPTED",
        },
        # page 2
        {
            "id": "log-06",
            "timestamp": _ts(11),
            "title": "Order rejected",
            "eventType": "ORDER_REJECTED",
        },
        {
            "id": "log-07",
            "timestamp": _ts(60),
            "title": "Quarterly Report",
            "eventType": "QUARTERLY_REPORT",
        },
        {
            "id": "log-08",
            "timestamp": _ts(150),
            "title": "Customer created",
            "eventType": "CUSTOMER_CREATED",
        },
    ]


TIMELINE_PAGE_SIZE = 5


# --- tradeAggregateHistory fixtures (daily bars from 2026-01-01) ---


def _ytd_bars(isin: str, base_price: float, last_price: float) -> dict:
    """Daily bars: first bar open = base_price (year start), last close = last_price."""
    n = 160  # trading days Jan->Aug
    step = (last_price - base_price) / max(n - 1, 1)
    aggregates = []
    from datetime import datetime, timedelta

    start = datetime(2026, 1, 2, tzinfo=UTC)
    for i in range(n):
        open_p = base_price + step * i
        close_p = open_p + step * 0.5
        day = start + timedelta(days=i)
        aggregates.append(
            {
                "time": int(day.timestamp() * 1000),
                "open": round(open_p, 4),
                "close": round(close_p, 4),
                "high": round(max(open_p, close_p) * 1.001, 4),
                "low": round(min(open_p, close_p) * 0.999, 4),
                "volume": 100,
            }
        )
    return {"aggregates": aggregates}


def _ytd_base_price(isin: str) -> float:
    return 100.0


def _history_bars(
    base_price: float,
    last_price: float,
    num_bars: int,
    skip_days: int = 0,
    gap_indices: set[int] | None = None,
) -> dict:
    """Daily bars ending today, linear from base_price to last_price.

    `skip_days` > 0 removes that many bars from the START of the series
    (simulates an instrument whose series begins later — missing-bar case).
    `gap_indices` removes bars in the MIDDLE (simulates thin trading).
    """
    from datetime import datetime, timedelta

    today = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    # Prices progress per VISIBLE bar (gaps don't cause price cliffs).
    visible = [
        i
        for i in range(num_bars)
        if i >= skip_days and not (gap_indices and i in gap_indices)
    ]
    n_visible = len(visible)
    step = (last_price - base_price) / max(n_visible - 1, 1)
    aggregates = []
    start = today - timedelta(days=num_bars - 1)
    for v_idx, i in enumerate(visible):
        day = start + timedelta(days=i)
        open_p = base_price + step * v_idx
        # close = next visible bar's open; the LAST close is exactly last_price.
        if v_idx == n_visible - 1:
            close_p = last_price
        else:
            close_p = base_price + step * (v_idx + 1)
        aggregates.append(
            {
                "time": int(day.timestamp() * 1000),
                "open": round(open_p, 4),
                "close": round(close_p, 4),
                "high": round(max(open_p, close_p) * 1.001, 4),
                "low": round(min(open_p, close_p) * 0.999, 4),
                "volume": 100,
            }
        )
    return {
        "aggregates": aggregates,
        "resolution": 86400000,
        "unit": "EUR",
        "sourceCurrency": "EUR",
        "expectedClosingTime": int(today.timestamp() * 1000),
    }


LOGIN_429_BODY = (
    '{"errors":[{"errorCode":"TOO_MANY_REQUESTS",'
    '"meta":{"nextAttemptInSeconds":600,"nextAttemptTimestamp":"2030-01-01T00:00:00.000Z"}}]}'
)


class MockTransport(Transport):
    def __init__(
        self, mode: str | None = None, initial_cookies: dict[str, str] | None = None
    ):
        self.mode = mode or os.environ.get("TR_CLI_MOCK_MODE", "ok")
        self.missing_tickers: set[str] = set()
        self._cookies: dict[str, str] = dict(initial_cookies or {})
        self._poll_count = 0
        self._session_rotations = 0
        self._requests: list[tuple[str, str]] = []  # (method, path) log for tests
        # history fixtures
        self.history_days: int = 200
        self.missing_history_start: dict[
            str, int
        ] = {}  # isin -> days skipped at series start
        self.fail_history_isins: set[str] = set()  # isin -> series subscription fails
        # timeline fixtures
        self.timeline_hide_creation: bool = (
            os.environ.get("TR_CLI_MOCK_HIDE_CREATION", "0") == "1"
        )  # drop creation/deposit signals for fallback tests
        # middle-gap simulation: isin -> set of bar indices to drop
        self.history_gaps: dict[str, set[int]] = {}

    # --- HTTP ---------------------------------------------------------------
    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        self._requests.append((method.upper(), path))
        body: str
        status = 200

        if path == "/api/v2/auth/web/login" and method.upper() == "POST":
            if self.mode == "rate_limited":
                return HttpResponse(status_code=429, body=LOGIN_429_BODY)
            if self.mode == "invalid_creds":
                return HttpResponse(
                    status_code=200, body='{"errors":[{"errorCode":"PIN_INVALID"}]}'
                )
            body = f'{{"processId":"{MOCK_PROCESS_ID}","countdownInSeconds":120,"twoFactorMethod":"APP_APPROVAL"}}'

        elif path.startswith("/api/v2/auth/web/login/processes/"):
            self._poll_count += 1
            if self.mode == "pending_forever":
                body = '{"status":"PENDING"}'
            elif self._poll_count <= 1:
                body = '{"status":"PENDING","expiresAt":"2030-01-01T00:00:00.000Z"}'
            else:
                body = '{"status":"CONFIRMED"}'
                self._cookies.update(
                    {
                        "tr_session": "mock-session-token",
                        "tr_refresh": "mock-refresh-token",
                        "tr_device": "mock-device",
                        "JSESSIONID": "mock-jsessionid",
                    }
                )

        elif path == "/api/v1/auth/web/session":
            self._session_rotations += 1
            if self._cookies:
                self._cookies["tr_session"] = (
                    f"mock-session-token-rot{self._session_rotations}"
                )
                self._cookies["JSESSIONID"] = (
                    f"mock-jsessionid-rot{self._session_rotations}"
                )
            body = '{"ok":true}'

        elif path == "/api/v2/auth/account":
            if self.mode == "expired_session":
                status = 401
                body = '{"errors":[{"errorCode":"UNAUTHENTICATED"}]}'
            else:
                body = _json(FIXTURE_ACCOUNT)

        elif path.startswith("/api/"):
            body = '{"error":"mock: unknown path"}'
            status = 404
        else:
            body = ""

        if status == 200 and not path.startswith("/api/v2/auth/account"):
            pass
        return HttpResponse(status_code=status, body=body)

    # --- WebSocket ----------------------------------------------------------
    def ws_collect(
        self,
        subscriptions: list[tuple[Hashable, dict[str, Any]]],
        *,
        timeout: float = 5.0,
    ) -> dict[Hashable, Any]:
        results: dict[Hashable, Any] = {}
        for key, payload in subscriptions:
            topic = payload.get("type")
            if topic == "compactPortfolioByType":
                results[key] = (
                    {"categories": []}
                    if self.mode == "empty_portfolio"
                    else dict(FIXTURE_PORTFOLIO)
                )
            elif topic == "cash":
                results[key] = [dict(c) for c in FIXTURE_CASH]
            elif topic == "instrument":
                isin = payload.get("id", "")
                if isin in FIXTURE_INSTRUMENTS:
                    results[key] = dict(FIXTURE_INSTRUMENTS[isin])
            elif topic == "ticker":
                ticker_id = payload.get("id", "")
                if (
                    ticker_id not in self.missing_tickers
                    and ticker_id in FIXTURE_TICKERS
                ):
                    results[key] = dict(FIXTURE_TICKERS[ticker_id])
            elif topic == "tradeAggregateHistory":
                isin = payload.get("isin", "")
                # base price = fixture year-start; last close = current ticker last price
                base = _ytd_base_price(isin)
                last_price = None
                for tkey, tval in FIXTURE_TICKERS.items():
                    if tkey.split(".")[0] == isin:
                        last_price = float(tval["last"]["price"])
                        break
                if last_price is not None:
                    results[key] = _ytd_bars(isin, base, last_price)
            elif topic == "stockDetails":
                isin = payload.get("id", "")
                if isin in FIXTURE_STOCK_DETAILS:
                    results[key] = dict(FIXTURE_STOCK_DETAILS[isin])
            elif topic == "performance":
                results[key] = dict(FIXTURE_PERFORMANCE)
            elif topic == "instrumentSuitability":
                results[key] = dict(FIXTURE_SUITABILITY)
            elif topic == "neonNews":
                results[key] = list(FIXTURE_NEWS)
            # unknown topics: no response (mimics timeout/missing)
        return results

    def ws_paginate(
        self,
        subscriptions: list[tuple[Hashable, dict[str, Any]]],
        *,
        next_payload: Any,
        timeout: float = 8.0,
        max_rounds: int = 25,
    ) -> dict[Hashable, list[Any]]:
        """Scripted multi-round pagination over the fixture item lists."""
        pages: dict[Hashable, list[list[dict]]] = {}
        for key, payload in subscriptions:
            topic = payload.get("type")
            if topic == "timelineTransactions":
                items = _timeline_tx_items()
            elif topic == "timelineActivityLog":
                items = _timeline_log_items()
            else:
                items = []
            if self.timeline_hide_creation:
                if topic == "timelineActivityLog":
                    items = [
                        it
                        for it in items
                        if it.get("eventType")
                        not in (
                            "CUSTOMER_CREATED",
                            "SECURITIES_ACCOUNT_CREATED",
                            "VERIFICATION_TRANSFER_ACCEPTED",
                        )
                    ]
                elif topic == "timelineTransactions":
                    items = [
                        it
                        for it in items
                        if it.get("eventType") != "BANK_TRANSACTION_INCOMING"
                    ]
            pages[key] = [
                items[i : i + TIMELINE_PAGE_SIZE]
                for i in range(0, len(items), TIMELINE_PAGE_SIZE)
            ]

        results: dict[Hashable, list[Any]] = {key: [] for key, _ in subscriptions}
        active = list(subscriptions)
        for _round in range(max_rounds):
            if not active:
                break
            round_results: dict[Hashable, Any] = {}
            for key, _payload in active:
                queue = pages.get(key) or []
                if not queue:
                    continue
                page_items = queue.pop(0)
                more = bool(queue)
                import base64 as _b64

                after = (
                    _b64.b64encode(str(len(queue) + 1).encode()).decode()
                    if more
                    else None
                )
                round_results[key] = {
                    "items": page_items,
                    "cursors": {"after": after, "before": None},
                }
            next_active: list[tuple[Hashable, dict[str, Any]]] = []
            for key, _payload in active:
                if key in round_results:
                    results[key].append(round_results[key])
                    nxt = next_payload(key, round_results[key])
                    if nxt is not None:
                        next_active.append((key, nxt))
            active = next_active
        return results

    def ws_rounds(
        self,
        batches: Any,
        *,
        timeout: float = 8.0,
        max_rounds: int = 12,
    ) -> dict[int, dict[Hashable, Any]]:
        """Emulate sequential rounds; supports builder callables."""
        results: dict[int, dict[Hashable, Any]] = {}
        for r_index in range(max_rounds):
            if callable(batches):
                batch = batches(r_index, results)
                if batch is None:
                    break
            else:
                if r_index >= len(batches):
                    break
                batch = batches[r_index]
            collected: dict[Hashable, Any] = {}
            for key, payload in batch:
                topic = payload.get("type")
                if topic == "compactPortfolioByType":
                    collected[key] = (
                        {"categories": []}
                        if self.mode == "empty_portfolio"
                        else dict(FIXTURE_PORTFOLIO)
                    )
                elif topic == "cash":
                    collected[key] = [dict(c) for c in FIXTURE_CASH]
                elif topic == "instrument":
                    isin = payload.get("id", "")
                    if isin in FIXTURE_INSTRUMENTS:
                        collected[key] = dict(FIXTURE_INSTRUMENTS[isin])
                elif topic == "tradeAggregateHistory":
                    isin = payload.get("isin", "")
                    last_price = None
                    for tkey, tval in FIXTURE_TICKERS.items():
                        if tkey.split(".")[0] == isin:
                            last_price = float(tval["last"]["price"])
                            break
                    if last_price is not None and isin not in self.fail_history_isins:
                        skip = self.missing_history_start.get(isin, 0)
                        gaps = self.history_gaps.get(isin)
                        frm = payload.get("from")
                        until = payload.get("until")
                        if frm and until:
                            num_bars = max(1, int((until - frm) // 86400000))
                        else:
                            num_bars = self.history_days
                        collected[key] = _history_bars(
                            _ytd_base_price(isin),
                            last_price,
                            num_bars=num_bars,
                            skip_days=skip,
                            gap_indices=gaps,
                        )
            results[r_index] = collected
        return results

    def cookies_snapshot(self) -> dict[str, str]:
        return dict(self._cookies)

    # --- test helpers ---------------------------------------------------------
    @property
    def request_log(self) -> list[tuple[str, str]]:
        return list(self._requests)


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj)
