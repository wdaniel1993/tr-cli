import base64
import json

from tr_cli import protocol


def test_device_info_header_is_base64_json_with_stable_device_id():
    encoded = protocol.device_info_header(stable_id="ab" * 32)
    raw = base64.b64decode(encoded)
    device = json.loads(raw)
    assert device["stableDeviceId"] == "ab" * 32
    assert device["browser"] == "Chrome"
    assert "timezone" in device
    assert "numberOfCores" in device


def test_login_headers_shape():
    headers = protocol.login_headers(device_id="cd" * 32, waf_token="waf-token-1")
    assert headers["x-tr-device-info"]
    assert headers["x-tr-app-version"] == protocol.TR_APP_VERSION
    assert headers["x-tr-platform"] == protocol.TR_PLATFORM
    assert headers["x-aws-waf-token"] == "waf-token-1"
    assert headers["Content-Type"] == "application/json"
    assert "User-Agent" in headers


def test_login_headers_without_waf():
    headers = protocol.login_headers()
    assert "x-aws-waf-token" not in headers


def test_ws_connect_message():
    msg = protocol.ws_connect_message()
    assert msg.startswith("connect ")
    import json as _json

    payload = _json.loads(msg.split(" ", 2)[2])
    assert payload["platformId"] == "webtrading"
    assert payload["clientId"] == "app.traderepublic.com"
