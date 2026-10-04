"""Private chronological replay through the actual nightly and intraday paths.

This runner makes no estimator, broker-fill or historical publication claim.
Supplied raw execution proxies are introduced only after each decision batch.
Every unavailable observation and durable original intent remains evidence.
"""

from __future__ import annotations

import contextlib
import io
import math
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from itertools import chain
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import intraday_orders, paper
from backend.cli import market_daily
from backend.market import alpaca_trading, calendar, entry_timing
from backend.market.live_execution_inputs import (
    RawExecutionInputs,
    validate_inherited,
    validate_passive,
)
from backend.market.replay_broker import ReplayBroker

POLICY = "actual-policy-timing/1-research"


# Copy immutable metadata and preserve missing money without serializing NaN.
def plain(value):
    if isinstance(value, Mapping):
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


# Expose inherited assets only at their current session's actual observation clock.
def passive_marks(inputs, day, now):
    passive = inputs.passive
    if passive is None:
        return {}
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Aware passive observation clock required")
    local = now.astimezone(calendar.NEW_YORK)
    date = inputs.dates[day].astype(object)
    if local.date() != date:
        raise ValueError("Passive marks require the same observed session")
    opening = instant(inputs.dates[day], calendar.REGULAR_OPEN)
    closing = instant(inputs.dates[day], calendar.session_close(date))
    prices = np.full(len(passive.tickers), np.nan)
    if now == opening:
        prices = passive.session_open[day]
    elif now > closing:
        prices = passive.daily_close[day]
    elif opening < now <= closing:
        seconds = (now - opening).total_seconds()
        if seconds % 900 == 0:
            prices = passive.observation_close[day, int(seconds // 900) - 1]
    return marks(passive.tickers, prices)


# Merge valuation-only marks without adding inherited symbols to any execution input.
def account_marks(inputs, day, now, prices):
    return {**marks(inputs.tickers, prices), **passive_marks(inputs, day, now)}


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


# Select actions already effective at this observation, separately from archive dates.
def due_actions(inputs, day, now):
    date = inputs.dates[day].astype(object)
    if now.utcoffset() is None or now.astimezone(calendar.NEW_YORK).date() != date:
        raise ValueError("Aware same-session corporate-action observation required")
    due = []
    for symbol, rows in chain(
        inputs.actions.items(), (inputs.inherited_actions or {}).items()
    ):
        for row in rows:
            clock = row.get("effective_at", row.get("completed_before"))
            if clock is None and row["date"] != str(inputs.dates[day]):
                continue
            effective = (
                datetime.fromisoformat(clock)
                if clock is not None
                else instant(inputs.dates[day], calendar.REGULAR_OPEN)
            )
            if effective.utcoffset() is None:
                raise ValueError("Aware corporate-action effective clock required")
            if effective <= now and (
                row["date"] == str(inputs.dates[day])
                or effective.astimezone(calendar.NEW_YORK).date() == date
            ):
                due.append((symbol, row, effective))
    order = (
        "split",
        "share_split",
        "security_exchange",
        "share_consolidation",
        "cash_merger",
        "stock_distribution",
        "dividend",
        "archive_adjustment",
    )
    if any(row["kind"] not in order for _, row, _ in due):
        raise ValueError("Unsupported economic corporate action")
    return sorted(due, key=lambda item: (item[2], order.index(item[1]["kind"])))


# Apply each observed entitlement once with chronological and same-clock share ordering.
def corporate_actions(broker, inputs, day, now):
    if broker.clock()["timestamp"] != now.astimezone(UTC).isoformat():
        raise ValueError("Corporate action requires the actual observed broker clock")
    for symbol, row, effective in due_actions(inputs, day, now):
        if row["kind"] in ("split", "share_split"):
            broker.apply_split(symbol, row["value"], effective)
        elif row["kind"] == "dividend":
            broker.accrue_dividend(symbol, row["value"], effective)
        elif row["kind"] == "share_consolidation":
            broker.apply_share_consolidation(
                symbol,
                row["numerator"],
                row["denominator"],
                effective,
                fractional_policy=row["fractional_policy"],
            )
        elif row["kind"] == "security_exchange":
            broker.apply_security_exchange(
                symbol,
                row["numerator"],
                row["denominator"],
                effective,
                old_security_id=row["old_security_id"],
                new_security_id=row["new_security_id"],
                fractional_policy=row["fractional_policy"],
                election_policy=row.get("election_policy"),
            )
        elif row["kind"] == "cash_merger":
            broker.apply_cash_merger(
                symbol,
                row["value"],
                row["completed_before"],
                old_security_id=row["old_security_id"],
                election_policy=row["election_policy"],
            )
        elif row["kind"] == "stock_distribution":
            broker.apply_stock_distribution(
                symbol,
                row["child"],
                row["numerator"],
                row["denominator"],
                effective,
                parent_basis_fraction=row["parent_basis_fraction"],
                basis_policy=row.get("basis_policy"),
            )


# Value priced holdings and retain uncovered securities or unknown cash as missing NAV.
def valuation(broker, inputs, day):
    ledger = broker.ledger()
    unknown = [
        row
        for row in ledger.get("security_distributions", ())
        if row["fractional_qty"] > 0 and row["cash_in_lieu"] is None
    ]
    unknown_consolidations = [
        row
        for row in ledger.get("share_consolidations", ())
        if row["fractional_qty"] > 0 and row["cash_in_lieu"] is None
    ]
    unknown.extend(unknown_consolidations)
    unknown_exchanges = [
        row
        for row in ledger.get("security_exchanges", ())
        if row.get("fractional_qty", 0) > 0 and row["cash_in_lieu"] is None
    ]
    unknown.extend(unknown_exchanges)
    if unknown:
        return plain(
            {
                "nav": None,
                "price_nav": None,
                "status": "unknown_exchange_cash_in_lieu"
                if unknown_exchanges
                else "unknown_consolidation_cash_in_lieu"
                if unknown_consolidations
                else "unknown_distribution_cash_in_lieu",
                "unpriced_entitlements": unknown,
                "cash": ledger["cash"],
                "holdings": ledger["holdings"],
            }
        )
    closing_marks = marks(inputs.tickers, inputs.daily_close[day])
    observed_at = ledger["observed_at"]
    if observed_at is not None:
        now = datetime.fromisoformat(observed_at)
        closing = instant(
            inputs.dates[day], calendar.session_close(inputs.dates[day].astype(object))
        )
        closing_marks.update(
            passive_marks(inputs, day, now)
            if now > closing
            else dict.fromkeys(inputs.passive.tickers if inputs.passive else ())
        )
    missing = [
        name
        for name, quantity in ledger["holdings"].items()
        if quantity and closing_marks.get(name) is None
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
        quantity * closing_marks[name] for name, quantity in ledger["holdings"].items()
    )
    receivable = sum(row["amount"] for row in ledger["dividends"] if not row["paid"])
    merger_receivable = sum(
        row["amount"] for row in ledger.get("cash_mergers", ()) if not row["paid"]
    )
    return plain(
        {
            "nav": price_nav + receivable + merger_receivable,
            "price_nav": price_nav,
            "dividend_receivable": receivable,
            **(
                {"merger_receivable": merger_receivable}
                if "cash_mergers" in ledger
                else {}
            ),
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
    validate_passive(inputs.passive, inputs.dates, inputs.tickers)
    validate_inherited(inputs)
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


# Identify atomic state replacements in the exclusively owned private account folder.
def state_revision(root):
    path = paper.state_path(root)
    if not path.exists():
        return None
    value = path.stat()
    return value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


# Reuse only unchanged private state and reject a concurrent replacement during reading.
def read_private_state(root, cached, revision, *, reuse=True):
    current = state_revision(root)
    if reuse and cached is not None and current == revision:
        return cached, current
    value = paper.load_state(root)
    if state_revision(root) != current:
        raise ValueError("Private paper state changed during reading")
    return value, current


# Send detached completed-session evidence to an optional private progress writer.
def publish_progress(callback, row):
    if callback is not None:
        callback(plain(row))


# Execute real nightly planning and retain unavailable paths without invented plans.
def nightly(
    panel,
    inputs,
    root,
    broker,
    day,
    build_report,
    intents,
    logs,
    feature_reader=None,
    holding_policy=None,
):
    now = instant(
        inputs.dates[day], calendar.session_close(inputs.dates[day].astype(object))
    )
    now += timedelta(minutes=1)
    broker.observe(now, account_marks(inputs, day, now, inputs.daily_close[day]), False)
    corporate_actions(broker, inputs, day, now)
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
                holding_policy=holding_policy,
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


# Admit optional risk planning only when physical-account costs match its contract.
def _holding_option(policy, cost_bps):
    if policy is None:
        return
    from backend.market.joint_funded_policy import JointFundedPolicy

    if not isinstance(policy, JointFundedPolicy) or policy.cost_bps != cost_bps:
        raise ValueError(
            "Authenticated joint policy and identical account fees required"
        )


# Carry a private account through real execution with optional named risk planning.
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
    holding_policy=None,
    reuse_unchanged_state=True,
    on_session=None,
):
    root = Path(root)
    validate(panel, inputs, root, first, last, reader_builder, provider)
    _holding_option(holding_policy, cost_bps)
    if report_builder is None:
        from backend.market.live_policy_report import build as report_builder
    if not callable(report_builder):
        raise ValueError("Explicit nightly report builder required")
    if feature_reader is not None and not callable(feature_reader):
        raise ValueError("Explicit callable feature reader required")
    if not isinstance(reuse_unchanged_state, bool) or (
        on_session is not None and not callable(on_session)
    ):
        raise ValueError("Explicit state-reuse boolean and callable progress required")
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
        holding_policy,
    )
    sessions.append(
        {
            "session": str(inputs.dates[first - 1]),
            "initial": True,
            **valuation(broker, inputs, first - 1),
            "nightly": base,
        }
    )
    publish_progress(on_session, sessions[-1])
    cached_state, revision = None, None
    for day in range(first, last + 1):
        date = inputs.dates[day].astype(object)
        opening = instant(inputs.dates[day], calendar.REGULAR_OPEN)
        closing = instant(inputs.dates[day], calendar.session_close(date))
        broker.observe(
            opening, account_marks(inputs, day, opening, inputs.session_open[day]), True
        )
        corporate_actions(broker, inputs, day, opening)
        broker.flush(
            opening, marks(inputs.tickers, inputs.session_open[day]), phase="open"
        )
        count = int((closing - opening).total_seconds() // 900) - 1
        for clock in range(count):
            now = opening + timedelta(minutes=15 * (clock + 1))
            live = snapshot(inputs, day, clock, now)
            broker.observe(
                now,
                account_marks(inputs, day, now, inputs.observation_close[day, clock]),
                True,
            )
            # Match the live balancer's first-crossing latch before deciding requests.
            entry_timing.update(root, live, now)
            before, revision = read_private_state(
                root, cached_state, revision, reuse=reuse_unchanged_state
            )
            cached_state = before
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
                    plain(due),
                    broker,
                    cost_bps,
                    forecasts,
                )
            lines = (
                intraday_orders.send_due(
                    root, live, now, lambda: broker, timing_reader=reader
                )
                if due or not reuse_unchanged_state
                else []
            )
            after, revision = read_private_state(
                root, cached_state, revision, reuse=reuse_unchanged_state
            )
            cached_state = after
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
            holding_policy,
        )
        sessions.append(
            {
                "session": str(inputs.dates[day]),
                "initial": False,
                **valuation(broker, inputs, day),
                "nightly": result,
            }
        )
        publish_progress(on_session, sessions[-1])
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
            **(
                {"passive_valuation_source": inputs.passive.provenance}
                if inputs.passive is not None
                else {}
            ),
        }
    )


# Carry a matched whole-share ETF control without reinvesting unspendable dividends.
def run_benchmark(
    panel, inputs, root, first, last, cost_bps, symbol, *, initial_cash=100000.0
):
    root = Path(root)
    validate(panel, inputs, root, first, last, None, None)
    if symbol not in ("SPY", "QQQ") or symbol not in inputs.tickers:
        raise ValueError("Declared SPY or QQQ control required")
    broker = ReplayBroker(initial_cash, cost_bps)
    root.mkdir(parents=True, exist_ok=False)
    sessions = [
        {
            "session": str(inputs.dates[first - 1]),
            "initial": True,
            **valuation(broker, inputs, first - 1),
        }
    ]
    column = inputs.tickers.index(symbol)
    entry = {
        "status": "opening_price_unavailable",
        "symbol": symbol,
        "session": str(inputs.dates[first]),
        "qty": None,
    }
    for day in range(first, last + 1):
        opening = instant(inputs.dates[day], calendar.REGULAR_OPEN)
        broker.observe(
            opening, account_marks(inputs, day, opening, inputs.session_open[day]), True
        )
        corporate_actions(broker, inputs, day, opening)
        if day == first:
            price = inputs.session_open[day, column]
            if np.isfinite(price) and price > 0:
                quantity = math.floor(initial_cash / (price * (1 + cost_bps / 1e4)))
                entry.update(qty=quantity, price=float(price))
                if quantity:
                    broker.submit_market_on_open(
                        symbol,
                        quantity,
                        "buy",
                        f"benchmark-{symbol}-{inputs.dates[day]}",
                    )
                    broker.flush(opening, {symbol: float(price)})
                    entry["status"] = "filled_opening_proxy"
                else:
                    entry["status"] = "insufficient_cash_for_one_share"
        closing = instant(
            inputs.dates[day], calendar.session_close(inputs.dates[day].astype(object))
        )
        broker.observe(
            closing, account_marks(inputs, day, closing, inputs.daily_close[day]), False
        )
        sessions.append(
            {
                "session": str(inputs.dates[day]),
                "initial": False,
                **valuation(broker, inputs, day),
            }
        )
    return plain(
        {
            "policy": "whole-share-buy-and-hold/1-research",
            "symbol": symbol,
            "first": str(inputs.dates[first]),
            "last": str(inputs.dates[last]),
            "cost_bps": cost_bps,
            "initial_cash": initial_cash,
            "entry": entry,
            "sessions": sessions,
            "fills": broker.fill_history,
            "attempts": broker.attempt_history,
            "broker": broker.ledger(),
            "economic_status": "conditional_current_vintage_private_proxy",
            "adoption_eligible": False,
            **(
                {"passive_valuation_source": inputs.passive.provenance}
                if inputs.passive is not None
                else {}
            ),
        }
    )
