import os
import stat

import pytest

from tr_cli import session as session_mod
from tr_cli.auth import (
    ApprovalTimeout,
    LoginFailed,
    RateLimited,
    initiate_login,
    login_flow,
    refresh_session,
)
from tr_cli.mock import MockTransport

PHONE = "+491234567890"
PIN = "1234"
DEVICE_ID = "ab" * 32


def test_login_flow_harvests_cookies(mock_transport):
    result = login_flow(mock_transport, PHONE, PIN, DEVICE_ID)
    assert result.process_id.startswith("mock-process")
    assert "JSESSIONID" in result.cookies
    assert "tr_refresh" in result.cookies
    assert "tr_device" in result.cookies
    assert "tr_session" in result.cookies


def test_login_flow_rate_limited():
    m = MockTransport(mode="rate_limited")
    with pytest.raises(RateLimited) as exc:
        login_flow(m, PHONE, PIN, DEVICE_ID)
    assert exc.value.wait_seconds == 600
    assert (
        "cooldown" in str(exc.value).lower()
        or "rate-limiting" in str(exc.value).lower()
    )


def test_login_flow_approval_timeout():
    m = MockTransport(mode="pending_forever")
    with pytest.raises(ApprovalTimeout):
        login_flow(m, PHONE, PIN, DEVICE_ID, timeout=1.0, interval=0.1)


def test_login_flow_invalid_credentials():
    m = MockTransport(mode="invalid_creds")
    with pytest.raises(LoginFailed) as exc:
        login_flow(m, PHONE, PIN, DEVICE_ID)
    assert "PIN_INVALID" in str(exc.value) or "rejected" in str(exc.value).lower()


def test_initiate_requires_process_id():
    class Weird:
        def request(self, *a, **k):
            from tr_cli.transport import HttpResponse

            return HttpResponse(status_code=200, body="{}")

    with pytest.raises(LoginFailed):
        initiate_login(Weird(), PHONE, PIN, DEVICE_ID)


def test_session_save_chmod_600(tmp_path):
    cookies = {"JSESSIONID": "j", "tr_refresh": "r", "tr_device": "d"}
    n = session_mod.save_cookies(cookies, tmp_path)
    path = session_mod.cookies_path(tmp_path)
    assert n == 3
    assert path.is_file()
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600
    loaded = session_mod.load_cookies(tmp_path)
    assert (
        loaded["tr_session"] if "tr_session" in cookies else loaded["JSESSIONID"] == "j"
    )


def test_session_roundtrip_and_summary(tmp_path):
    cookies = {"JSESSIONID": "j", "tr_refresh": "r", "tr_device": "d", "tr_claims": "c"}
    session_mod.save_cookies(cookies, tmp_path)
    loaded = session_mod.load_cookies(tmp_path)
    assert loaded == cookies
    summary = session_mod.summarize(loaded)
    assert summary["required_present"] == ["JSESSIONID", "tr_device", "tr_refresh"]
    assert summary["required_missing"] == []
    assert "tr_claims" in summary["useful_present"]


def test_device_id_persisted(tmp_path):
    session_mod.save_device_id("ef" * 32, tmp_path)
    assert session_mod.load_device_id(tmp_path) == "ef" * 32


def test_refresh_rotates_cookies(tmp_path):
    m = MockTransport()
    result = login_flow(m, PHONE, PIN, DEVICE_ID)
    session_mod.save_cookies(result.cookies, tmp_path)
    # a fresh transport seeded from disk
    m2 = MockTransport(initial_cookies=session_mod.load_cookies(tmp_path))
    before = m2.cookies_snapshot()
    out = refresh_session(m2, DEVICE_ID)
    assert out["ok"] is True
    after = m2.cookies_snapshot()
    assert after["tr_session"] != before["tr_session"]
    assert after["JSESSIONID"] != before["JSESSIONID"]
