import pytest

from tr_cli import client
from tr_cli.errors import NeedsLogin
from tr_cli.mock import MockTransport

PHONE = "+491234567890"
PIN = "1234"
DEVICE_ID = "ab" * 32


def _logged_in():
    m = MockTransport()
    from tr_cli.auth import login_flow

    login_flow(m, PHONE, PIN, DEVICE_ID)
    return m


def test_account_gives_sec_acc_no():
    m = _logged_in()
    acct = client.account(m)
    assert acct.securities_account_number == "1234567890123"


def test_account_401_raises_needs_login():
    m = MockTransport(mode="expired_session")
    with pytest.raises(NeedsLogin):
        client.account(m)


def test_portfolio_assembly():
    m = _logged_in()
    p = client.portfolio(m)
    assert len(p.positions) == 2
    by_id = {pos.instrument_id: pos for pos in p.positions}
    apple = by_id["US0378331005"]
    assert apple.name == "Apple"
    assert apple.price == "232.05"
    assert apple.net_value is not None and str(apple.net_value) == "2320.50"
    assert str(p.total_value) == "2402.70"
    assert p.cash.total == "1234.56"
    assert p.cash.available == "1000.00"


def test_portfolio_missing_ticker():
    m = _logged_in()
    m.missing_tickers.add("US0378331005.LSX")
    p = client.portfolio(m)
    by_id = {pos.instrument_id: pos for pos in p.positions}
    assert by_id["US0378331005"].price is None
    assert by_id["DE0005140008"].price == "16.44"
    # total only counts valued positions
    assert str(p.total_value) == "82.20"


def test_rates():
    m = _logged_in()
    quotes = client.rates(m, ["US0378331005", "DE0005140008"])
    assert len(quotes) == 2
    q = quotes[0]
    assert q.name == "Apple"
    assert q.price == "232.05"
    assert q.ask == "232.1"


def test_rates_missing_price():
    m = _logged_in()
    m.missing_tickers.add("DE0005140008.LSX")
    quotes = client.rates(m, ["US0378331005", "DE0005140008"])
    by_id = {q.instrument_id: q for q in quotes}
    assert by_id["DE0005140008"].price is None


def test_details_partial():
    m = _logged_in()
    topics = client.details(m, "US0378331005")
    assert "instrument" in topics
    assert "stockDetails" in topics
    assert "ticker" in topics
    assert "performance" in topics
    assert "neonNews" in topics
    # unknown ISIN -> only topics that answered
    topics2 = client.details(m, "XX0000000000")
    assert "instrument" not in topics2
