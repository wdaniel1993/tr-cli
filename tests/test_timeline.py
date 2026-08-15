
from tr_cli import timeline
from tr_cli.mock import MockTransport

PHONE = "+491234567890"
PIN = "1234"
DEVICE_ID = "ab" * 32


def _logged_in(mode: str | None = None):
    m = MockTransport(mode=mode)
    from tr_cli.auth import login_flow

    login_flow(m, PHONE, PIN, DEVICE_ID)
    return m


def test_classify():
    assert timeline.classify("BANK_TRANSACTION_INCOMING") == "deposits"
    assert timeline.classify("BANK_TRANSACTION_OUTGOING") == "withdrawals"
    assert timeline.classify("INTEREST_PAYOUT") == "interest"
    assert timeline.classify("SSP_CORPORATE_ACTION_DIVIDEND_EQUIVALENT") == "dividends"
    assert timeline.classify("TRADING_SAVINGSPLAN_EXECUTED") == "orders"
    assert timeline.classify("ORDER_REJECTED") == "orders"
    assert timeline.classify("SSP_CORPORATE_ACTION_INFORMATIVE") == "corporate_actions"
    assert timeline.classify("TAX_YEAR_END_REPORT_CREATED") == "documents"
    assert timeline.classify("DOCUMENTS_ACCEPTED") == "documents"
    assert timeline.classify("SOME_UNKNOWN_EVENT") == "other"
    assert timeline.classify(None) == "other"


def test_timeline_merges_and_dedupes():
    m = _logged_in()
    result = timeline.fetch_timeline(m, days=90)
    ids = [e.id for e in result.events]
    assert len(ids) == len(set(ids)), "duplicate event ids"
    # both streams present
    types = {e.event_type for e in result.events}
    assert "SSP_CORPORATE_ACTION_DIVIDEND_EQUIVALENT" in types  # from transactions
    assert "EX_POST_COST_REPORT_CREATED" in types  # from activity log
    # sorted newest first
    stamps = [e.timestamp for e in result.events]
    assert stamps == sorted(stamps, reverse=True)
    # 90-day cutoff: tx-10 (120d) and log-08 (150d) excluded
    titles = {e.title for e in result.events}
    assert "Wallner  Daniel" in titles
    assert "Customer created" not in titles
    # pagination happened (multi-page)
    assert result.pages >= 2


def test_timeline_amounts():
    m = _logged_in()
    result = timeline.fetch_timeline(m, days=90)
    dividend = next(
        e
        for e in result.events
        if e.event_type == "SSP_CORPORATE_ACTION_DIVIDEND_EQUIVALENT"
    )
    assert dividend.amount == {"currency": "EUR", "value": -184.4, "fractionDigits": 2}
    # activity-log events have no amount
    report = next(
        e for e in result.events if e.event_type == "EX_POST_COST_REPORT_CREATED"
    )
    assert report.amount is None


def test_timeline_bucket_sums():
    m = _logged_in()
    result = timeline.fetch_timeline(m, days=90)
    deposits = result.buckets["deposits"]
    assert deposits.count == 2
    assert str(deposits.sums["EUR"]) == "5600.0"  # 600 + 5000
    dividends = result.buckets["dividends"]
    assert dividends.count == 1
    assert str(dividends.sums["EUR"]) == "-184.4"
    assert result.buckets["other"].count == 1  # SOME_UNKNOWN_EVENT_TYPE


def test_timeline_unknown_types_included():
    m = _logged_in()
    result = timeline.fetch_timeline(m, days=90)
    assert any(e.bucket == "other" for e in result.events)


def test_parse_timestamp():
    dt = timeline.parse_timestamp("2026-08-13T07:05:05.920+0000")
    assert dt.year == 2026 and dt.month == 8 and dt.day == 13
