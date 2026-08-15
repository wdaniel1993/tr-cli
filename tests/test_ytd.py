from tr_cli import client
from tr_cli.mock import MockTransport

PHONE = "+491234567890"
PIN = "1234"
DEVICE_ID = "ab" * 32


def _logged_in(mode: str | None = None):
    m = MockTransport(mode=mode)
    from tr_cli.auth import login_flow

    login_flow(m, PHONE, PIN, DEVICE_ID)
    return m


def test_ytd_math():
    m = _logged_in()
    pf = client.portfolio(m)
    by_id = {p.instrument_id: p for p in pf.positions}
    apple = by_id["US0378331005"]  # netSize 10, price 232.05, base 100.0
    assert apple.ytd_base_price == "100.0"
    assert str(apple.ytd_gain) == "1320.50"
    assert str(apple.ytd_pct) == "132.05"
    db = by_id["DE0005140008"]  # netSize 5, price 16.44, base 100.0
    assert str(db.ytd_gain) == "-417.80"
    # portfolio total
    assert str(pf.ytd_total) == "902.70"


def test_ytd_missing_series_is_null():
    m = _logged_in()
    m.missing_tickers.add(
        "US0378331005.LSX"
    )  # ticker never answers -> price stays None
    pf = client.portfolio(m)
    by_id = {p.instrument_id: p for p in pf.positions}
    # the missing ticker position still has exchangeIds from instrument; but ticker missing
    # means price is None -> ytd must be None (not a fake number)
    assert by_id["US0378331005"].ytd_gain is None
    assert by_id["US0378331005"].ytd_base_price is None
    assert pf.ytd_total is not None  # other position still contributes


def test_ytd_all_missing_is_null_total():
    m = _logged_in()
    m.missing_tickers.update({"US0378331005.LSX", "DE0005140008.LSX"})
    pf = client.portfolio(m)
    assert pf.ytd_total is None
    assert all(p.ytd_gain is None for p in pf.positions)


def test_portfolio_backward_compat():
    m = _logged_in()
    pf = client.portfolio(m)
    assert len(pf.positions) == 2
    assert str(pf.total_value) == "2402.70"  # unchanged semantics
    assert str(pf.cash.total) == "2234.56"
