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
    # last day: Apple 10x232.05 + DB 5x16.44 = 2402.70 (POSITIONS ONLY)
    assert h.series[-1].total == Decimal("2402.70")
    assert h.series[-1].cash == "2234.56"  # cash is separate, never added
    assert h.start_date == h.series[0].date
    assert h.end_date == h.series[-1].date
    assert h.positions_covered == 2
    assert h.positions_without_series == []
    assert "approximate" in h.note.lower() or "retroactively" in h.note
    # every point carries the constant cash as a separate field
    for point in h.series:
        assert point.cash == "2234.56"


def test_history_cash_never_added_regression():
    """total must equal exactly the sum of qty*close (forward-filled); cash is separate."""
    from datetime import UTC as _UTC
    from decimal import ROUND_HALF_UP

    from tr_cli.mock import FIXTURE_TICKERS, _history_bars, _ytd_base_price

    m = _logged_in(days=50, hide_creation=True)
    window_days = 50
    h = client.history(m, days=window_days)
    assert len(h.series) == window_days

    # Independently recompute the per-position forward-filled closes from the
    # same fixture the mock serves (visible-bar pricing), then compare.
    net_size = {"US0378331005": Decimal(10), "DE0005140008": Decimal(5)}
    raw = {}
    for isin in net_size:
        last = next(
            float(t["last"]["price"])
            for tkey, t in FIXTURE_TICKERS.items()
            if tkey.split(".")[0] == isin
        )
        payload = _history_bars(_ytd_base_price(isin), last, num_bars=window_days)
        dates = {}
        for bar in payload["aggregates"]:
            day = datetime.fromtimestamp(bar["time"] / 1000, tz=_UTC).date().isoformat()
            dates[day] = Decimal(str(bar["close"]))
        raw[isin] = dates

    # forward-fill each position across the union of dates (same rule as client)
    all_days = sorted({d for dates in raw.values() for d in dates})
    filled = {}
    for isin, dates in raw.items():
        last_close = None
        fwd = {}
        for day in all_days:
            if day in dates:
                last_close = dates[day]
            if last_close is not None:
                fwd[day] = last_close
        filled[isin] = fwd

    for point in h.series:
        expected = sum(
            filled[isin][point.date] * qty for isin, qty in net_size.items()
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert point.total == expected, f"total mismatch on {point.date}"
        assert point.cash == "2234.56"  # separate field, never part of total
        assert point.total != point.total + Decimal("2234.56")


def test_history_dates_are_utc_days():
    m = _logged_in(days=60)
    h = client.history(m, days=60)
    dates = [p.date for p in h.series]
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) for d in dates)
    assert dates == sorted(set(dates))
    assert len(dates) == 60  # mock generates one bar per calendar day


def test_history_start_is_max_first_bar():
    """Series starts at the latest first-bar date -> every day covers all positions."""
    m = _logged_in(days=100)
    m.missing_history_start = {"DE0005140008": 30}  # DB series starts 30 days in
    h = client.history(m, days=100)  # fallback window: no creation signals
    assert h.positions_covered == 2
    # start = DB's first bar (30d in); no Apple-only prefix days
    assert len(h.series) == 100 - 30
    assert "start = max first bar date" in h.note
    assert "forward-filled" in h.note
    # day 0 already covers BOTH positions: Apple (forward-filled, ~1013) +
    # DB (first bar, ~495) -> total ~1907, far above an Apple-only day (~1013),
    # proving no missing-position prefix and no artificial drop at the start
    assert h.series[0].total > Decimal(1500)


def test_history_forward_fill_no_drop_regression():
    """Regression: a middle gap in one position must NOT drop the total."""
    m = _logged_in(days=100)
    # DB loses bars on indices 40..49 (middle of the 100-day series)
    m.history_gaps = {"DE0005140008": {40, 41, 42, 43, 44, 45, 46, 47, 48, 49}}
    h = client.history(m, days=100)
    assert h.positions_covered == 2
    assert len(h.series) == 100
    # DB's close is forward-filled across the gap -> the total never collapses.
    # (Without forward-fill, DB (~490 EUR) would vanish for 10 days.)
    deltas = [
        h.series[i].total - h.series[i - 1].total for i in range(1, len(h.series))
    ]
    assert min(deltas) >= Decimal("-0.01"), f"artificial drop in series: {min(deltas)}"
    # day-over-day at the gap boundary stays smooth (normal daily move, no ~490 EUR cliff)
    gap_start = 40
    boundary_delta = abs(h.series[gap_start].total - h.series[gap_start - 1].total)
    assert boundary_delta < Decimal(25), f"gap boundary jump: {boundary_delta}"


def test_history_failed_series_excluded():
    m = _logged_in(days=60)
    m.fail_history_isins = {"DE0005140008"}
    h = client.history(m, days=60)
    assert h.positions_covered == 1
    assert h.positions_without_series == ["DE0005140008"]
    # only Apple contributes (positions only, no cash add-on)
    assert h.series[-1].total == Decimal("2320.50")
    assert h.series[-1].cash == "2234.56"
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
        "coverage",
        "series",
    }
    assert data["coverage"]["positions"] == 2
    assert data["coverage"]["forward_filled"] is True
    # auto-detection wins over --days: CUSTOMER_CREATED is 150 days old in fixtures
    assert data["days"] == 150
    assert data["series"][0] == {
        "date": data["start_date"],
        "total": data["series"][0]["total"],
        "cash": "2234.56",
    }
    assert all("date" in p and "total" in p and "cash" in p for p in data["series"])
    assert data["series"][-1]["total"] == "2402.70"  # positions only
    assert data["series"][-1]["cash"] == "2234.56"  # cash separate
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
