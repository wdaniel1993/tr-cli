#!/usr/bin/env python3
"""Probe ticker topic id formats (real account, one WS connection).

Resolves the FORBIDDEN seen for ticker {"id": "DE000BASF111.XETR"}:
1. sub instrument -> take the first active exchange slug from the raw reply
2. sub ticker with "ISIN.SLUG" (slug as returned)
3. sub ticker with lowercase slug
4. sub ticker with bare ISIN
Prints raw replies (public instrument data only; no account data).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import websockets  # noqa: E402

from tr_cli import session as session_mod  # noqa: E402
from tr_cli.delta import decode_response  # noqa: E402
from tr_cli.protocol import USER_AGENT, WS_URL, ws_connect_message  # noqa: E402


async def probe(isin: str):
    cookies = session_mod.load_cookies()
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    headers = {"User-Agent": USER_AGENT, "Cookie": cookie_str}
    ws = await websockets.connect(WS_URL, additional_headers=headers, open_timeout=15)
    previous: dict[str, str] = {}
    slug = None

    try:
        await ws.send(ws_connect_message())
        print(f"connect -> {await asyncio.wait_for(ws.recv(), timeout=10)!r}")

        await ws.send('sub 1 {"type":"instrument","id":"' + isin + '"}')
        # collect instrument reply, extract slug
        deadline = asyncio.get_running_loop().time() + 10
        while asyncio.get_running_loop().time() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            frame = raw.decode() if isinstance(raw, bytes) else str(raw)
            sid, code, payload = decode_response(frame, previous)
            print(f"< [instrument] {code} {json.dumps(payload)[:200]}")
            if code in ("A", "D"):
                try:
                    exs = payload.get("exchanges", [])
                    active = [e for e in exs if e.get("active")]
                    if active:
                        slug = active[0].get("slug")
                    print(f"  first active exchange slug: {slug!r}")
                except AttributeError:
                    pass
                break
            if code in ("E", "C"):
                break
        await ws.send("unsub 1")

        variants = [
            (2, {"type": "ticker", "id": f"{isin}.{slug}" if slug else isin}),
            (3, {"type": "ticker", "id": f"{isin}.{slug.lower()}" if slug else isin}),
            (4, {"type": "ticker", "id": isin}),
        ]
        for sid, payload in variants:
            print(f"\n> sub {sid} {json.dumps(payload, separators=(',', ':'))}")
            await ws.send(f"sub {sid} {json.dumps(payload, separators=(',', ':'))}")

        deadline = asyncio.get_running_loop().time() + 10
        got = {}
        while asyncio.get_running_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(0.5, deadline - asyncio.get_running_loop().time()))
            except TimeoutError:
                break
            frame = raw.decode() if isinstance(raw, bytes) else str(raw)
            sid, code, payload = decode_response(frame, previous)
            if sid in got:
                continue
            got[sid] = True
            print(f"< [sub {sid}] {code} {json.dumps(payload)[:300]}")
            if code in ("A", "D", "E", "C"):
                await ws.send(f"unsub {sid}")
    finally:
        await ws.close()


def main() -> int:
    isin = sys.argv[1] if len(sys.argv) > 1 else "DE000BASF111"
    asyncio.run(probe(isin))
    return 0


if __name__ == "__main__":
    sys.exit(main())
