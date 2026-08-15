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
    assert "TOTAL VALUE" in r.output

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
