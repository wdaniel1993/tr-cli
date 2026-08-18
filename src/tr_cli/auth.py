"""v2 push-approval login flow + session refresh.

Flow (current TR web login, no WAF token needed on v2 — pytr verified):
  1. POST /api/v2/auth/web/login {phoneNumber, pin} -> {processId}
     TR pushes an approval prompt to the user's mobile app.
  2. Poll GET /api/v2/auth/web/login/processes/{processId} until
     status in {CONFIRMED, COMPLETED, APPROVED} (PENDING = keep waiting).
     Session cookies (JSESSIONID, tr_refresh, tr_device) arrive via Set-Cookie
     during this round-trip (requests merges them into the session).
  3. Harvest cookies -> caller persists them.

429 TOO_MANY_REQUESTS is never retried; cooldown info is parsed from
errors[0].meta (nextAttemptTimestamp / nextAttemptInSeconds).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .errors import ApprovalTimeout, LoginFailed, RateLimited
from .protocol import (
    LOGIN_ENDPOINT,
    LOGIN_POLL_INTERVAL_SEC,
    LOGIN_TIMEOUT_SEC,
    SESSION_ENDPOINT,
    login_headers,
)
from .transport import HttpResponse, Transport

# Statuses the poll accepts as success.
APPROVED_STATES = {"CONFIRMED", "COMPLETED", "APPROVED", "SUCCESS", "OK", "DONE"}
FAILED_STATES = {"REJECTED", "DECLINED", "FAILED", "EXPIRED"}


@dataclass
class LoginResult:
    process_id: str
    cookies: dict[str, str] = field(default_factory=dict)
    raw_initiate: dict[str, Any] = field(default_factory=dict)


def _error_code(resp: HttpResponse) -> tuple[str | None, dict[str, Any] | None]:
    """Extract (errorCode, meta) from TR's error envelope, if present."""
    try:
        j = resp.json()
    except (ValueError, TypeError):
        return None, None
    errors = j.get("errors") if isinstance(j, dict) else None
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return errors[0].get("errorCode"), errors[0].get("meta")
    return None, None


def _raise_for_login_error(resp: HttpResponse, *, phase: str) -> None:
    code, meta = _error_code(resp)
    if resp.status_code == 429 or code == "TOO_MANY_REQUESTS":
        wait_s: int | None = None
        next_at: str | None = None
        if isinstance(meta, dict):
            wait_s = meta.get("nextAttemptInSeconds")
            next_at = meta.get("nextAttemptTimestamp")
        msg = "Trade Republic is rate-limiting login attempts for this account."
        if wait_s:
            msg += f" Retry in ~{wait_s}s ({wait_s // 60} min)."
        if next_at:
            msg += f" Next attempt allowed at {next_at}."
        raise RateLimited(msg, wait_seconds=wait_s, next_attempt_at=next_at)
    if code in ("PIN_INVALID", "NUMBER_INVALID", "USER_NOT_FOUND"):
        raise LoginFailed(
            f"Trade Republic rejected the credentials ({code}). Check phone number and PIN."
        )
    if resp.status_code == 405 and not resp.body.strip():
        raise LoginFailed(
            "Request blocked by AWS WAF (405, empty body). The v2 login normally "
            "works without a WAF token; if TR started enforcing one, set "
            "TR_WAF_TOKEN=<token> and retry."
        )
    raise LoginFailed(
        f"Login {phase} failed: HTTP {resp.status_code} {resp.body[:200]!r}"
    )


def initiate_login(
    transport: Transport,
    phone: str,
    pin: str,
    device_id: str,
    waf_token: str | None = None,
    otp_less: bool = False,
) -> LoginResult:
    """POST /api/v2/auth/web/login. Returns processId (push sent to app).

    `otp_less=True` sends the X-TR-OTP-Less header: TR may authenticate
    PIN-only without an app-approval push (trusted-device behaviour). If the
    server still requires approval the poll simply waits as usual.
    """
    headers = login_headers(device_id, waf_token)
    if otp_less:
        headers["X-TR-OTP-Less"] = "true"
    resp = transport.request(
        "POST",
        LOGIN_ENDPOINT,
        json_body={"phoneNumber": phone, "pin": pin},
        headers=headers,
    )
    if not resp.ok:
        _raise_for_login_error(resp, phase="initiate")
    try:
        j = resp.json()
    except Exception as e:
        raise LoginFailed(
            f"Initiate returned 200 but body was not JSON: {resp.body[:120]!r}"
        ) from e
    if isinstance(j, dict) and j.get("errors"):
        # TR sometimes answers 200 with an error envelope (e.g. PIN_INVALID).
        code, _meta = _error_code(resp)
        raise LoginFailed(
            f"Trade Republic rejected the credentials ({code or 'unknown error'})."
        )
    pid = j.get("processId") if isinstance(j, dict) else None
    if not pid:
        raise LoginFailed(f"Initiate returned 200 but no processId: {j}")
    return LoginResult(process_id=pid, raw_initiate=j)


def poll_login(
    transport: Transport,
    process_id: str,
    device_id: str,
    waf_token: str | None = None,
    *,
    timeout: float = LOGIN_TIMEOUT_SEC,
    interval: float = LOGIN_POLL_INTERVAL_SEC,
    on_pending: Callable[[int], None] | None = None,
) -> LoginResult:
    """Poll the login process until approved. Harvests cookies via transport."""
    headers = login_headers(device_id, waf_token)
    url = f"{LOGIN_ENDPOINT}/processes/{process_id}"
    deadline = time.monotonic() + timeout
    last_announce = time.monotonic()
    while time.monotonic() < deadline:
        resp = transport.request("GET", url, headers=headers)
        if resp.status_code == 200:
            try:
                j = resp.json()
            except (ValueError, TypeError):
                j = {}
            state = str(j.get("status") or j.get("state") or "").upper()
            if state in APPROVED_STATES:
                return LoginResult(
                    process_id=process_id,
                    cookies=transport.cookies_snapshot(),
                    raw_initiate=j,
                )
            if state in FAILED_STATES:
                raise LoginFailed(f"Login process {state.lower()}: {j}")
            if not state:
                # Some flows set the session cookie without an explicit state.
                snap = transport.cookies_snapshot()
                if "tr_session" in snap or "JSESSIONID" in snap:
                    return LoginResult(
                        process_id=process_id, cookies=snap, raw_initiate=j
                    )
            remaining = int(deadline - time.monotonic())
            if on_pending and (time.monotonic() - last_announce) >= 10:
                last_announce = time.monotonic()
                on_pending(remaining)
        elif resp.status_code in (401, 403, 404, 410):
            raise ApprovalTimeout(
                f"Login process expired/gone (HTTP {resp.status_code}). Approve the push faster and try again."
            )
        else:
            _raise_for_login_error(resp, phase="poll")
        time.sleep(interval)
    raise ApprovalTimeout(
        "Approval not received in time — open the Trade Republic app and approve "
        "the login prompt, then run `tr-cli login` again."
    )


def login_flow(
    transport: Transport,
    phone: str,
    pin: str,
    device_id: str,
    waf_token: str | None = None,
    *,
    on_initiate: Callable[[str], None] | None = None,
    on_pending: Callable[[int], None] | None = None,
    timeout: float = LOGIN_TIMEOUT_SEC,
    interval: float = LOGIN_POLL_INTERVAL_SEC,
    otp_less: bool = False,
) -> LoginResult:
    """Full v2 push login: initiate -> poll -> cookies.

    `on_initiate(process_id)` fires once after the push is sent;
    `on_pending(remaining_seconds)` fires periodically while waiting.
    `otp_less=True` requests PIN-only auth (X-TR-OTP-Less header); the poll
    still waits for CONFIRMED — without a push the server responds on its own.
    """
    init = initiate_login(
        transport, phone, pin, device_id, waf_token, otp_less=otp_less
    )
    if on_initiate:
        on_initiate(init.process_id)
    return poll_login(
        transport,
        init.process_id,
        device_id,
        waf_token,
        on_pending=on_pending,
        timeout=timeout,
        interval=interval,
    )


def refresh_session(
    transport: Transport, device_id: str, waf_token: str | None = None
) -> dict[str, Any]:
    """GET /api/v1/auth/web/session — rotates session cookies server-side.

    Returns {"ok": bool, "status_code": int, "cookies_changed": [...], "error": str|None}.
    """
    resp = transport.request(
        "GET", SESSION_ENDPOINT, headers=login_headers(device_id, waf_token)
    )
    if resp.status_code != 200:
        return {
            "ok": False,
            "status_code": resp.status_code,
            "cookies_changed": [],
            "error": f"refresh rejected: HTTP {resp.status_code} {resp.body[:200]!r}",
        }
    return {"ok": True, "status_code": 200, "cookies_changed": [], "error": None}
