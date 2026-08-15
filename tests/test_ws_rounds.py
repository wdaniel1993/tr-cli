"""Tests for the single-connection sequential-rounds helper."""

import asyncio

from tr_cli import ws


class FakeWS:
    def __init__(self, batches):
        self._batches = list(batches)
        self.sent = []

    async def send(self, message):
        self.sent.append(message)

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
        self.connected_ws = FakeWS(self.batches)
        return self.connected_ws


def _connector(round_frames):
    batches = [["connected", *round_frames[0]]] + [[*f] for f in round_frames[1:]]
    return FakeConnector(batches)


def test_rounds_static(monkeypatch):
    ws._counter = 0
    frames = [
        '1 A {"type":"compactPortfolioByType"}',
        '2 A {"type":"cash"}',
        '3 A {"type":"instrument","id":"X"}',
    ]
    fake = _connector([frames[:2], frames[2:]])
    monkeypatch.setattr(ws.websockets, "connect", fake)

    results = ws.rounds(
        [
            [("pf", {"type": "compactPortfolioByType"}), ("cash", {"type": "cash"})],
            [("inst", {"type": "instrument", "id": "X"})],
        ],
        cookie_str="",
    )
    assert results[0]["pf"]["type"] == "compactPortfolioByType"
    assert results[0]["cash"]["type"] == "cash"
    assert results[1]["inst"]["id"] == "X"


def test_rounds_builder_dependency(monkeypatch):
    """Round 2 payload depends on round 1's reply — still one connection."""
    ws._counter = 0
    frames = [
        '1 A {"positions":[{"isin":"X"}]}',
        '2 A {"exchangeIds":["LSX"]}',
        '3 A {"aggregates":[{"time":1,"close":2}]}',
    ]
    fake = _connector([frames[:1], frames[1:2], frames[2:]])
    monkeypatch.setattr(ws.websockets, "connect", fake)

    def builder(r_index, so_far):
        if r_index == 0:
            return [("pf", {"type": "compactPortfolioByType"})]
        if r_index == 1:
            return [
                (
                    "inst",
                    {
                        "type": "instrument",
                        "id": so_far[0]["pf"]["positions"][0]["isin"],
                    },
                )
            ]
        if r_index == 2:
            ex = so_far[1]["inst"]["exchangeIds"][0]
            return [("series", {"type": "tradeAggregateHistory", "exchangeId": ex})]
        return None

    results = ws.rounds(builder, cookie_str="")
    assert results[0]["pf"]["positions"][0]["isin"] == "X"
    assert results[1]["inst"]["exchangeIds"] == ["LSX"]
    assert results[2]["series"]["aggregates"][0]["close"] == 2
    # all rounds on ONE connection: exactly one connect message sent
    connects = [s for s in fake.connected_ws.sent if s.startswith("connect")]
    assert len(connects) == 1
