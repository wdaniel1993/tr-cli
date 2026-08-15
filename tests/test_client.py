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
    assert [(i.currency_id, i.amount) for i in p.cash.items] == [
        ("EUR", "1234.56"),
        ("USD", "1000.0"),
    ]
    assert str(p.cash.total) == "2234.56"
    assert str(p.cash.amount_for("EUR")) == "1234.56"


def test_portfolio_empty():
    m = MockTransport(mode="empty_portfolio")
    from tr_cli.auth import login_flow

    login_flow(m, PHONE, PIN, DEVICE_ID)
    pf = client.portfolio(m)
    assert pf.positions == []
    assert str(pf.total_value) == "0.00"
    assert str(pf.cash.total) == "2234.56"


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


def test_parse_cash_array_shape():
    """Real wire shape: array of {accountNumber, currencyId, amount}."""
    cash = client._parse_cash(
        [{"accountNumber": "0123456789", "currencyId": "EUR", "amount": 1234.56}]
    )
    assert len(cash.items) == 1
    assert cash.items[0].currency_id == "EUR"
    assert cash.items[0].amount == "1234.56"
    assert cash.items[0].account_number == "0123456789"
    assert str(cash.total) == "1234.56"


def test_parse_cash_multicurrency_aggregation():
    cash = client._parse_cash(
        [
            {"accountNumber": "1", "currencyId": "EUR", "amount": 10.5},
            {"accountNumber": "2", "currencyId": "USD", "amount": 20},
            {"accountNumber": "3", "currencyId": "EUR", "amount": 1.25},
        ]
    )
    assert str(cash.total) == "31.75"
    assert str(cash.amount_for("EUR")) == "11.75"
    assert cash.amount_for("USD") == 20


def test_parse_cash_defensive_shapes():
    # single dict with amount -> one item
    cash = client._parse_cash({"currencyId": "EUR", "amount": "5.0"})
    assert cash.items[0].currency_id == "EUR" and cash.items[0].amount == "5.0"
    # legacy {total, available} dict -> one unknown-currency item (never zeroes out)
    cash = client._parse_cash({"total": "7.0", "available": "7.0"})
    assert str(cash.total) == "7.00"
    # junk -> empty
    assert client._parse_cash(None).items == []
    assert client._parse_cash("nope").items == []
    assert client._parse_cash([{"foo": "bar"}]).items == []
