"""Tests for the WS collect loop using a fake websocket."""

import asyncio

from tr_cli import ws


class FakeWS:
    """Minimal stand-in for websockets.connect return value."""

    def __init__(self, responses):
        # responses: list of frames to emit in order after `connect`
        self._responses = list(responses)
        self.sent = []

    async def send(self, message):
        self.sent.append(message)

    async def recv(self):
        if self._responses:
            return self._responses.pop(0)
        await asyncio.sleep(0.05)
        raise TimeoutError()

    async def close(self):
        self.closed = True


class FakeConnector:
    """Monkeypatches websockets.connect with a FakeWS."""

    def __init__(self, responses):
        self.responses = responses
        self.connected_ws = None

    async def __call__(self, url, **kwargs):
        self.url = url
        self.kwargs = kwargs
        fw = FakeWS(self.responses)
        self.connected_ws = fw
        return fw


def test_collect_full_responses(monkeypatch):
    frames = [
        "connected",
        '1 A {"type":"cash","total":"10"}',
        '2 A {"type":"instrument","id":"US0378331005"}',
    ]
    fake = FakeConnector(frames)
    monkeypatch.setattr(ws.websockets, "connect", fake)

    class T:
        pass

    ws._counter = 0
    results = ws.collect(
        T(),
        [
            ("cash", {"type": "cash"}),
            ("inst", {"type": "instrument", "id": "US0378331005"}),
        ],
        cookie_str="JSESSIONID=x",
    )
    assert results["cash"]["total"] == "10"
    assert results["inst"]["id"] == "US0378331005"
    # unsub sent for both
    unsubs = [s for s in fake.connected_ws.sent if s.startswith("unsub")]
    assert len(unsubs) == 2
    # cookie header attached
    assert "Cookie" in fake.kwargs.get("additional_headers", {})


def test_collect_delta_response(monkeypatch):
    full = '{"type":"ticker","last":{"price":"1.0"}}'
    delta = '+{"type":"ticker","last":{"price":"2.0"}}'
    frames = ["connected", f"1 A {full}", f"2 D {delta}"]
    fake = FakeConnector(frames)
    monkeypatch.setattr(ws.websockets, "connect", fake)

    class T:
        pass

    ws._counter = 0
    results = ws.collect(T(), [("a", {"type": "ticker"}), ("b", {"type": "ticker"})])
    assert results["b"]["last"]["price"] == "2.0"


def test_collect_timeout_missing(monkeypatch):
    frames = ["connected", '1 A {"type":"cash"}']  # subscription 2 never answers
    fake = FakeConnector(frames)
    monkeypatch.setattr(ws.websockets, "connect", fake)

    class T:
        pass

    ws._counter = 0
    results = ws.collect(
        T(), [("a", {"type": "cash"}), ("b", {"type": "ticker"})], timeout=0.5
    )
    assert "a" in results
    assert "b" not in results
