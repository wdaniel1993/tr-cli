"""Transport abstraction.

Two implementations:
  - RealTransport: requests (HTTP) + websockets (WS) against api.traderepublic.com
  - MockTransport: bundled fixture data (see mock.py) — no network, no account

The CLI resolves the transport from --mock / TR_CLI_MOCK. All command logic
talks to Transport only, so the entire surface is testable offline.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Hashable
from dataclasses import dataclass, field
from typing import Any

import requests

from . import session as session_mod
from . import ws as ws_mod
from .errors import ProtocolError
from .protocol import API_BASE, REQUIRED_AUTH_COOKIES


@dataclass
class HttpResponse:
    """Normalized HTTP response (headers lowercased, Set-Cookie harvested)."""

    status_code: int
    body: str
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except ValueError as e:
            raise ProtocolError(
                f"Response body is not JSON (status {self.status_code}): {self.body[:120]!r}"
            ) from e


class Transport(ABC):
    """Minimal surface used by auth/client commands."""

    @abstractmethod
    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        """HTTP request to {API_BASE}{path}. Cookies are managed internally."""

    @abstractmethod
    def ws_collect(
        self,
        subscriptions: list[tuple[Hashable, dict[str, Any]]],
        *,
        timeout: float = 5.0,
    ) -> dict[Hashable, Any]:
        """Open one WS connection, subscribe to each (key, payload) pair,
        collect one full response per subscription, then close.

        Returns {key: parsed_payload} for received responses only.
        """

    @abstractmethod
    def ws_paginate(
        self,
        subscriptions: list[tuple[Hashable, dict[str, Any]]],
        *,
        next_payload: Any,
        timeout: float = 8.0,
        max_rounds: int = 25,
    ) -> dict[Hashable, list[Any]]:
        """Multi-round subscribe->collect over ONE WS connection.

        Round 1 subscribes to all (key, payload) pairs; after each round
        `next_payload(key, last_payload)` returns the next round's payload or
        None to stop. Returns {key: [round_1, round_2, ...]}.
        """

    @abstractmethod
    def ws_rounds(
        self,
        batches: Any,
        *,
        timeout: float = 8.0,
        max_rounds: int = 12,
    ) -> dict[int, dict[Hashable, Any]]:
        """Sequential subscribe rounds over ONE WS connection.

        `batches` is a static list of rounds OR a builder
        `builder(round_index, results_so_far) -> list[(key, payload)] | None`.
        Returns {round_index: {key: payload}}.
        """

    def cookies_snapshot(self) -> dict[str, str]:
        """Current cookie set (used after login to persist the session)."""
        return {}


class RealTransport(Transport):
    """Production transport: requests + websockets against TR."""

    def __init__(
        self,
        initial_cookies: dict[str, str] | None = None,
        waf_token: str | None = None,
    ):
        self.waf_token = waf_token
        self._http = requests.Session()
        if initial_cookies:
            for name, value in initial_cookies.items():
                self._http.cookies.set(
                    name, value, domain=".traderepublic.com", path="/"
                )
        if waf_token:
            self._http.cookies.set(
                "aws-waf-token", waf_token, domain=".traderepublic.com", path="/"
            )

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        try:
            r = self._http.request(
                method.upper(),
                API_BASE + path,
                json=json_body,
                headers=headers,
                timeout=25,
            )
        except requests.RequestException as e:
            raise ProtocolError(
                f"HTTP {method} {path} failed: {type(e).__name__}: {e}"
            ) from e
        # Normalize headers to lowercase keys; harvest Set-Cookie.
        hdrs = {k.lower(): v for k, v in r.headers.items()}
        harvested: dict[str, str] = {}
        for c in self._http.cookies:
            if c.domain.endswith("traderepublic.com") and c.value:
                harvested[c.name] = c.value
        return HttpResponse(
            status_code=r.status_code, body=r.text, headers=hdrs, cookies=harvested
        )

    def cookies_snapshot(self) -> dict[str, str]:
        out = {}
        for c in self._http.cookies:
            if c.domain.endswith("traderepublic.com") and c.value:
                out[c.name] = c.value
        return out

    def ws_collect(
        self,
        subscriptions: list[tuple[Hashable, dict[str, Any]]],
        *,
        timeout: float = 5.0,
    ) -> dict[Hashable, Any]:
        if not subscriptions:
            return {}
        cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookies_snapshot().items())
        return ws_mod.collect(
            self, subscriptions, cookie_str=cookie_str, timeout=timeout
        )

    def ws_paginate(
        self,
        subscriptions: list[tuple[Hashable, dict[str, Any]]],
        *,
        next_payload: Any,
        timeout: float = 8.0,
        max_rounds: int = 25,
    ) -> dict[Hashable, list[Any]]:
        if not subscriptions:
            return {}
        cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookies_snapshot().items())
        return ws_mod.paginate(
            subscriptions,
            cookie_str=cookie_str,
            next_payload=next_payload,
            timeout=timeout,
            max_rounds=max_rounds,
        )

    def ws_rounds(
        self,
        batches: Any,
        *,
        timeout: float = 8.0,
        max_rounds: int = 12,
    ) -> dict[int, dict[Hashable, Any]]:
        if not batches:
            return {}
        cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookies_snapshot().items())
        return ws_mod.rounds(
            batches, cookie_str=cookie_str, timeout=timeout, max_rounds=max_rounds
        )


def make_transport(
    *,
    mock: bool = False,
    base_dir=None,
    waf_token: str | None = None,
) -> Transport:
    """Resolve the transport from flags/env. Loads saved cookies for real mode."""
    if mock:
        from .mock import MockTransport

        return MockTransport()
    cookies = session_mod.load_cookies(base_dir)
    missing = REQUIRED_AUTH_COOKIES - set(cookies)
    if missing and not waf_token:
        # No usable session yet; still allow anonymous login via a clean transport.
        pass
    return RealTransport(initial_cookies=cookies, waf_token=waf_token)
