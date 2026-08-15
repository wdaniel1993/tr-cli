#!/usr/bin/env python3
"""Capture real-account wire shapes (redacted) — spike recording tool.

Usage (from repo root, after `tr-cli login`):
    uv run python scripts/capture-wire.py [ISIN] [EXCHANGE]

Prints redacted structures: keys + types + nesting preserved, all leaf values
masked, so the output is safe to commit into docs/wire-notes.md. The account
number is extracted internally (needed for the portfolio topic) but never
printed.

Makes exactly: 2 HTTP GETs + 1 WebSocket connection (4 subscriptions).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import websockets

from tr_cli import session as session_mod
from tr_cli.delta import decode_response
from tr_cli.protocol import (
    ACCOUNT_ENDPOINT,
    SESSION_ENDPOINT,
    USER_AGENT,
    WS_URL,
    login_headers,
    ws_connect_message,
)
from tr_cli.transport import RealTransport


def redact(obj):
    """Mask leaf values, keep structure."""
    if isinstance(obj, dict):
        return {str(k): redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    if isinstance(obj, bool):
        return "<bool>"
    if isinstance(obj, (int, float)):
        return "<num>"
    if isinstance(obj, str):
        return "<str>"
    return "<?>"


def find_account_number(body):
    """Locate the securities account number generically (never printed)."""
    if isinstance(body, dict):
        for key in ("securitiesAccountNumber", "secAccNo", "securitiesAccountId"):
            v = body.get(key)
            if isinstance(v, str) and v:
                return v
        for v in body.values():
            found = find_account_number(v)
            if found:
                return found
    elif isinstance(body, list):
        for v in body:
            found = find_account_number(v)
            if found:
                return found
    return None


def http_capture(transport: RealTransport, device_id: str):
    print("=" * 70)
    print("HTTP")
    print("=" * 70)

    # 1. Account (cookie auth) — request() prepends API_BASE itself.
    resp = transport.request("GET", ACCOUNT_ENDPOINT, headers=login_headers(device_id))
    print(f"\nGET {ACCOUNT_ENDPOINT} -> {resp.status_code}")
    print(f"  response headers: {json.dumps(sorted(resp.headers.keys()))}")
    account = None
    try:
        account = resp.json()
    except (ValueError, TypeError):
        print(f"  body (non-JSON): {resp.body[:120]!r}")
    if isinstance(account, dict):
        print(f"  body structure: {json.dumps(redact(account), indent=2)[:2500]}")

    # 2. Session refresh (cookie auth) — cookie rotation check
    before = set(transport.cookies_snapshot())
    resp2 = transport.request("GET", SESSION_ENDPOINT, headers=login_headers(device_id))
    after = set(transport.cookies_snapshot())
    print(f"\nGET {SESSION_ENDPOINT} -> {resp2.status_code}")
    print(f"  cookies before: {sorted(before)}")
    print(f"  cookies after:  {sorted(after)}")
    print(f"  cookie changes: {sorted(after - before) or 'none'}")
    if resp2.body.strip():
        try:
            print(
                f"  body structure: {json.dumps(redact(resp2.json()), indent=2)[:800]}"
            )
        except (ValueError, TypeError):
            print(f"  body (non-JSON): {resp2.body[:120]!r}")
    return account


async def ws_capture(cookie_str: str, sec_acc_no: str | None, isin: str, exchange: str):
    print("\n" + "=" * 70)
    print("WebSocket")
    print("=" * 70)
    headers = {"User-Agent": USER_AGENT}
    if cookie_str:
        headers["Cookie"] = cookie_str
    ws = await websockets.connect(WS_URL, additional_headers=headers, open_timeout=15)
    try:
        await ws.send(ws_connect_message())
        greeting = await asyncio.wait_for(ws.recv(), timeout=10)
        print(f"\nconnect {ws_connect_message().split(' ', 2)[1]}")
        print(f"  -> reply: {greeting!r}")

        subs = [
            ("cash", {"type": "cash"}),
            ("instrument", {"type": "instrument", "id": isin}),
            ("ticker", {"type": "ticker", "id": f"{isin}.{exchange}"}),
        ]
        if sec_acc_no:
            subs.insert(
                1,
                (
                    "portfolio",
                    {"type": "compactPortfolioByType", "secAccNo": sec_acc_no},
                ),
            )

        previous: dict[str, str] = {}
        pending = {}
        for i, (label, payload) in enumerate(subs, start=1):
            sid = str(i)
            pending[sid] = label
            frame = f"sub {sid} {json.dumps(payload, separators=(',', ':'))}"
            if "secAccNo" in payload:
                frame = f"sub {sid} {json.dumps({**payload, 'secAccNo': '<redacted>'}, separators=(',', ':'))}"
            print(f"\n> {frame}")
            await ws.send(frame)

        deadline = asyncio.get_running_loop().time() + 8.0
        while pending and asyncio.get_running_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(
                    ws.recv(),
                    timeout=max(0.1, deadline - asyncio.get_running_loop().time()),
                )
            except TimeoutError:
                break
            frame = raw.decode() if isinstance(raw, bytes) else str(raw)
            sid, code, payload = decode_response(frame, previous)
            label = pending.get(sid)
            if code in ("A", "D"):
                print(
                    f"< [{label}] frame code={code} structure: {json.dumps(redact(payload), indent=2)[:2500]}"
                )
                await ws.send(f"unsub {sid}")
                pending.pop(sid, None)
            elif code in ("E", "C"):
                print(f"< [{label}] frame code={code} payload={payload!r}")
                pending.pop(sid, None)
        for sid, label in pending.items():
            print(f"< [{label}] NO REPLY within window")
    finally:
        await ws.close()


def main() -> int:
    isin = sys.argv[1] if len(sys.argv) > 1 else "DE000BASF111"
    exchange = sys.argv[2] if len(sys.argv) > 2 else "XETR"

    cookies = session_mod.load_cookies()
    if not cookies:
        print("No session found — run `tr-cli login` first.", file=sys.stderr)
        return 1
    print(f"Loaded {len(cookies)} cookies: {sorted(cookies.keys())}")

    transport = RealTransport(initial_cookies=cookies)
    from tr_cli.protocol import stable_device_id

    account = http_capture(transport, stable_device_id())

    sec_acc_no = find_account_number(account) if isinstance(account, dict) else None
    print(f"\nsecuritiesAccountNumber found: {bool(sec_acc_no)} (value redacted)")

    cookie_str = "; ".join(f"{k}={v}" for k, v in transport.cookies_snapshot().items())
    asyncio.run(ws_capture(cookie_str, sec_acc_no, isin, exchange))
    return 0


if __name__ == "__main__":
    sys.exit(main())
