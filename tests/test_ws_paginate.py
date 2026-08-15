"""Tests for the multi-round WS pagination helper."""

import asyncio

from tr_cli import ws


class FakeWS:
    def __init__(self, rounds):
        """rounds: list of (connect_reply + frames) batches per round."""
        self._batches = list(rounds)
        self.sent = []
        self.sent_count = 0

    async def send(self, message):
        self.sent.append(message)
        self.sent_count += 1

    async def recv(self):
        while self._batches and not self._batches[0]:
            self._batches.pop(0)
        if self._batches:
            return self._batches[0].pop(0)
        await asyncio.sleep(0.05)
        raise TimeoutError()

    async def close(self):
        pass


class FakeConnector:
    def __init__(self, batches):
        self.batches = batches

    async def __call__(self, url, **kwargs):
        self.kwargs = kwargs
        self.connected_ws = FakeWS(self.batches)
        return self.connected_ws


def _connector(round_frames):
    # only the first round's batch carries the `connected` greeting
    batches = [["connected", *round_frames[0]]] + [[*f] for f in round_frames[1:]]
    return FakeConnector(batches)


def test_paginate_two_rounds(monkeypatch):
    ws._counter = 0
    # round 1: both topics answer with a cursor; round 2: both answer, no more cursors -> stop
    frames_r1 = [
        '1 A {"items":[{"id":"a"}],"cursors":{"after":"c1"}}',
        '2 A {"items":[{"id":"b"}],"cursors":{"after":"c2"}}',
    ]
    frames_r2 = [
        '3 A {"items":[{"id":"c"}],"cursors":{"after":null}}',
        '4 A {"items":[{"id":"d"}],"cursors":{"after":null}}',
    ]
    fake = _connector([frames_r1, frames_r2])
    monkeypatch.setattr(ws.websockets, "connect", fake)

    class T:
        pass

    def next_payload(key, last):
        after = (last.get("cursors") or {}).get("after")
        if not after:
            return None
        return {"type": "x", "after": after}

    results = ws.paginate(
        [
            ("tx", {"type": "timelineTransactions"}),
            ("log", {"type": "timelineActivityLog"}),
        ],
        cookie_str="JSESSIONID=x",
        next_payload=next_payload,
        timeout=2.0,
    )
    assert [i["id"] for i in results["tx"][0]["items"]] == ["a"]
    assert [i["id"] for i in results["tx"][1]["items"]] == ["c"]
    assert [i["id"] for i in results["log"][0]["items"]] == ["b"]
    assert (
        len(results["log"]) == 2
    )  # round 2 answered too, then cursor exhausted -> stop
    # 1 connect + 2 subs (round 1) + 2 subs (round 2) + 4 unsubs
    assert fake.connected_ws.sent_count >= 9


def test_paginate_stops_when_no_reply(monkeypatch):
    ws._counter = 0
    # only the tx topic answers round 1 (log gets no reply); next_payload always asks for more
    frames = ['1 A {"items":[{"id":"a"}],"cursors":{"after":"c1"}}']
    fake = _connector([frames])
    monkeypatch.setattr(ws.websockets, "connect", fake)

    class T:
        pass

    results = ws.paginate(
        [
            ("tx", {"type": "timelineTransactions"}),
            ("log", {"type": "timelineActivityLog"}),
        ],
        cookie_str="",
        next_payload=lambda key, last: {"type": "x"},
        timeout=0.5,
        max_rounds=3,
    )
    assert "tx" in results and len(results["tx"]) == 1
    assert "log" not in results or results["log"] == []
