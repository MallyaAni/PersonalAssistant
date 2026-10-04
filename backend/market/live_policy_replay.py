"""Private chronological replay through the actual nightly and intraday paths.

This runner makes no estimator, broker-fill or historical publication claim.
Supplied raw execution proxies are introduced only after each decision batch.
Every unavailable observation and durable original intent remains evidence.
"""

from __future__ import annotations

import contextlib
import io
import math
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import intraday_orders, paper
from backend.cli import market_daily
from backend.market import alpaca_trading, calendar, entry_timing
from backend.market.live_execution_inputs import RawExecutionInputs
from backend.market.replay_broker import ReplayBroker

POLICY = "actual-policy-timing/1-research"


# Preserve missing monetary values explicitly without serializing NaN as JSON evidence.
def plain(value):
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


# Express only the supplied raw prices, including explicit unavailable held marks.
def marks(names, prices):
    return {
        name: float(price) if np.isfinite(price) and price > 0 else None
        for name, price in zip(names, prices, strict=True)
    }


# Create the actual New York observation clock without inferring a provider receipt.
def instant(day, wall_time):
    return datetime.combine(day.astype(object), wall_time, calendar.NEW_YORK)


# Build a completed-bar snapshot that contains no next-open or later-session prices.
def snapshot(inputs, day, clock, now):
    started = instant(inputs.dates[day], calendar.REGULAR_OPEN) + timedelta(
        minutes=15 * clock
    )
    if now != started + timedelta(minutes=15):
        raise ValueError("Exact completed-bar observation clock required")
    quotes = {}
    for stock, symbol in enumerate(inputs.tickers):
        opened, close = (
            inputs.session_open[day, stock],
            inputs.observation_close[day, clock, stock],
        )
        if np.isfinite(opened) and opened > 0 and np.isfinite(close) and close > 0:
            quotes[symbol] = {
                "ticker": symbol,
                "open": float(opened),
                "last": float(close),
                "bar": started.isoformat(),
                "as_of": now.isoformat(),
                "source": "original_raw_SIP_completed_bar_proxy",
            }
    return {"as_of": now.isoformat(), "quotes": quotes}


# Retain each original durable intent once without replacing its desired quantity.
def remember_intents(root, intents):
    for row in paper.load_state(root).pending:
        identity = row["client_order_id"]
        if identity not in intents:
            intents[identity] = plain(row)


# Apply dated split entitlements and explicitly unspendable dividend receivables.
def corporate_actions(broker, inputs, day, opening):
    for symbol in inputs.tickers:
        for row in inputs.actions[symbol]:
            if row["date"] != str(inputs.dates[day]):
                continue
            if row["kind"] == "split":
                broker.apply_split(symbol, row["value"], opening)
            else:
                broker.accrue_dividend(symbol, row["value"], opening)


# Value actual raw holdings separately from unknown-payment dividend receivables.
def valuation(broker, inputs, day):
    ledger = broker.ledger()
    missing = [
        name
        for name, quantity in ledger["holdings"].items()
        if quantity
        and not np.isfinite(inputs.daily_close[day, inputs.tickers.index(name)])
    ]
    if missing:
        return {
            "nav": None,
            "price_nav": None,
            "status": "missing_held_close",
            "missing_symbols": missing,
            "cash": ledger["cash"],
            "holdings": ledger["holdings"],
        }
    price_nav = ledger["cash"] + sum(
        quantity * inputs.daily_close[day, inputs.tickers.index(name)]
        for name, quantity in ledger["holdings"].items()
    )
    receivable = sum(row["amount"] for row in ledger["dividends"] if not row["paid"])
    return plain(
        {
            "nav": price_nav + receivable,
            "price_nav": price_nav,
            "dividend_receivable": receivable,
            "cash": ledger["cash"],
            "holdings": ledger["holdings"],
            "status": "marked_raw_close",
        }
    )


# Obtain an explicit auction print without replacing it with an ordinary closing bar.
def auction_prices(cubes, names, day):
    result = {}
    for name in names:
        cube = cubes.get(name)
        value = None
        if cube is not None:
            selected = np.flatnonzero(cube.dates == day)
            if len(selected) == 1:
                price = cube.auction_open[selected[0]]
                if np.isfinite(price) and price > 0:
                    value = float(price)
        result[name] = value
    return result


# Refuse ambiguous calendars, reused state folders and forecast dependencies.
def validate(panel, inputs, root, first, last, reader_builder, provider):
    if not isinstance(inputs, RawExecutionInputs):
        raise ValueError("Reviewed raw execution input contract required")
    if (
        tuple(panel.tickers) != inputs.tickers
        or not np.array_equal(panel.dates, inputs.dates)
        or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (first, last)
        )
        or not 1 <= first <= last < len(inputs.dates)
    ):
        raise ValueError("Aligned original inputs and explicit account range required")
    years, sessions = calendar.reviewed_sessions()
    days = np.arange(
        inputs.dates[first - 1], inputs.dates[last] + np.timedelta64(1, "D")
    )
    expected = days[np.is_busday(days, busdaycal=sessions)]
    if (
        any(day.astype(object).year not in years for day in days)
        or not np.array_equal(inputs.dates[first - 1 : last + 1], expected)
        or root.exists()
    ):
        raise ValueError(
            "Complete reviewed sessions and new private account folder required"
        )
    if (reader_builder is None) != (provider is None) or (
        reader_builder is not None
        and (not callable(reader_builder) or not callable(provider))
    ):
        raise ValueError("Both explicit forecast provider and reader builder required")


# Execute real nightly planning and retain unavailable paths without invented plans.
def nightly(
    panel, inputs, root, broker, day, build_report, intents, logs, feature_reader=None
):
    now = instant(
        inputs.dates[day], calendar.session_close(inputs.dates[day].astype(object))
    )
    now += timedelta(minutes=1)
    broker.observe(now, marks(inputs.tickers, inputs.daily_close[day]), False)
    report = build_report(panel, inputs, inputs.grades, inputs.eligible, day)
    stream = io.StringIO()
    try:
        with contextlib.redirect_stdout(stream):
            result = market_daily.paper_trade(
                report,
                root,
                str(inputs.dates[day]),
                True,
                client_factory=lambda: broker,
                decision_at=now,
                feature_reader=feature_reader,
            )
        remember_intents(root, intents)
        status = {"status": "planned", "entry": plain(result)}
    except alpaca_trading.AlpacaTradingError as exc:
        # Broker incompleteness is missing evidence; programming failures still stop.
        status = {"status": "nightly_broker_unavailable", "reason": str(exc)}
    logs.append(
        {
            "session": str(inputs.dates[day]),
            "at": now.isoformat(),
            "text": stream.getvalue(),
            **status,
        }
    )
    return {"status": status["status"], "excluded": plain(report.excluded)}


# Carry one private account through real planning, timing, requests and settlement.
def run_account(
    panel,
    inputs,
    cubes,
    root,
    first,
    last,
    cost_bps,
    *,
    initial_cash=100000.0,
    reader_builder=None,
    provider=None,
    report_builder=None,
    feature_reader=None,
):
    root = Path(root)
    validate(panel, inputs, root, first, last, reader_builder, provider)
    if report_builder is None:
        from backend.market.live_policy_report import build as report_builder
    if not callable(report_builder):
        raise ValueError("Explicit nightly report builder required")
    if feature_reader is not None and not callable(feature_reader):
        raise ValueError("Explicit callable feature reader required")
    broker = ReplayBroker(initial_cash, cost_bps)
    root.mkdir(parents=True, exist_ok=False)
    intents, observations, sessions, logs, forecasts = {}, [], [], [], []
    base = nightly(
        panel,
        inputs,
        root,
        broker,
        first - 1,
        report_builder,
        intents,
        logs,
        feature_reader,
    )
    sessions.append(
        {
            "session": str(inputs.dates[first - 1]),
            "initial": True,
            **valuation(broker, inputs, first - 1),
            "nightly": base,
        }
    )
    for day in range(first, last + 1):
        date = inputs.dates[day].astype(object)
        opening = instant(inputs.dates[day], calendar.REGULAR_OPEN)
        closing = instant(inputs.dates[day], calendar.session_close(date))
        broker.observe(opening, marks(inputs.tickers, inputs.session_open[day]), True)
        corporate_actions(broker, inputs, day, opening)
        broker.flush(
            opening, marks(inputs.tickers, inputs.session_open[day]), phase="open"
        )
        count = int((closing - opening).total_seconds() // 900) - 1
        for clock in range(count):
            now = opening + timedelta(minutes=15 * (clock + 1))
            live = snapshot(inputs, day, clock, now)
            broker.observe(
                now, marks(inputs.tickers, inputs.observation_close[day, clock]), True
            )
            # Match the live balancer's first-crossing latch before deciding requests.
            entry_timing.update(root, live, now)
            before = paper.load_state(root)
            due = intraday_orders.due(before, date)
            reader = None
            if (
                reader_builder is not None
                and now < entry_timing.session_clock(date)["final"]
            ):
                reader = reader_builder(
                    provider,
                    inputs.tickers,
                    day,
                    clock,
                    date,
                    now,
                    live,
                    due,
                    broker,
                    cost_bps,
                    forecasts,
                )
            lines = intraday_orders.send_due(
                root, live, now, lambda: broker, timing_reader=reader
            )
            after = paper.load_state(root)
            current = {row["client_order_id"]: row for row in after.pending}
            for row in due:
                symbol = row["symbol"]
                observations.append(
                    plain(
                        {
                            "intent_id": row["client_order_id"],
                            "session": str(inputs.dates[day]),
                            "day": day,
                            "clock": clock,
                            "at": now.isoformat(),
                            "symbol": symbol,
                            "side": row["side"],
                            "planned_qty": row["qty"],
                            "quote": live["quotes"].get(symbol),
                            "supported_full_session": bool(inputs.full_session[day]),
                            "before": row,
                            "after": current.get(row["client_order_id"]),
                            "sender_logs": lines,
                        }
                    )
                )
            # Outcome prices have not entered any observation, model or request yet.
            broker.flush(now, marks(inputs.tickers, inputs.next_open[day, clock]))
        broker.flush(
            closing,
            auction_prices(cubes, inputs.tickers, inputs.dates[day]),
            phase="close",
        )
        result = nightly(
            panel,
            inputs,
            root,
            broker,
            day,
            report_builder,
            intents,
            logs,
            feature_reader,
        )
        sessions.append(
            {
                "session": str(inputs.dates[day]),
                "initial": False,
                **valuation(broker, inputs, day),
                "nightly": result,
            }
        )
    return plain(
        {
            "policy": POLICY,
            "first": str(inputs.dates[first]),
            "last": str(inputs.dates[last]),
            "initial_cash": initial_cash,
            "cost_bps": cost_bps,
            "sessions": sessions,
            "intents": list(intents.values()),
            "observations": observations,
            "forecast_decisions": forecasts,
            "attempts": broker.attempt_history,
            "fills": broker.fill_history,
            "broker": broker.ledger(),
            "paper_state": asdict(paper.load_state(root)),
            "nightlies": logs,
            "economic_status": "conditional_current_vintage_private_proxy",
            "adoption_eligible": False,
        }
    )
