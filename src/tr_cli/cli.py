"""tr-cli: small unofficial Trade Republic CLI.

Commands:
  login             v2 push-approval login (approve in the TR mobile app)
  session status    local check of the saved session (no network)
  session refresh   rotate session cookies via /api/v1/auth/web/session
  portfolio         positions + cash + totals
  rates <ISIN...>   quotes for one or more ISINs
  details <ISIN>    instrument detail view

Global flags: --mock (offline demo mode, TR_CLI_MOCK=1), --json.
Exit codes: 0 ok, 1 generic, 2 usage, 3 needs-login, 4 rate-limited,
5 login-failed, 6 protocol error.

Safety: real logins are never auto-retried; 429 shows a cooldown message.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from getpass import getpass
from pathlib import Path
from typing import Any

import typer

from . import client as client_mod
from . import render as render_mod
from . import session as session_mod
from .errors import (
    EXIT_GENERIC,
    NeedsLogin,
    TrCliError,
)
from .mock import MockTransport
from .protocol import (
    SESSION_REFRESH_INTERVAL_SEC,
    stable_device_id,
)
from .transport import RealTransport, Transport

app = typer.Typer(
    name="tr-cli",
    help="Small unofficial Trade Republic CLI (v2 push login, portfolio, rates, details).",
    no_args_is_help=True,
    add_completion=False,
)

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{10}$")


def _fail(error: TrCliError) -> None:
    """Print an error to stderr and exit with the mapped code."""
    print(f"error: {error}", file=sys.stderr)
    raise typer.Exit(code=error.exit_code)


def _warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# transport/session helpers
# ---------------------------------------------------------------------------


def _login_transport(mock: bool) -> Transport:
    """Clean transport for the login flow (no saved cookies)."""
    if mock:
        return MockTransport()
    waf = _waf_token()
    return RealTransport(initial_cookies={}, waf_token=waf)


def _session_transport(mock: bool, base_dir: Path | None) -> Transport:
    """Transport loaded with the saved session, with keepalive refresh."""
    if mock:
        return MockTransport(initial_cookies=session_mod.load_cookies(base_dir))
    if not session_mod.session_exists(base_dir):
        raise NeedsLogin("No saved session found. Run `tr-cli login` first.")
    cookies = session_mod.load_cookies(base_dir)
    missing = session_mod.required_missing(cookies)
    if missing:
        raise NeedsLogin(
            f"Saved session is missing required cookies {missing}. Run `tr-cli login` again."
        )
    waf = _waf_token()
    t = RealTransport(initial_cookies=cookies, waf_token=waf)
    _maybe_keepalive(t, base_dir)
    return t


def _maybe_keepalive(transport: Transport, base_dir: Path | None) -> None:
    """Best-effort session refresh when the cookie file is stale (~290s TTL)."""
    path = session_mod.cookies_path(base_dir)
    try:
        if time.time() - path.stat().st_mtime < SESSION_REFRESH_INTERVAL_SEC:
            return
    except OSError:
        return
    device_id = session_mod.load_device_id(base_dir) or stable_device_id()
    from .auth import refresh_session

    try:
        result = refresh_session(transport, device_id, _waf_token())
        if result["ok"]:
            changed = transport.cookies_snapshot()
            session_mod.save_cookies(changed, base_dir)
    except TrCliError:
        pass  # account check will surface a 401 as NeedsLogin if it matters


def _waf_token() -> str | None:
    import os

    return os.environ.get("TR_WAF_TOKEN") or None


def _device_id(base_dir: Path | None) -> str:
    return session_mod.load_device_id(base_dir) or stable_device_id()


def _emit(data: Any, json_output: bool, human: str) -> None:
    if json_output:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(human)


def _resolve_phone_pin(phone: str | None, pin: str | None) -> tuple[str, str]:
    import os

    phone = phone or os.environ.get("TR_PHONE")
    if not phone:
        phone = input(
            "Trade Republic phone number (international format, e.g. +49123...): "
        ).strip()
    pin = pin or os.environ.get("TR_PIN")
    if not pin:
        pin = getpass("Trade Republic PIN: ")
    if not phone or not pin:
        raise typer.Exit(code=2)
    return phone, pin


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


@app.command()
def login(
    phone: str | None = typer.Option(
        None, "--phone", "-n", help="TR phone number (or TR_PHONE env)."
    ),
    pin: str | None = typer.Option(
        None, "--pin", "-p", help="TR PIN (or TR_PIN env). Prompted if omitted."
    ),
) -> None:
    """Log in via the v2 push flow (approve the prompt in the TR mobile app)."""
    mock = _ctx_mock()
    base_dir = _ctx_base_dir()
    phone, pin = _resolve_phone_pin(phone, pin)
    transport = _login_transport(mock)

    from .auth import login_flow

    device_id = _device_id(base_dir)

    def on_initiate(process_id: str) -> None:
        print(
            "Approval push sent to your Trade Republic mobile app — approve it there.",
            file=sys.stderr,
        )
        print("(waiting up to 120s)", file=sys.stderr)

    def on_pending(remaining: int) -> None:
        print(f"Still waiting for approval, {remaining}s left...", file=sys.stderr)

    import os as _os

    timeout = float(_os.environ.get("TR_LOGIN_TIMEOUT", "120"))
    try:
        result = login_flow(
            transport,
            phone,
            pin,
            device_id,
            _waf_token(),
            on_initiate=on_initiate,
            on_pending=on_pending,
            timeout=timeout,
        )
    except TrCliError as e:
        _fail(e)

    if mock:
        result.cookies = transport.cookies_snapshot()
    if not result.cookies:
        _fail(NeedsLogin("Login completed but no session cookies were received."))
    n = session_mod.save_cookies(result.cookies, base_dir)
    session_mod.save_device_id(device_id, base_dir)
    summary = session_mod.summarize(result.cookies)
    data = {
        "ok": True,
        "phone": phone,
        "process_id": result.process_id,
        "cookies_saved": n,
        "cookies_file": str(session_mod.cookies_path(base_dir)),
        "summary": summary,
    }
    if _ctx_json():
        print(json.dumps(data, indent=2))
    else:
        print(
            f"Logged in. Session saved ({n} cookies) to {session_mod.cookies_path(base_dir)}"
        )
        print(
            f"Required cookies present: {', '.join(summary['required_present']) or '(none)'}"
        )


@app.command()
def portfolio() -> None:
    """Show positions, cash and totals."""
    mock = _ctx_mock()
    base_dir = _ctx_base_dir()
    try:
        transport = _session_transport(mock, base_dir)
        result = client_mod.portfolio(transport)
    except TrCliError as e:
        _fail(e)
    data = {
        "ok": True,
        "positions": [
            {
                "instrumentId": p.instrument_id,
                "name": p.name,
                "netSize": p.net_size,
                "averageBuyIn": p.average_buy_in,
                "price": p.price,
                "ask": p.ask,
                "netValue": str(p.net_value) if p.net_value is not None else None,
                "ytd": (
                    {
                        "basePrice": p.ytd_base_price,
                        "gain": str(p.ytd_gain) if p.ytd_gain is not None else None,
                        "pct": str(p.ytd_pct) if p.ytd_pct is not None else None,
                    }
                    if p.ytd_base_price is not None
                    else None
                ),
            }
            for p in result.positions
        ],
        "cash": {
            "items": [
                {"currencyId": i.currency_id, "amount": i.amount}
                for i in result.cash.items
            ],
            "total": str(result.cash.total),
        },
        "totalValue": str(result.total_value),
        "ytdTotal": str(result.ytd_total) if result.ytd_total is not None else None,
        "positions_ytd": {
            "base": "first trading day open of 2026 (tradeAggregateHistory daily bars)",
        },
    }
    _emit(data, _ctx_json(), render_mod.render_portfolio(result))


_ISINS_ARG = typer.Argument(..., help="ISINs, comma/semicolon/space separated.")


@app.command()
def rates(
    isins: list[str] = _ISINS_ARG,
) -> None:
    """Fetch quotes for one or more ISINs."""
    mock = _ctx_mock()
    base_dir = _ctx_base_dir()
    tokens: list[str] = []
    for chunk in isins:
        tokens.extend(t.strip() for t in re.split(r"[,;\s]+", chunk) if t.strip())
    valid = [t for t in tokens if ISIN_RE.match(t)]
    for t in set(tokens) - set(valid):
        _warn(f"skipping invalid ISIN: {t!r}")
    if not valid:
        _fail(_usage("No valid ISINs provided."))
    try:
        transport = _session_transport(mock, base_dir)
        quotes = client_mod.rates(transport, valid)
    except TrCliError as e:
        _fail(e)
    data = {
        "ok": True,
        "quotes": [
            {
                "instrumentId": q.instrument_id,
                "name": q.name,
                "price": q.price,
                "ask": q.ask,
            }
            for q in quotes
        ],
    }
    _emit(data, _ctx_json(), render_mod.render_rates(quotes))


def _usage(msg: str) -> TrCliError:
    from .errors import UsageError

    return UsageError(msg)


@app.command()
def timeline(
    days: int = typer.Option(90, "--days", help="How far back to fetch (default 90)."),
    bucket: str | None = typer.Option(
        None, "--bucket", help="Only show one bucket (e.g. dividends)."
    ),
) -> None:
    """Show the account's timeline (transactions + activity log, merged)."""
    mock = _ctx_mock()
    base_dir = _ctx_base_dir()
    try:
        transport = _session_transport(mock, base_dir)
        from .timeline import BUCKETS, fetch_timeline

        if bucket is not None and bucket not in BUCKETS:
            _fail(
                _usage(f"Invalid --bucket {bucket!r}; choose from {', '.join(BUCKETS)}")
            )
        result = fetch_timeline(transport, days=days)
    except TrCliError as e:
        _fail(e)
    if bucket is not None:
        result.events = [e for e in result.events if e.bucket == bucket]
    data = {
        "ok": True,
        "window_days": days,
        "pages": result.pages,
        "events": [
            {
                "id": e.id,
                "timestamp": e.timestamp,
                "title": e.title,
                "subtitle": e.subtitle,
                "eventType": e.event_type,
                "bucket": e.bucket,
                "amount": e.amount,
            }
            for e in result.events
        ],
        "buckets": {
            b: {
                "count": s.count,
                "sum": {c: str(v) for c, v in s.sums.items()},
            }
            for b, s in result.buckets.items()
        },
    }
    if _ctx_json():
        print(json.dumps(data, indent=2))
    else:
        print(render_mod.render_timeline(result, days=days, bucket=bucket))


@app.command()
def history(
    days: int | None = typer.Option(
        None,
        "--days",
        help="Limit the window to the last N days (default: full curve, max 730).",
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help="Start the curve at YYYY-MM-DD.",
    ),
    snapshots: str | None = typer.Option(
        None,
        "--snapshots",
        help="JSON file with collector snapshots [{date, total}] that override chart points.",
    ),
) -> None:
    """Historical portfolio value curve (official portfolio chart) + reconstructed cash."""
    mock = _ctx_mock()
    base_dir = _ctx_base_dir()
    if days is not None and (days < 1 or days > 730):
        _fail(_usage("--days must be between 1 and 730."))
    if since is not None:
        try:
            datetime.fromisoformat(since)
        except ValueError:
            _fail(_usage(f"Invalid --since {since!r}; expected YYYY-MM-DD."))
    snap_list: list[dict[str, Any]] | None = None
    if snapshots is not None:
        try:
            import pathlib as _pl

            snap_list = json.loads(_pl.Path(snapshots).read_text())
        except (OSError, ValueError) as e:
            _fail(_usage(f"Cannot read snapshots file {snapshots!r}: {e}"))
    try:
        transport = _session_transport(mock, base_dir)
        result = client_mod.history(
            transport, days=days, since=since, snapshots=snap_list
        )
    except TrCliError as e:
        _fail(e)
    data = {
        "ok": True,
        "start_date": result.start_date,
        "end_date": result.end_date,
        "days": len(result.series),
        "approximate": result.approximate,
        "note": result.note,
        "coverage": {
            "source": "portfolio-chart",
            "ranges": ["1y", "max"],
            "cash": "reconstructed",
            "cash_events": result.cash_events,
            "snapshots_merged": result.snapshots_merged,
        },
        "series": [
            {
                "date": p.date,
                "total": str(p.total),
                "cash": p.cash,
                "deposits": p.deposits,
            }
            for p in result.series
        ],
    }
    _emit(data, _ctx_json(), render_mod.render_history(result, days=days))


@app.command()
def details(
    isin: str = typer.Argument(..., help="ISIN to inspect."),
) -> None:
    """Show instrument details for one ISIN."""
    mock = _ctx_mock()
    base_dir = _ctx_base_dir()
    isin = isin.strip().upper()
    if not ISIN_RE.match(isin):
        _fail(_usage(f"Invalid ISIN: {isin!r}"))
    try:
        transport = _session_transport(mock, base_dir)
        topics = client_mod.details(transport, isin)
    except TrCliError as e:
        _fail(e)
    data = {
        "ok": True,
        "isin": isin,
        "topics": {k: v for k, v in topics.items() if v is not None},
    }
    _emit(data, _ctx_json(), render_mod.render_details(isin, topics))


# ---------------------------------------------------------------------------
# session sub-commands
# ---------------------------------------------------------------------------

session_app = typer.Typer(help="Session management.", no_args_is_help=True)
app.add_typer(session_app, name="session")


@session_app.command("status")
def session_status() -> None:
    """Show local session state (no network)."""
    base_dir = _ctx_base_dir()
    cookies = session_mod.load_cookies(base_dir)
    summary = session_mod.summarize(cookies)
    path = session_mod.cookies_path(base_dir)
    mtime = path.stat().st_mtime if path.is_file() else None
    data = {
        "ok": True,
        "exists": bool(cookies),
        "cookies_file": str(path) if path.is_file() else None,
        "mtime": mtime,
        "summary": summary,
    }
    if _ctx_json():
        print(json.dumps(data, indent=2))
    else:
        if not cookies:
            print("No saved session.")
            return
        print(f"Session file: {path}")
        print(
            f"Required cookies present: {', '.join(summary['required_present']) or '(none)'}"
        )
        missing = summary["required_missing"]
        if missing:
            print(f"Required cookies MISSING: {', '.join(missing)}")


@session_app.command("refresh")
def session_refresh() -> None:
    """Rotate the session cookies via /api/v1/auth/web/session."""
    mock = _ctx_mock()
    base_dir = _ctx_base_dir()
    try:
        transport = _session_transport(mock, base_dir)
        from .auth import refresh_session

        before = transport.cookies_snapshot()
        result = refresh_session(transport, _device_id(base_dir), _waf_token())
        if not result["ok"]:
            print(f"error: {result['error']}", file=sys.stderr)
            raise typer.Exit(code=EXIT_GENERIC)
        after = transport.cookies_snapshot()
        session_mod.save_cookies(after, base_dir)
        changed = sorted(
            k for k in set(before) | set(after) if before.get(k) != after.get(k)
        )
        data = {"ok": True, "status_code": 200, "cookies_changed": changed}
        if _ctx_json():
            print(json.dumps(data, indent=2))
        else:
            if changed:
                print(f"Session refreshed. Rotated cookies: {', '.join(changed)}")
            else:
                print("Session refreshed (no cookie values changed).")
    except TrCliError as e:
        _fail(e)


# ---------------------------------------------------------------------------
# context plumbing (mock flag / base dir via env)
# ---------------------------------------------------------------------------

_CTX: dict[str, Any] = {}


@app.callback()
def _main(
    mock: bool = typer.Option(
        False, "--mock", envvar="TR_CLI_MOCK", help="Offline demo mode (no network)."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON on stdout."),
) -> None:
    _CTX["mock"] = mock
    _CTX["json"] = json_output


def _ctx_mock() -> bool:
    return bool(_CTX.get("mock"))


def _ctx_json() -> bool:
    return bool(_CTX.get("json"))


def _ctx_base_dir() -> Path | None:
    import os

    override = os.environ.get("TR_CLI_DIR")
    return Path(override).expanduser() if override else None


def main() -> None:
    app()
