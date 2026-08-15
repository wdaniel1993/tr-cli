"""Human-readable rendering (stdlib only, fixed-width tables)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .client import Portfolio, Quote

FMT = "{:<28} {:<14} {:>10} {:>10} {:>10} {:>12}"


def _num(value: str | None, precision: int = 2) -> str:
    if value is None:
        return "-"
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return (
        f"{f:.{precision}f}".rstrip("0").rstrip(".")
        if "." in f"{f:.{precision}f}"
        else f"{f:.{precision}f}"
    )


def render_portfolio(portfolio: Portfolio) -> str:
    lines: list[str] = []
    lines.append("PORTFOLIO")
    if portfolio.positions:
        lines.append(FMT.format("Name", "ISIN", "qty", "price", "avgCost", "netValue"))
        for pos in portfolio.positions:
            lines.append(
                FMT.format(
                    pos.name or pos.instrument_id,
                    pos.instrument_id,
                    _num(pos.net_size, 4),
                    _num(pos.price, 4),
                    _num(pos.average_buy_in, 4),
                    _num(str(pos.net_value) if pos.net_value is not None else None, 2),
                )
            )
        missing = [p.instrument_id for p in portfolio.positions if p.price is None]
        if missing:
            lines.append("")
            lines.append(f"No price received for: {', '.join(missing)}")
    else:
        lines.append("(no positions)")
    lines.append("")
    cash = portfolio.cash
    if cash.items:
        lines.append("CASH (available, per currency)")
        for item in cash.items:
            lines.append(f"  {item.currency_id}: {_num(item.amount, 2)}")
        if len(cash.items) > 1:
            lines.append(f"  TOTAL: {_num(str(cash.total), 2)}")
    else:
        lines.append("CASH: (none)")
    lines.append("")
    lines.append(f"TOTAL VALUE (positions only): {portfolio.total_value}")
    return "\n".join(lines)


def render_rates(quotes: list[Quote]) -> str:
    if not quotes:
        return "No quotes."
    lines = ["{:<28} {:<14} {:>10} {:>10}".format("Name", "ISIN", "price", "ask")]
    for q in quotes:
        lines.append(
            f"{q.name or q.instrument_id:<28} {q.instrument_id:<14} {_num(q.price, 4):>10} {_num(q.ask, 4):>10}"
        )
    missing = [q.instrument_id for q in quotes if q.price is None]
    if missing:
        lines.append("")
        lines.append(f"No price received for: {', '.join(missing)}")
    return "\n".join(lines)


def _pretty(obj: Any, indent: int = 0) -> list[str]:
    """Render a nested JSON-ish object as 'key: value' lines."""
    out: list[str] = []
    pad = " " * indent
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                out.append(f"{pad}{k}:")
                out.extend(_pretty(v, indent + 2))
            else:
                out.append(f"{pad}{k}: {v}")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                out.extend(_pretty(item, indent + 2))
            else:
                out.append(f"{pad}- {item}")
    else:
        out.append(f"{pad}{obj}")
    return out


def render_details(isin: str, topics: dict[str, Any]) -> str:
    lines: list[str] = [f"DETAILS {isin}"]
    instrument = topics.get("instrument")
    if isinstance(instrument, dict):
        lines.append("")
        lines.append("INSTRUMENT")
        for key in ("name", "shortName", "typeId", "currency"):
            if instrument.get(key) is not None:
                lines.append(f"  {key}: {instrument[key]}")
        exchanges = instrument.get("exchanges") or []
        if exchanges:
            slugs = [
                f"{e.get('slug')}({e.get('symbolAtExchange')})"
                for e in exchanges
                if isinstance(e, dict)
            ]
            lines.append(f"  exchanges: {', '.join(slugs) if slugs else exchanges}")
        tags = instrument.get("tags") or []
        if tags:
            lines.append(
                f"  tags: {', '.join(f'{t.get("type")}:{t.get("name")}' for t in tags if isinstance(t, dict))}"
            )

    ticker = topics.get("ticker")
    if isinstance(ticker, dict):
        last = ticker.get("last") or {}
        ask = ticker.get("ask") or {}
        bid = ticker.get("bid") or {}
        lines.append("")
        lines.append("QUOTE")
        if isinstance(last, dict):
            lines.append(f"  last: {last.get('price')}")
        if isinstance(ask, dict):
            lines.append(f"  ask: {ask.get('price')}")
        if isinstance(bid, dict):
            lines.append(f"  bid: {bid.get('price')}")

    stock = topics.get("stockDetails")
    if isinstance(stock, dict):
        lines.append("")
        lines.append("COMPANY")
        lines.extend(_pretty(stock, 2))

    news = topics.get("neonNews")
    if isinstance(news, list):
        lines.append("")
        lines.append("NEWS")
        for item in news[:5]:
            if not isinstance(item, dict):
                continue
            created = item.get("createdAt")
            date_str = "?"
            if isinstance(created, (int, float)):
                try:
                    date_str = datetime.fromtimestamp(created / 1000, tz=UTC).isoformat(
                        timespec="minutes"
                    )
                except (OverflowError, OSError, ValueError):
                    date_str = str(created)
            lines.append(f"  {date_str}: {item.get('headline', '')}")

    perf = topics.get("performance")
    if isinstance(perf, dict):
        lines.append("")
        lines.append(f"PERFORMANCE  range: {perf.get('range')}")
        points = perf.get("perf") or []
        lines.append(f"  data points: {len(points)}")

    received = set(topics)
    wanted = {
        "instrument",
        "stockDetails",
        "ticker",
        "performance",
        "instrumentSuitability",
        "neonNews",
    }
    missing = sorted(wanted - received)
    if missing:
        lines.append("")
        lines.append(f"No data for topics: {', '.join(missing)}")
    return "\n".join(lines)
