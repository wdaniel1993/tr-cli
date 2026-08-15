"""Trade Republic wire protocol: endpoints, header builders, device fingerprint.

All constants are centralized here and env-overridable so a protocol change
(bumped app version, different platform id, ...) is a one-line fix instead of
a code hunt. Defaults follow pytr (the most battle-tested unofficial client).

Research notes (cross-checked pytr / cdamken / NightOwl07 / Erim32 / autotr):
- v2 web login: POST /api/v2/auth/web/login {phoneNumber, pin} -> {processId};
  TR pushes an approval prompt to the mobile app; poll the process endpoint
  until status CONFIRMED. Session cookies (JSESSIONID, tr_refresh, tr_device)
  arrive via Set-Cookie. pytr does this WITHOUT any AWS WAF token.
- Keepalive/refresh: GET /api/v1/auth/web/session rotates the cookies.
- Account: GET /api/v2/auth/account (cookie auth) -> securitiesAccountNumber.
"""

from __future__ import annotations

import base64
import json
import os
import platform
import re
import uuid
from datetime import UTC, datetime

API_BASE = os.environ.get("TR_API_BASE", "https://api.traderepublic.com")
APP_ORIGIN = os.environ.get("TR_APP_ORIGIN", "https://app.traderepublic.com")
WS_URL = os.environ.get("TR_WS_URL", "wss://api.traderepublic.com")

# Header values (env-overridable; pytr defaults).
TR_APP_VERSION = os.environ.get("TR_APP_VERSION", "2.2631.13")
TR_PLATFORM = os.environ.get("TR_PLATFORM", "web-pro")
USER_AGENT = os.environ.get(
    "TR_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
)
LOCALE = os.environ.get("TR_LOCALE", "en")

# WS handshake (cookie-authenticated, pytr's connect id 31 + full message).
WS_CONNECT_ID = os.environ.get("TR_WS_CONNECT_ID", "31")
WS_PLATFORM_ID = "webtrading"
WS_PLATFORM_VERSION = os.environ.get("TR_WS_PLATFORM_VERSION", "chrome - 94.0.4606")
WS_CLIENT_ID = "app.traderepublic.com"
WS_CLIENT_VERSION = os.environ.get("TR_WS_CLIENT_VERSION", "5582")

# Session keepalive window (pytr refreshes ~290s, just under the ~5 min TTL).
SESSION_REFRESH_INTERVAL_SEC = 290

# Login process polling defaults.
LOGIN_POLL_INTERVAL_SEC = 2.0
LOGIN_TIMEOUT_SEC = 120.0

# Cookies that must be present for an authenticated session.
REQUIRED_AUTH_COOKIES = frozenset({"JSESSIONID", "tr_refresh", "tr_device"})
# Extra cookies worth persisting when TR sets them.
USEFUL_COOKIES = frozenset(
    {"tr_claims", "aws-waf-token", "tr_external_id", "tr_user_exp_id"}
)

# Endpoints.
LOGIN_ENDPOINT = "/api/v2/auth/web/login"
SESSION_ENDPOINT = "/api/v1/auth/web/session"
ACCOUNT_ENDPOINT = "/api/v2/auth/account"


def _timezone_name() -> str:
    """IANA tz name with the web frontend's own fallback."""
    try:
        import pathlib as _pl

        resolved = str(_pl.Path("/etc/localtime").resolve())
        if "zoneinfo/" in resolved:
            return resolved.split("zoneinfo/")[1]
    except (OSError, IndexError):
        pass
    return "Etc/UTC"


def stable_device_id() -> str:
    """64-hex device id stable for this machine (web frontend uses a hashed
    canvas fingerprint; we hash machine identity instead)."""
    seed = "|".join(
        [str(uuid.getnode()), platform.node(), platform.machine(), platform.system()]
    )
    import hashlib

    return hashlib.sha512(seed.encode()).hexdigest()


def device_info_header(stable_id: str | None = None) -> str:
    """Base64-encoded JSON device description sent as x-tr-device-info.

    Fields the frontend can only fill from a browser are left out rather than
    invented (model/deviceMemory on desktop), matching pytr.
    """
    now = datetime.now(UTC).astimezone()
    offset_min = int(now.utcoffset().total_seconds() // 60) if now.utcoffset() else 0
    chrome = re.search(r"Chrome/([\d.]+)", USER_AGENT)
    device = {
        "stableDeviceId": stable_id or stable_device_id(),
        "browser": "Chrome",
        "browserVersion": chrome.group(1) if chrome else "",
        "os": platform.system(),
        "osVersion": platform.release(),
        "timezone": _timezone_name(),
        # JavaScript counts the offset the other way round than Python.
        "timezoneOffset": -offset_min,
        "screen": "1920x1080x24",
        "preferredLanguages": [LOCALE],
        "numberOfCores": os.cpu_count() or 1,
    }
    raw = json.dumps(device, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def login_headers(
    device_id: str | None = None, waf_token: str | None = None
) -> dict[str, str]:
    """Headers for the /api/v2/auth/web/login* round-trip.

    `waf_token` is optional (pytr skips it on v2); when provided it is sent as
    both the x-aws-waf-token header and the aws-waf-token cookie (cdamken).
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": LOCALE,
        "Content-Type": "application/json",
        "Origin": APP_ORIGIN,
        "Referer": APP_ORIGIN + "/",
        "x-tr-platform": TR_PLATFORM,
        "x-tr-app-version": TR_APP_VERSION,
        "x-tr-device-info": device_info_header(device_id),
    }
    if waf_token:
        headers["x-aws-waf-token"] = waf_token
    return headers


def ws_connect_message() -> str:
    """The `connect` frame sent after the WS handshake."""
    payload = {
        "locale": LOCALE,
        "platformId": WS_PLATFORM_ID,
        "platformVersion": WS_PLATFORM_VERSION,
        "clientId": WS_CLIENT_ID,
        "clientVersion": WS_CLIENT_VERSION,
    }
    return f"connect {WS_CONNECT_ID} {json.dumps(payload, separators=(',', ':'))}"
