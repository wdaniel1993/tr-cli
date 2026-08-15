"""Timeline: fetch + classify the account's event history.

The app's feed is two merged streams (verified live 2026-08-15):
  - `timelineTransactions`: money events — dividends, transfers, interest,
    savings-plan buys — each with a signed `amount {currency, value,
    fractionDigits}` (positive = inflow, negative = outflow/buy/reinvestment).
  - `timelineActivityLog`: reports, corporate actions, account/document events
    (no amounts).
We fetch both over one WS connection, paginating with the `after` cursor from
each topic's `cursors` object, then merge + dedupe by event id and classify
each eventType into a bucket.
"""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from .protocol import (
    TIMELINE_ACTIVITY_LOG_TOPIC,
    TIMELINE_DEFAULT_DAYS,
    TIMELINE_PAGE_LIMIT,
    TIMELINE_TRANSACTIONS_TOPIC,
)
from .transport import Transport

BUCKETS = (
    "deposits",
    "withdrawals",
    "interest",
    "dividends",
    "orders",
    "corporate_actions",
    "documents",
    "other",
)

# Ordered (predicate, bucket) rules — first match wins. Order matters:
# dividends/interest/orders are checked before the looser documents rules.
_CLASSIFY_RULES: list[tuple[tuple[str, ...], str]] = [
    (("DIVIDEND", "DIVIDENDE"), "dividends"),
    (("INTEREST", "ZINSEN"), "interest"),
    (
        (
            "BANK_TRANSACTION_INCOMING",
            "INCOMING_TRANSFER",
            "PAYMENT_INBOUND",
            "DEPOSIT",
            "CASH_TOP",
        ),
        "deposits",
    ),
    (
        (
            "BANK_TRANSACTION_OUTGOING",
            "OUTGOING_TRANSFER",
            "PAYMENT_OUTBOUND",
            "WITHDRAWAL",
            "CASH_PAYOUT",
        ),
        "withdrawals",
    ),
    (
        ("SAVINGSPLAN", "SAVINGS_PLAN", "ORDER", "TRADE_INVOICE", "ORDER_INVOICE"),
        "orders",
    ),
    (
        (
            "CORPORATE_ACTION",
            "SPLIT",
            "SPINOFF",
            "MERGER",
            "TAUSCH",
            "BONUSAKTIE",
            "VORABPAUSCHALE",
        ),
        "corporate_actions",
    ),
    (
        (
            "REPORT",
            "STATEMENT",
            "DOCUMENT",
            "TAX_",
            "QUARTERLY",
            "ANNUAL",
            "LEGAL",
            "TNC",
            "SUITABILITY",
            "INVOICE",
            "CONSENT",
            "PERMISSION",
        ),
        "documents",
    ),
]


def classify(event_type: str | None) -> str:
    """Map an eventType to one of the BUCKETS (unknown -> 'other')."""
    if not event_type:
        return "other"
    upper = event_type.upper()
    for needles, bucket in _CLASSIFY_RULES:
        if any(needle in upper for needle in needles):
            return bucket
    return "other"


def parse_timestamp(ts: str) -> datetime:
    """Parse TR's `2026-08-13T07:05:05.920+0000` timestamps."""
    return datetime.fromisoformat(ts.replace("+0000", "+00:00"))


@dataclass
class TimelineEvent:
    id: str
    timestamp: str
    title: str
    subtitle: str | None
    event_type: str | None
    bucket: str
    amount: dict[str, Any] | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class BucketSummary:
    count: int = 0
    # currency -> Decimal sum of signed amounts
    sums: dict[str, Decimal] = field(default_factory=dict)


@dataclass
class TimelineResult:
    events: list[TimelineEvent] = field(default_factory=list)
    buckets: dict[str, BucketSummary] = field(default_factory=dict)
    pages: int = 0

    @property
    def total_count(self) -> int:
        return len(self.events)


def _next_page_payload(
    key: Hashable, last: Any, *, cutoff: datetime
) -> dict[str, Any] | None:
    """Return the next subscription payload for a topic, or None to stop."""
    if not isinstance(last, dict):
        return None
    items = last.get("items") or []
    if not items:
        return None
    # Stop when every item on this page is older than the cutoff (pages are
    # newest-first).
    timestamps = [i.get("timestamp") for i in items if isinstance(i, dict)]
    if timestamps:
        try:
            newest_ts = min(parse_timestamp(t) for t in timestamps)
            if newest_ts < cutoff:
                return None
        except (ValueError, TypeError):
            pass
    cursors = last.get("cursors") or {}
    after = cursors.get("after")
    if not after:
        return None
    topic = TIMELINE_TRANSACTIONS_TOPIC if key == "tx" else TIMELINE_ACTIVITY_LOG_TOPIC
    return {"type": topic, "limit": TIMELINE_PAGE_LIMIT, "after": after}


def fetch_timeline(
    transport: Transport,
    *,
    days: int = TIMELINE_DEFAULT_DAYS,
    timeout: float = 8.0,
    max_rounds: int = 25,
) -> TimelineResult:
    """Fetch both timeline topics, paginate to the cutoff, merge + classify."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)

    rounds = transport.ws_paginate(
        [
            ("tx", {"type": TIMELINE_TRANSACTIONS_TOPIC, "limit": TIMELINE_PAGE_LIMIT}),
            (
                "log",
                {"type": TIMELINE_ACTIVITY_LOG_TOPIC, "limit": TIMELINE_PAGE_LIMIT},
            ),
        ],
        next_payload=lambda key, last: _next_page_payload(key, last, cutoff=cutoff),
        timeout=timeout,
        max_rounds=max_rounds,
    )
    pages = max((len(v) for v in rounds.values()), default=0)

    seen: set[str] = set()
    events: list[TimelineEvent] = []
    for key in ("tx", "log"):
        for payload in rounds.get(key, []):
            if not isinstance(payload, dict):
                continue
            for item in payload.get("items") or []:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                eid = str(item["id"])
                if eid in seen:
                    continue
                ts = item.get("timestamp") or ""
                try:
                    if parse_timestamp(ts) < cutoff:
                        continue
                except (ValueError, TypeError):
                    pass  # unparseable timestamp: keep the item
                seen.add(eid)
                events.append(
                    TimelineEvent(
                        id=eid,
                        timestamp=ts,
                        title=str(item.get("title") or ""),
                        subtitle=item.get("subtitle"),
                        event_type=item.get("eventType"),
                        bucket=classify(item.get("eventType")),
                        amount=item.get("amount")
                        if isinstance(item.get("amount"), dict)
                        else None,
                        raw=item,
                    )
                )

    events.sort(key=lambda e: e.timestamp, reverse=True)

    buckets: dict[str, BucketSummary] = {b: BucketSummary() for b in BUCKETS}
    for ev in events:
        summary = buckets[ev.bucket]
        summary.count += 1
        if ev.amount:
            currency = str(ev.amount.get("currency") or "?")
            try:
                summary.sums[currency] = summary.sums.get(
                    currency, Decimal(0)
                ) + Decimal(str(ev.amount.get("value")))
            except (ValueError, TypeError, ArithmeticError):
                pass
    return TimelineResult(events=events, buckets=buckets, pages=pages)
