"""WebSocket protocol client for api.traderepublic.com.

Wire protocol:
  - handshake wss://api.traderepublic.com with the session cookies in the
    Cookie header (no separate auth message)
  - send `connect <id> <json>` -> expect `connected`
  - `sub <id> {"type": ...}` -> responses come back as `<id> A|D|C|E <payload>`
  - `unsub <id>` to end a subscription

This module implements the connection + one-shot collect pattern used by all
data commands; long-lived streaming is out of scope.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Hashable
from typing import Any

import websockets

from .delta import decode_response
from .errors import ProtocolError
from .protocol import USER_AGENT, WS_URL, ws_connect_message

_counter = 0


def _next_subscription_id() -> str:
    global _counter
    _counter += 1
    return str(_counter)


def collect(
    transport,
    subscriptions: list[tuple[Hashable, dict[str, Any]]],
    *,
    cookie_str: str = "",
    timeout: float = 5.0,
) -> dict[Hashable, Any]:
    """One-shot subscribe->collect->close over a single WS connection.

    Returns {key: parsed_payload} for every subscription that answered within
    `timeout`. Subscriptions with no answer are simply absent from the result.
    """
    return asyncio.run(
        _collect_async(subscriptions, cookie_str=cookie_str, timeout=timeout)
    )


async def _collect_async(
    subscriptions: list[tuple[Hashable, dict[str, Any]]],
    *,
    cookie_str: str,
    timeout: float,
) -> dict[Hashable, Any]:
    headers = {"User-Agent": USER_AGENT}
    if cookie_str:
        headers["Cookie"] = cookie_str
    try:
        ws = await websockets.connect(
            WS_URL, additional_headers=headers, open_timeout=15
        )
    except Exception as e:  # OSError / InvalidStatus / ...
        raise ProtocolError(f"WebSocket connect failed: {type(e).__name__}: {e}") from e

    results: dict[Hashable, Any] = {}
    pending: dict[str, Hashable] = {}
    previous: dict[str, str] = {}

    try:
        await ws.send(ws_connect_message())
        greeting = await asyncio.wait_for(ws.recv(), timeout=10)
        if greeting != "connected":
            raise ProtocolError(f"Unexpected connect reply: {greeting[:120]!r}")

        for key, payload in subscriptions:
            sub_id = _next_subscription_id()
            pending[sub_id] = key
            await ws.send(f"sub {sub_id} {json.dumps(payload, separators=(',', ':'))}")

        deadline = asyncio.get_running_loop().time() + timeout
        while pending:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                frame = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except TimeoutError:
                break
            sub_id, code, payload = decode_response(frame, previous)
            key = pending.get(sub_id)
            if key is None and code != "C":
                continue
            if code in ("A", "D"):
                if key is not None:
                    results[key] = payload
                await ws.send(f"unsub {sub_id}")
                pending.pop(sub_id, None)
            elif code == "E" or code == "C":
                pending.pop(sub_id, None)
    finally:
        try:
            await ws.close()
        except (OSError, asyncio.CancelledError):
            pass
    return results
