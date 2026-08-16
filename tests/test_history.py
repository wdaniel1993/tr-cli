"""Tests for the v0.3.0 history: official portfolio-chart source + cash reconstruction."""

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


def _logged_in(mode: str | None = None):
    m = MockTransport(mode=mode)
    from tr_cli.auth import login_flow

    login_flow(m, PHONE, PIN, DEVICE_ID)
    return m


# --- chart merge ------------------------------------------------------------


def test_history_merge_daily_wins_over_coarser():
    m = _logged_in()
    h = client.history(m)
    assert h.start_date is not None and h.end_date is not None
    assert len(h.series) > 200
    # leading zero dropped: first total is non-zero
    assert h.series[0].total != 0
    assert h.start_date == h.series[0].date
    # last point = final 1y chart value (positions only)
    assert h.series[-1].total == Decimal("150000.00")
    assert h.approximate is False


def test_history_granularity_note():
    m = _logged_in()
    h = client.history(m)
    assert "daily since" in h.note
    assert "coarser before" in h.note
    assert "cash reconstructed from 9 events" in h.note  # no-amount event skipped


def test_history_leading_zero_dropped():
    m = _logged_in()
    h = client.history(m)
    # max fixture's first point (0.00) must not appear in the series
    assert all(p.total != 0 for p in h.series)
    # the first date is the max fixture's first NON-ZERO point (360-20=340 days ago)
    expected_start = (datetime.now(UTC) - timedelta(days=340)).date().isoformat()
    assert h.start_date == expected_start


def test_history_snapshots_override():
    m = _logged_in()
    snap = {
        "date": (datetime.now(UTC) - timedelta(days=30)).date().isoformat(),
        "total": "999999.00",
    }
    h = client.history(m, snapshots=[snap])
    assert h.snapshots_merged == 1
    assert "snapshots merged: 1" in h.note
    by_date = {p.date: p.total for p in h.series}
    assert by_date[snap["date"]] == Decimal("999999.00")


def test_history_since_and_days_filters():
    m = _logged_in()
    h = client.history(m)
    end = h.end_date
    # --days window
    h90 = client.history(m, days=90)
    assert len(h90.series) <= 91
    assert h90.series[-1].date == end
    # --since
    since = (datetime.now(UTC) - timedelta(days=60)).date().isoformat()
    hs = client.history(m, since=since)
    assert all(p.date >= since for p in hs.series)
    with pytest.raises(UsageError):
        client.history(m, days=0)
    with pytest.raises(UsageError):
        client.history(m, since="nope")


# --- cash reconstruction ----------------------------------------------------


def test_history_cash_walk_and_invariant():
    m = _logged_in()
    h = client.history(m)
    assert h.cash_events == 9  # all amount-bearing events counted; no-amount skipped
    # cash before the first event is 0 (reconciliation invariant)
    assert h.series[0].cash == "0.00"
    # cash ends at the current cash
    assert h.series[-1].cash == "2234.56"
    # cash never negative mid-series
    assert all(Decimal(p.cash) >= 0 for p in h.series if p.cash)
    # walk: cash is constant between events, steps at event dates
    cash_values = [Decimal(p.cash) for p in h.series]
    diffs = {cash_values[i] - cash_values[i - 1] for i in range(1, len(cash_values))}
    # steps are only at event dates (mock events at 120/100/80/60/50/40/30/20/10 days ago)
    assert (
        len(
            diffs
            - {
                Decimal("0.00"),
                Decimal("3150.00"),
                Decimal("-900.00"),
                Decimal("600.00"),
                Decimal("-150.00"),
                Decimal("-184.40"),
                Decimal("7.63"),
                Decimal("-123.67"),
                Decimal("-15.00"),
            }
        )
        == 0
    )


def test_history_amount_presence_rule_and_invariant():
    """The reconstruction counts every amount-bearing event (the transactions
    feed is the cash-movement feed); no-amount events are skipped; the
    reconciliation invariant (sum(events) == current cash) holds — and would
    break if a cash-moving event were dropped."""
    m = _logged_in()
    events = client._fetch_cash_events(m)
    assert len(events) == 9  # 10 mock items, one without an amount (skipped)
    # invariant: sum(events) == current cash -> residual 0
    h = client.history(m)
    assert h.cash_residual == 0
    assert h.series[0].cash == "0.00"
    assert h.cash_events == 9
    # dropping any cash-moving event breaks the invariant (e.g. the -900 OUTGOING)
    dropped = [events[0]] + events[2:]  # everything except the -900 event
    residual = Decimal("2234.56") - sum(a for _, a, _b in dropped)
    assert residual == Decimal("-900.00")


def test_history_dates_are_utc_days():
    m = _logged_in()
    h = client.history(m)
    dates = [p.date for p in h.series]
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) for d in dates)
    assert dates == sorted(set(dates))


# --- pagination --------------------------------------------------------------


def test_history_timeline_pagination():
    m = _logged_in()
    # 10 mock items (9 with amounts), 3 per page -> 4 pages, all fetched
    events = client._fetch_cash_events(m)
    assert len(events) == 9  # the no-amount informational item is skipped
    # multiple pages were used (mock page size 3)
    page_requests = [
        r for r in m.request_log if r[1] == "/api/v2/timeline/transactions"
    ]
    assert len(page_requests) >= 4


def test_history_deposits_curve():
    """Deposits curve = cumulative net EXTERNAL money flow only: deposits +
    withdrawals + card. Orders, dividends and interest must not move it."""
    m = _logged_in()
    h = client.history(m)
    # before the first money-flow event the curve is 0
    assert h.series[0].deposits == "0.00"
    # external flow only: 3150 - 900 + 600 - 123.67 (card) = 2726.33;
    # orders (-150/-150), dividend (-184.4), interest (7.63), saveback (-15)
    # are internal/income and must NOT move the curve
    assert h.series[-1].deposits == "2726.33"
    assert h.deposits_events == 4
    # steps only at money-flow event dates (mock: 3150 / -900 / 600 / -123.67)
    assert all(p.deposits is not None for p in h.series)
    dep_values = [Decimal(p.deposits) for p in h.series]  # type: ignore[arg-type]
    diffs = {dep_values[i] - dep_values[i - 1] for i in range(1, len(dep_values))}
    assert diffs <= {
        Decimal("0.00"),
        Decimal("3150.00"),
        Decimal("-900.00"),
        Decimal("600.00"),
        Decimal("-123.67"),
    }


def test_history_cli_json_contract(cli_env):
    r = runner.invoke(app, ["login"], env={})
    assert r.exit_code == 0
    r = runner.invoke(app, ["--json", "history"], env={})
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["ok"] is True
    assert data["approximate"] is False
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
    assert data["coverage"]["source"] == "portfolio-chart"
    assert data["coverage"]["cash"] == "reconstructed"
    assert data["series"][0] == {
        "date": data["start_date"],
        "total": data["series"][0]["total"],
        "cash": data["series"][0]["cash"],
        "deposits": data["series"][0]["deposits"],
    }
    assert all(
        "date" in p and "total" in p and "cash" in p and "deposits" in p
        for p in data["series"]
    )
    # privacy: no account numbers anywhere in the output
    blob = json.dumps(data)
    assert "securitiesAccountNumber" not in blob
    assert "cashAccountNumber" not in blob


def test_history_cli_snapshots_file(cli_env, tmp_path):
    snap_file = tmp_path / "snapshots.json"
    snap_file.write_text(
        json.dumps(
            [
                {
                    "date": (datetime.now(UTC) - timedelta(days=5)).date().isoformat(),
                    "total": "88888.00",
                }
            ]
        )
    )
    r = runner.invoke(app, ["login"], env={})
    assert r.exit_code == 0
    r = runner.invoke(app, ["--json", "history", "--snapshots", str(snap_file)], env={})
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["coverage"]["snapshots_merged"] == 1
    assert "snapshots merged: 1" in data["note"]


def test_history_cli_days_limit(cli_env):
    r = runner.invoke(app, ["login"], env={})
    assert r.exit_code == 0
    r = runner.invoke(app, ["history", "--days", "9999"], env={})
    assert r.exit_code == 2
    assert "730" in r.output
