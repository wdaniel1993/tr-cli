import json

from typer.testing import CliRunner

from tr_cli.cli import app

runner = CliRunner()


def run(*args, env=None, **kw):
    return runner.invoke(app, list(args), env=env or {}, **kw)


def test_login_and_data_commands(cli_env):
    r = run("login")
    assert r.exit_code == 0, r.output
    assert "Session saved" in r.output

    r = run("session", "status")
    assert r.exit_code == 0
    assert "JSESSIONID" in r.output

    r = run("portfolio")
    assert r.exit_code == 0, r.output
    assert "Apple" in r.output
    assert "TOTAL VALUE (positions only)" in r.output
    assert "EUR: 1234.56" in r.output
    assert "USD: 1000" in r.output

    r = run("rates", "US0378331005", "DE0005140008")
    assert r.exit_code == 0, r.output
    assert "Apple" in r.output and "Deutsche Bank" in r.output

    r = run("details", "US0378331005")
    assert r.exit_code == 0, r.output
    assert "Apple Inc." in r.output
    assert "QUOTE" in r.output

    r = run("session", "refresh")
    assert r.exit_code == 0, r.output
    assert "Rotated cookies" in r.output


def test_json_output(cli_env):
    r = run("login")
    assert r.exit_code == 0
    r = run("--json", "portfolio")
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["ok"] is True
    assert data["totalValue"] == "2402.70"
    assert len(data["positions"]) == 2
    assert data["cash"]["items"] == [
        {"currencyId": "EUR", "amount": "1234.56"},
        {"currencyId": "USD", "amount": "1000.0"},
    ]
    assert data["cash"]["total"] == "2234.56"
    assert all("accountNumber" not in item for item in data["cash"]["items"])


def test_rate_limit_message(cli_env, monkeypatch):
    monkeypatch.setenv("TR_CLI_MOCK_MODE", "rate_limited")
    r = run("login")
    assert r.exit_code == 4
    assert "rate-limiting" in r.output.lower()
    assert "600" in r.output


def test_approval_timeout_exit(cli_env, monkeypatch):
    monkeypatch.setenv("TR_CLI_MOCK_MODE", "pending_forever")
    monkeypatch.setenv("TR_LOGIN_TIMEOUT", "0.6")
    r = run("--json", "login")
    assert r.exit_code == 5, r.output
    assert "approve" in r.output.lower()


def test_expired_session(cli_env, monkeypatch):
    r = run("login")
    assert r.exit_code == 0
    monkeypatch.setenv("TR_CLI_MOCK_MODE", "expired_session")
    r = run("portfolio")
    assert r.exit_code == 3
    assert "tr-cli login" in r.output


def test_invalid_isin_usage(cli_env):
    r = run("rates", "not-an-isin")
    assert r.exit_code == 2
    assert "No valid ISINs" in r.output


def test_rates_json(cli_env):
    r = run("login")
    assert r.exit_code == 0
    r = run("--json", "rates", "US0378331005,DE0005140008")
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert len(data["quotes"]) == 2


def test_details_json(cli_env):
    r = run("login")
    assert r.exit_code == 0
    r = run("--json", "details", "US0378331005")
    assert r.exit_code == 0
    data = json.loads(r.output)
    assert data["topics"]["instrument"]["shortName"] == "Apple"


def test_timeline_command(cli_env):
    r = run("login")
    assert r.exit_code == 0
    r = run("timeline")
    assert r.exit_code == 0, r.output
    assert "TIMELINE" in r.output
    assert "dividends" in r.output
    assert "deposits" in r.output
    assert "-184.40 EUR" in r.output  # dividend amount
    assert "+600.00 EUR" in r.output  # incoming transfer
    assert "BUCKET SUMS" in r.output


def test_timeline_json(cli_env):
    r = run("login")
    assert r.exit_code == 0
    r = run("--json", "timeline")
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["ok"] is True
    assert data["window_days"] == 90
    types = {e["eventType"] for e in data["events"]}
    assert "SSP_CORPORATE_ACTION_DIVIDEND_EQUIVALENT" in types  # transactions stream
    assert "EX_POST_COST_REPORT_CREATED" in types  # activity-log stream
    amt_events = [e for e in data["events"] if e["amount"]]
    assert amt_events and amt_events[0]["amount"]["currency"] == "EUR"
    assert data["buckets"]["dividends"]["sum"] == {"EUR": "-184.4"}


def test_timeline_bucket_filter(cli_env):
    r = run("login")
    assert r.exit_code == 0
    r = run("timeline", "--bucket", "dividends")
    assert r.exit_code == 0, r.output
    assert "dividends" in r.output
    assert "BANK_TRANSACTION_INCOMING" not in r.output
    r = run("timeline", "--bucket", "bogus")
    assert r.exit_code == 2


def test_portfolio_ytd_json(cli_env):
    r = run("login")
    assert r.exit_code == 0
    r = run("--json", "portfolio")
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["ytdTotal"] == "902.70"
    pos = data["positions"][0]
    assert pos["ytd"]["basePrice"] == "100.0"
    assert "gain" in pos["ytd"] and "pct" in pos["ytd"]
    # backward compat: old fields still present
    assert data["totalValue"] == "2402.70"
    assert len(data["positions"]) == 2


def test_portfolio_human_ytd_line(cli_env):
    r = run("login")
    assert r.exit_code == 0
    r = run("portfolio")
    assert r.exit_code == 0, r.output
    assert "YTD 2026" in r.output
