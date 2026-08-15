import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from typer.testing import CliRunner

from tr_cli import client
from tr_cli.errors import UsageError
from tr_cli.mock import MockTransport

PHONE = "+491234567890"
PIN = "1234"
DEVICE_ID = "ab" * 32

runner = CliRunner()
from tr_cli.cli import app


def _logged_in(mode: str | None = None, days: int = 100, hide_creation: bool = True):
    m = MockTransport(mode=mode)
    from tr_cli.auth import login_flow

    login_flow(m, PHONE, PIN, DEVICE_ID)
    m.history_days = days
    # default: hide creation signals so the window tests exercise --days exactly
    m.timeline_hide_creation = hide_creation
    return m


def test_history_series_math():
    m = _logged_in(days=100)
    h = client.history(m, days=100)
    assert len(h.series) == 100
    assert "no creation events found; last 100 days" in h.note
    # last day: Apple 10x232.05 + DB 5x16.44 + cash 2234.56
    assert h.series[-1].total == Decimal("4637.26")
    assert h.series[-1].cash == "2234.56"
    assert h.start_date == h.series[0].date
    assert h.end_date == h.series[-1].date
    assert h.positions_covered == 2
    assert h.positions_without_series == []
    assert "approximate" in h.note.lower() or "retroactively" in h.note
    # every point includes cash
    for point in h.series:
        assert point.cash == "2234.56"


def test_history_dates_are_utc_days():
    m = _logged_in(days=60)
    h = client.history(m, days=60)
    dates = [p.date for p in h.series]
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) for d in dates)
    assert dates == sorted(set(dates))
    assert len(dates) == 60  # mock generates one bar per calendar day


def test_history_missing_bar_exclusion():
    m = _logged_in(days=100)
    m.missing_history_start = {"DE0005140008": 30}  # DB series starts 30 days in
    h = client.history(m, days=100)  # fallback window: no creation signals
    assert h.positions_covered == 2
    assert len(h.series) == 100  # dates come from the union (Apple covers all)
    # first 30 days: DB has no bar -> total = Apple only + cash
    # day 0 Apple close = 100 + step, step = (232.05-100)/99
    from decimal import ROUND_HALF_UP

    step = (Decimal("232.05") - Decimal(100)) / 99
    apple_close0 = (Decimal(100) + step).quantize(Decimal("0.0001"))
    expected0 = (apple_close0 * 10 + Decimal("2234.56")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    assert h.series[0].total == expected0
    # after DB joins, totals jump up (DB is in the money at first visible bar? no —
    # DB starts at 100+ and falls; but the total still changes once DB is included)
    assert h.series[29].total != h.series[30].total


def test_history_failed_series_excluded():
    m = _logged_in(days=60)
    m.fail_history_isins = {"DE0005140008"}
    h = client.history(m, days=60)
    assert h.positions_covered == 1
    assert h.positions_without_series == ["DE0005140008"]
    # only Apple contributes: last = 10x232.05 + cash
    assert h.series[-1].total == Decimal("2320.50") + Decimal("2234.56")
    assert "without series" in h.note


def test_history_empty_portfolio():
    m = _logged_in(mode="empty_portfolio")
    h = client.history(m, days=100)
    assert h.series == []
    assert h.start_date is None and h.end_date is None
    assert h.positions_covered == 0


# --- steer: account-start auto-detection -----------------------------------


def test_history_detects_account_start():
    m = MockTransport()
    from tr_cli.auth import login_flow

    login_flow(m, PHONE, PIN, DEVICE_ID)
    m.history_days = 300
    h = client.history(m, days=90)  # detection should win over the fallback
    expected = (datetime.now(UTC) - timedelta(days=150)).date().isoformat()
    assert h.start_date >= expected  # first bar on/after the creation date
    assert "account created" in h.note
    assert len(h.series) >= 150


def test_history_since_override():
    m = _logged_in(days=200)
    since = (datetime.now(UTC) - timedelta(days=60)).date().isoformat()
    h = client.history(m, since=since)
    assert "explicit --since" in h.note
    assert h.start_date >= since


def test_history_since_invalid():
    m = _logged_in()
    with pytest.raises(UsageError):
        client.history(m, since="not-a-date")


def test_history_fallback_when_no_signals():
    m = _logged_in(days=40, hide_creation=True)
    h = client.history(m, days=40)
    assert "no creation events found; last 40 days" in h.note
    assert len(h.series) == 40


def test_history_truncation_note():
    m = _logged_in(days=40, hide_creation=True)
    h = client.history(m, days=40)
    # 40-day window fits under the ~200-bar server cap -> no truncation note
    assert "truncated" not in h.note


def test_history_days_cap():
    m = _logged_in()
    with pytest.raises(UsageError):
        client.history(m, days=0)
    with pytest.raises(UsageError):
        client.history(m, days=731)


def test_history_cli_json_contract(cli_env):

    r = runner.invoke(app, ["login"], env={})
    assert r.exit_code == 0
    r = runner.invoke(app, ["--json", "history", "--days", "100"], env={})
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["ok"] is True
    assert data["approximate"] is True
    assert set(data) == {
        "ok",
        "start_date",
        "end_date",
        "days",
        "approximate",
        "note",
        "series",
    }
    # auto-detection wins over --days: CUSTOMER_CREATED is 150 days old in fixtures
    assert data["days"] == 150
    assert data["series"][0] == {
        "date": data["start_date"],
        "total": data["series"][0]["total"],
        "cash": "2234.56",
    }
    assert all("date" in p and "total" in p and "cash" in p for p in data["series"])
    assert data["series"][-1]["total"] == "4637.26"
    assert "account created" in data["note"]  # detection ran (CUSTOMER_CREATED fixture)


def test_history_cli_fallback_hide_creation(cli_env, monkeypatch):
    monkeypatch.setenv("TR_CLI_MOCK_HIDE_CREATION", "1")
    r = runner.invoke(app, ["login"], env={})
    assert r.exit_code == 0
    r = runner.invoke(app, ["--json", "history", "--days", "100"], env={})
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["days"] == 100
    assert "no creation events found" in data["note"]


def test_history_cli_days_limit(cli_env):

    r = runner.invoke(app, ["login"], env={})
    assert r.exit_code == 0
    r = runner.invoke(app, ["history", "--days", "9999"], env={})
    assert r.exit_code == 2
    assert "730" in r.output
