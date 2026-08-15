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

FIXTURE_CASH = {"total": "1234.56", "available": "1000.00", "currency": "EUR"}

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
                results[key] = dict(FIXTURE_PORTFOLIO)
            elif topic == "cash":
                results[key] = dict(FIXTURE_CASH)
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

    def cookies_snapshot(self) -> dict[str, str]:
        return dict(self._cookies)

    # --- test helpers ---------------------------------------------------------
    @property
    def request_log(self) -> list[tuple[str, str]]:
        return list(self._requests)


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj)
