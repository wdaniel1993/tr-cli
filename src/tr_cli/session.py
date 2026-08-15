"""Session persistence: cookie jar + stable device id under ~/.tr-cli/.

Cookies live in a Netscape-format jar (readable by requests) at
~/.tr-cli/cookies.txt, written atomically with 0600 permissions. The stable
device id (64 hex chars) is persisted next to it so re-logins reuse the same
identity (cdamken pattern). All secrets stay OUTSIDE the repository.
"""

from __future__ import annotations

import os
import time
from http.cookiejar import Cookie, MozillaCookieJar
from pathlib import Path

from .protocol import REQUIRED_AUTH_COOKIES, USEFUL_COOKIES

DEFAULT_DIR = Path.home() / ".tr-cli"
COOKIES_FILE = "cookies.txt"
DEVICE_ID_FILE = "device_id"


def cookies_path(base_dir: Path | None = None) -> Path:
    return (base_dir or DEFAULT_DIR) / COOKIES_FILE


def device_id_path(base_dir: Path | None = None) -> Path:
    return (base_dir or DEFAULT_DIR) / DEVICE_ID_FILE


def load_device_id(base_dir: Path | None = None) -> str | None:
    path = device_id_path(base_dir)
    try:
        text = path.read_text().strip()
        return text or None
    except OSError:
        return None


def save_device_id(device_id: str, base_dir: Path | None = None) -> Path:
    path = device_id_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(device_id)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def save_cookies(cookies: dict[str, str], base_dir: Path | None = None) -> int:
    """Write cookies to the session jar (0600, atomic). Returns count written."""
    path = cookies_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    jar = MozillaCookieJar(str(path))
    expires = int(time.time()) + 365 * 24 * 3600
    for name, value in cookies.items():
        jar.set_cookie(
            Cookie(
                version=0,
                name=name,
                value=value,
                port=None,
                port_specified=False,
                domain=".traderepublic.com",
                domain_specified=True,
                domain_initial_dot=True,
                path="/",
                path_specified=True,
                secure=True,
                expires=expires,
                discard=False,
                comment=None,
                comment_url=None,
                rest={},
                rfc2109=False,
            )
        )
    tmp = path.with_name(path.name + ".tmp")
    jar.save(str(tmp), ignore_discard=True, ignore_expires=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return len(jar)


def load_cookies(base_dir: Path | None = None) -> dict[str, str]:
    """Load the session jar as {name: value}. Returns {} when absent."""
    path = cookies_path(base_dir)
    if not path.is_file():
        return {}
    jar = MozillaCookieJar(str(path))
    jar.load(ignore_discard=True, ignore_expires=True)
    return {c.name: c.value for c in jar}


def session_exists(base_dir: Path | None = None) -> bool:
    return cookies_path(base_dir).is_file()


def required_present(cookies: dict[str, str]) -> list[str]:
    return sorted(REQUIRED_AUTH_COOKIES & set(cookies))


def required_missing(cookies: dict[str, str]) -> list[str]:
    return sorted(REQUIRED_AUTH_COOKIES - set(cookies))


def summarize(cookies: dict[str, str]) -> dict[str, object]:
    have = set(cookies)
    return {
        "total": len(cookies),
        "required_present": required_present(cookies),
        "required_missing": required_missing(cookies),
        "useful_present": sorted(USEFUL_COOKIES & have),
        "extras": sorted(have - REQUIRED_AUTH_COOKIES - USEFUL_COOKIES),
    }
