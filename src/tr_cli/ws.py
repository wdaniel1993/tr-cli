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


def paginate(
    subscriptions: list[tuple[Hashable, dict[str, Any]]],
    *,
    cookie_str: str,
    next_payload: Any,
    timeout: float = 8.0,
    max_rounds: int = 25,
) -> dict[Hashable, list[Any]]:
    """Multi-round subscribe->collect over ONE WS connection.

    Round 1 subscribes to all `(key, payload)` pairs. After each round,
    `next_payload(key, last_payload)` returns the payload for the next round
    (e.g. the same topic with an `after` cursor), or None to stop that key.
    A key that gets no reply in a round also stops. Returns
    {key: [round_1_payload, round_2_payload, ...]} for keys that answered.
    """
    return asyncio.run(
        _paginate_async(
            subscriptions,
            cookie_str=cookie_str,
            next_payload=next_payload,
            timeout=timeout,
            max_rounds=max_rounds,
        )
    )


async def _paginate_async(
    subscriptions: list[tuple[Hashable, dict[str, Any]]],
    *,
    cookie_str: str,
    next_payload: Any,
    timeout: float,
    max_rounds: int,
) -> dict[Hashable, list[Any]]:
    headers = {"User-Agent": USER_AGENT}
    if cookie_str:
        headers["Cookie"] = cookie_str
    try:
        ws = await websockets.connect(
            WS_URL, additional_headers=headers, open_timeout=15
        )
    except Exception as e:
        raise ProtocolError(f"WebSocket connect failed: {type(e).__name__}: {e}") from e

    results: dict[Hashable, list[Any]] = {key: [] for key, _ in subscriptions}
    try:
        await ws.send(ws_connect_message())
        greeting = await asyncio.wait_for(ws.recv(), timeout=10)
        if greeting != "connected":
            raise ProtocolError(f"Unexpected connect reply: {greeting[:120]!r}")

        active: list[tuple[Hashable, dict[str, Any]]] = list(subscriptions)
        previous: dict[str, str] = {}
        for _round in range(max_rounds):
            if not active:
                break
            pending: dict[str, Hashable] = {}
            for key, payload in active:
                sub_id = _next_subscription_id()
                pending[sub_id] = key
                await ws.send(
                    f"sub {sub_id} {json.dumps(payload, separators=(',', ':'))}"
                )
            round_results: dict[Hashable, Any] = {}
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
                        round_results[key] = payload
                    await ws.send(f"unsub {sub_id}")
                    pending.pop(sub_id, None)
                elif code in ("E", "C"):
                    pending.pop(sub_id, None)
            # Store this round's payloads and compute next round's subscriptions.
            next_active: list[tuple[Hashable, dict[str, Any]]] = []
            for key, _last in active:
                if key in round_results:
                    results[key].append(round_results[key])
                    nxt = next_payload(key, round_results[key])
                    if nxt is not None:
                        next_active.append((key, nxt))
            active = next_active
    finally:
        try:
            await ws.close()
        except (OSError, asyncio.CancelledError):
            pass
    return results


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
