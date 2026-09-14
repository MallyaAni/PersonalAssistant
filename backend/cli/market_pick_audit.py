"""Audit saved A+ picks against publication time, prices and paper executions.

Read-only: never recomputes grades, publishes decisions or submits orders.
The first observable opening price after publication is the entry reference.
Historical intraday prices use consolidated SIP bars by default. Neither a
bar nor a paper fill proves the price a real account could have executed.
"""

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.agents.trading.desk import timing_research
from backend.market import alpaca, alpaca_trading
from backend.market.store import MarketStore

NY = ZoneInfo("America/New_York")


# Retain only observations published before a regular-session bar could be entered.
def after_publication(bars, published):
    return [
        b
        for b in bars
        if b.start >= published
        and time(9, 30) <= b.start.astimezone(NY).time() < time(16)
        and b.start.astimezone(NY).weekday() < 5
    ]


# Compare predeclared timing rules, without choosing parameters from the observed highs.
def timing_cases(bars):
    if not bars:
        return {}
    reference = bars[0].open
    close = bars[-1].close
    first_day = bars[0].start.astimezone(NY).date()
    later = next(
        (
            b
            for b in bars
            if b.start.astimezone(NY).date() == first_day
            and b.start.astimezone(NY).time() >= time(10, 30)
        ),
        None,
    )
    limit = reference * 0.98
    dip = next((b for b in bars if b.low <= limit), None)
    entries = {"first_open": (bars[0], reference)}
    if later:
        entries["delay_until_1030"] = (later, later.open)
    if dip:
        entries["two_percent_limit_until_sample_end"] = (dip, min(dip.open, limit))
    out = {}
    for name, (entry, price) in entries.items():
        # Exclude the entry bar's high/low: its within-bar ordering is unknown.
        future = [b for b in bars if b.start > entry.start]
        exit_bar = next((b for b in future if b.high >= price * 1.05), None)
        out[name] = {
            "entry_at": entry.start.isoformat(),
            "entry_price": price,
            "hold_to_sample_end": close / price - 1,
            "hold_net_20bp": close / price - 1 - 0.002,
            "five_percent_take_profit_at": exit_bar.start.isoformat()
            if exit_bar
            else None,
            "five_percent_take_profit_net_20bp": (
                max(exit_bar.open, price * 1.05) / price - 1 - 0.002
                if exit_bar
                else close / price - 1 - 0.002
            ),
            "future_high_hindsight_only": max((b.high for b in future), default=None),
        }
    return out


# Price one stored pick from the first daily open that actually followed publication.
def daily_result(history, published, until):
    if history is None:
        return {"status": "daily prices unavailable"}
    bars = [
        b
        for b in history.bars
        if b.session_date <= until
        and datetime.combine(b.session_date, time(9, 30), NY) >= published
    ]
    if not bars:
        return {"status": "no post-publication session in sample"}
    first, last = bars[0], bars[-1]
    if (
        not first.open
        or not first.close
        or not first.adjusted_close
        or not last.adjusted_close
    ):
        return {"status": "incomplete price fields"}
    entry = first.open * first.adjusted_close / first.close
    highs = [
        (b.high * b.adjusted_close / b.close, b.session_date)
        for b in bars
        if b.high and b.adjusted_close and b.close
    ]
    peak, peak_date = max(highs) if highs else (entry, first.session_date)
    return {
        "status": "observed",
        "entry_session": str(first.session_date),
        "entry_at": datetime.combine(first.session_date, time(9, 30), NY).isoformat(),
        "entry_open_raw": first.open,
        "last_session": str(last.session_date),
        "last_close_raw": last.close,
        "adjusted_return": last.adjusted_close / entry - 1,
        "peak_return_hindsight_only": peak / entry - 1,
        "peak_session": str(peak_date),
        "sessions_observed": len(bars),
        "price_source": history.source,
        "price_fetched_at": history.source_time.isoformat(),
    }


# Select the requested historical feed without changing the live quote provider.
def _historical_transport(feed, url, headers):
    return alpaca.alpaca_transport(url.replace("feed=iex", f"feed={feed}"), headers)


# Fetch dated candles while reporting every unavailable symbol explicitly.
def _intraday(symbols, since, until, feed):
    candles, errors = {}, {}
    for ticker in symbols:
        try:
            candles[ticker] = alpaca.fetch_bars(
                ticker, since, until, transport=partial(_historical_transport, feed)
            )
        except alpaca.AlpacaUnavailableError as exc:
            errors[ticker] = str(exc)
    return candles, errors


# Read saved grades and match publication times to prices and broker receipts.
def audit(root, since, until, intraday=False, broker=False, feed="sip"):
    store = MarketStore(root)
    records = []
    for path in sorted((root / "desk").glob("asof=*/desk.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if str(since) <= record["session"] <= str(until):
            records.append((record, hashlib.sha256(path.read_bytes()).hexdigest()))
    symbols = sorted(
        {
            t
            for r, _ in records
            for t, g in r.get("grades", {}).items()
            if g.get("grade") == "A+"
        }
    )
    histories = {t: store.read(t, until) for t in symbols}
    benchmarks = {ticker: store.read(ticker, until) for ticker in ("SPY", "QQQ")}
    candles, errors = (
        _intraday(symbols, since - timedelta(days=45), until, feed)
        if intraday
        else ({}, {})
    )
    fills = []
    if broker:
        orders = alpaca_trading.client_from_env().orders_since(f"{since}T00:00:00Z")
        if len(orders) >= 500:
            raise ValueError(
                "Broker response reached its limit; cannot claim full coverage"
            )
        fields = (
            "client_order_id",
            "symbol",
            "side",
            "qty",
            "filled_qty",
            "filled_avg_price",
            "status",
            "submitted_at",
            "filled_at",
            "canceled_at",
            "expired_at",
            "time_in_force",
        )
        fills = [
            {k: o.get(k) for k in fields}
            for o in orders
            if str(o.get("client_order_id", "")).startswith("anios-")
        ]
    picks = []
    seen = set()
    for record, digest in records:
        published = datetime.fromisoformat(record["written"])
        if published.tzinfo is None:
            raise ValueError(
                "A publication time without a timezone cannot establish tradability"
            )
        for ticker, grade in record.get("grades", {}).items():
            if grade.get("grade") != "A+":
                continue
            level = (record.get("levels") or {}).get(ticker) or {}
            book = next(
                (row for row in record.get("book", []) if row["ticker"] == ticker), {}
            )
            picks.append(
                {
                    "ticker": ticker,
                    "session": record["session"],
                    "published_at": published.isoformat(),
                    "published_et": published.astimezone(NY).isoformat(),
                    "record_sha256": digest,
                    "source_revision": (record.get("provenance") or {}).get(
                        "code_revision"
                    ),
                    "first_observed_in_sample": ticker not in seen,
                    "target_weight": book.get("weight", 0),
                    "entry_blocked": level.get("rejecting_band"),
                    "paper_plan": (record.get("paper") or {}).get("plan"),
                    "until_rebalance": (record.get("paper") or {}).get(
                        "until_rebalance"
                    ),
                    "daily": daily_result(histories[ticker], published, until),
                    "benchmarks": {
                        ticker: daily_result(history, published, until)
                        for ticker, history in benchmarks.items()
                    },
                    "timing_cases": timing_cases(
                        after_publication(candles.get(ticker, []), published)
                    ),
                    "technical_timing": timing_research.compare(
                        candles.get(ticker, []), histories[ticker], published
                    ),
                }
            )
            seen.add(ticker)
    return {
        "since": str(since),
        "until": str(until),
        "generated_at": datetime.now(UTC).isoformat(),
        "audit_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "timing_source_sha256": hashlib.sha256(
            Path(timing_research.__file__).read_bytes()
        ).hexdigest(),
        "records": len(records),
        "unique_symbols": symbols,
        "picks": picks,
        "broker_orders": fills,
        "intraday_errors": errors,
        "intraday_feed": feed,
        "intraday_bars": {t: [asdict(b) for b in bars] for t, bars in candles.items()},
        "limitations": [
            "Stored write time bounds availability; first publication is unproven.",
            "Missing revisions leave some records' source implementation unverified.",
            "Repeated grades are dependent; first observed is not a new upgrade.",
            "SIP consolidates venues; IEX is partial. Neither guarantees a fill.",
            "Exploratory timing tests exclude entry-bar exits and charge 20 bp.",
            "Unfilled limits stay in cash and must stay in portfolio comparisons.",
            "Limit simulations assume liquidity and ignore allocation constraints.",
        ],
    }


# Emit the audit as an artifact; all account and market access is read-only.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--since", type=date.fromisoformat, required=True)
    parser.add_argument("--until", type=date.fromisoformat, required=True)
    parser.add_argument("--intraday", action="store_true")
    parser.add_argument("--broker", action="store_true")
    parser.add_argument("--feed", choices=("sip", "iex"), default="sip")
    args = parser.parse_args()
    print(
        json.dumps(
            audit(
                args.root, args.since, args.until, args.intraday, args.broker, args.feed
            ),
            default=str,
        )
    )


if __name__ == "__main__":
    main()
