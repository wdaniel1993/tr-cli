"""Trade Republic WebSocket frame decoding.

Wire format (text frames only):  `<subscriptionId> <CODE> <payload>`
  A = full answer (JSON payload)
  D = delta against the previous payload (TR's custom tab-separated patch)
  C = close (subscription ended)
  E = error

Delta algorithm (as used by pytr, re-implemented here):
  split the payload on tabs; for each token:
    "+..."   -> append urllib-decoded token (strip the +)
    "-N"     -> skip N chars of the previous payload
    "=N"     -> append N chars copied from the previous payload at index i
The result replaces the previous payload and is JSON-parsed.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

from .errors import ProtocolError


def parse_frame(frame: str) -> tuple[str, str, str]:
    """Split a raw WS frame into (subscription_id, code, payload_str)."""
    first_space = frame.find(" ")
    if first_space == -1:
        raise ValueError(f"Malformed frame (no space): {frame[:80]!r}")
    subscription_id = frame[:first_space]
    rest = frame[first_space + 1 :]
    code = rest[:1]
    payload = rest[1:].lstrip()
    return subscription_id, code, payload


def decode_delta(previous: str, delta_payload: str) -> str:
    """Apply TR's delta patch to the previous payload string."""
    i, result = 0, []
    for diff in delta_payload.split("\t"):
        if not diff:
            continue
        sign = diff[0]
        if sign == "+":
            result.append(urllib.parse.unquote_plus(diff).strip())
        elif sign in ("-", "="):
            length = int(diff[1:])
            if sign == "=":
                result.append(previous[i : i + length])
            i += length
        else:
            raise ProtocolError(f"Unknown delta op {sign!r} in {delta_payload[:80]!r}")
    return "".join(result)


def decode_response(
    frame: str, previous: dict[str, str] | None = None
) -> tuple[str, str, Any]:
    """Decode a raw WS frame into (subscription_id, code, parsed payload).

    Maintains `previous` in place: {subscription_id: last full payload str}.
    """
    subscription_id, code, payload = parse_frame(frame)
    if code == "A":
        if previous is not None:
            previous[subscription_id] = payload
        return subscription_id, code, json.loads(payload) if payload else {}
    if code == "D":
        prev = (previous or {}).get(subscription_id, "")
        full = decode_delta(prev, payload)
        if previous is not None:
            previous[subscription_id] = full
        return subscription_id, code, json.loads(full) if full else {}
    if code in ("C", "E"):
        return subscription_id, code, payload
    raise ProtocolError(f"Unknown frame code {code!r} in {frame[:80]!r}")
