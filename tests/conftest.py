import os
import sys

import pytest

sys.path.insert(0, str(os.path.dirname(__file__) + "/../src"))

from tr_cli.mock import MockTransport


@pytest.fixture
def mock_transport():
    return MockTransport()


@pytest.fixture
def logged_in_mock(tmp_path, monkeypatch):
    """MockTransport with a completed mock login (cookies set)."""
    m = MockTransport()
    from tr_cli.auth import login_flow

    result = login_flow(m, "+491234567890", "1234", "dev" * 21 + "d" * 1)
    assert result.cookies, "mock login should harvest cookies"
    return m


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    """Env for CLI tests: isolated TR_CLI_DIR + mock mode + creds."""
    monkeypatch.setenv("TR_CLI_DIR", str(tmp_path))
    monkeypatch.setenv("TR_CLI_MOCK", "1")
    monkeypatch.setenv("TR_PHONE", "+491234567890")
    monkeypatch.setenv("TR_PIN", "1234")
    monkeypatch.delenv("TR_CLI_MOCK_MODE", raising=False)
    return tmp_path
