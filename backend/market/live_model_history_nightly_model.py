"""Recompute saved nightly decisions without executing or replaying their orders."""

import json
import math
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import timedelta

import numpy as np

from backend.agents.trading.desk import (
    actions,
    event_risk,
    intraday_orders,
    live_policy,
    nightly_plan,
    paper,
)
from backend.cli import market_daily
from backend.cli.verify_actual_policy_timing import same
from backend.market import (
    calendar,
    direct_daily_arithmetic,
    learned_retention_models,
    live_policy_replay,
)
from backend.market import live_model_history_nightly_audit as controls
from backend.market.daily_arithmetic_bridge import _hash
from backend.market.live_model_history import FrozenCurrentGradePolicy
from backend.market.live_model_history_receipts import instant, require


# Recompute each complete causal prefix and score its final row with the frozen head.
def prefix_model(panel, raw, reader, day):
    require(
        type(day) is int and 0 <= day < len(panel.dates), "Exact model row required"
    )
    prefix = replace(
        panel,
        **{
            name: getattr(panel, name)[: day + 1]
            for name in ("dates", "open", "high", "low", "close", "adj_close", "volume")
        },
    )
    prepared = learned_retention_models.completed_features(
        prefix,
        raw.grades[: day + 1],
        raw.eligible[: day + 1],
        prefix.dates,
        {"basis": "independent_causal_prefix_audit"},
    )
    reader.select(day)
    current = reader.current
    for name, expected in (
        ("features", prepared["X"][-1]),
        ("support", prepared["risk_valid"][-1]),
        ("prices", prepared["prices"][-1]),
    ):
        require(
            np.array_equal(getattr(current, name), expected, equal_nan=True),
            "Independent complete-prefix model " + name + " differs",
        )
    scored, _ = direct_daily_arithmetic.predict(
        reader._parent._head, prepared["X"][-1:], prepared["risk_valid"][-1:]
    )
    require(
        np.array_equal(current.forecasts, scored[-1], equal_nan=True),
        "Independent frozen-head prediction differs",
    )
    return {
        "session": str(prefix.dates[-1]),
        "features_sha256": _hash(prepared["X"][-1]),
        "support_sha256": _hash(prepared["risk_valid"][-1]),
        "forecasts_sha256": _hash(scored[-1]),
    }


# Derive the planner account from independently conserved money, shares and raw marks.
def account(cash, held, basis, dividends, records, marks):
    require(
        type(cash) in (int, float) and math.isfinite(cash) and cash >= 0,
        "Independent finite nonnegative account cash required",
    )
    cash = float(cash)
    require(
        type(records) is dict
        and set(records)
        == {
            "security_distributions",
            "share_consolidations",
            "security_exchanges",
            "cash_mergers",
        }
        and all(type(rows) is list for rows in records.values()),
        "Complete independent economic record collections required",
    )
    require(
        type(held) is dict
        and all(
            type(qty) in (int, float) and math.isfinite(qty) and qty > 0
            for qty in held.values()
        ),
        "Independent finite positive held quantities required",
    )
    held = deepcopy(held)
    require(
        type(basis) is dict
        and set(basis) == set(held)
        and all(
            value is None
            or (type(value) in (int, float) and math.isfinite(value) and value >= 0)
            for value in basis.values()
        ),
        "Exact independent held basis including explicit unknowns required",
    )
    for kind, problem in (
        ("security_distributions", "unknown_distribution_cash_in_lieu"),
        ("share_consolidations", "unknown_consolidation_cash_in_lieu"),
        ("security_exchanges", "unknown_exchange_cash_in_lieu"),
    ):
        if any(
            row.get("fractional_qty", 0) > 0 and row["cash_in_lieu"] is None
            for row in records[kind]
        ):
            return {"problem": problem}
    missing = [
        name
        for name in held
        if not isinstance(marks.get(name), (int, float))
        or isinstance(marks[name], bool)
        or not math.isfinite(marks[name])
        or marks[name] <= 0
    ]
    if missing:
        return {"problem": "missing_held_close", "missing_symbols": sorted(missing)}
    positions = [
        {
            "symbol": name,
            "qty": qty,
            "market_value": qty * marks[name],
            "avg_entry_price": basis[name],
            "current_price": marks[name],
            "unrealized_pl": qty * (marks[name] - basis[name])
            if basis[name] is not None
            else None,
        }
        for name, qty in sorted(held.items())
    ]
    equity = cash + sum(row["market_value"] for row in positions)
    equity += sum(row["amount"] for row in dividends if not row["paid"])
    equity += sum(row["amount"] for row in records["cash_mergers"] if not row["paid"])
    require(math.isfinite(equity), "Independent finite equity required")
    return {
        "problem": None,
        "cash": cash,
        "equity": equity,
        "held": held,
        "positions": positions,
        "marks": deepcopy(marks),
    }


# Filter conserved cumulative receipts to this close before binding planned intents.
def planned_intents(
    orders, session, at, prices, policy, event_plan, accepted, attempts
):
    closing = instant(at)
    attempts = [deepcopy(row) for row in attempts if instant(row["at"]) == closing]
    accepted = {
        cid: deepcopy(row)
        for cid, row in accepted.items()
        if instant(row["at"]) == closing
    }
    require(
        all(
            row["client_order_id"] == cid and row["accepted"] is True
            for cid, row in accepted.items()
        ),
        "Exact original same-close acknowledgment identities required",
    )
    timing_policy = None if event_plan else policy.timing_policy
    pending = market_daily._pending_orders(
        orders,
        session,
        prices,
        session,
        decision_at=instant(at),
        timing_policy=timing_policy,
    )
    submitted, refused = [], []
    for order, row in zip(orders, pending, strict=True):
        cid = row["client_order_id"]
        rows = [r for r in attempts if r["client_order_id"] == cid]
        if order.execution_timing == intraday_orders.INTRADAY_TIMING:
            require(
                not rows and cid not in accepted, "Nightly timed intent was submitted"
            )
            continue
        require(
            len(rows) == 1
            and type(rows[0]["qty"]) is int
            and rows[0]["qty"] == order.qty
            and rows[0]["symbol"] == order.symbol
            and rows[0]["side"] == order.side
            and type(rows[0]["accepted"]) is bool
            and instant(rows[0]["at"]) == instant(at),
            "Original immediate nightly attempt required",
        )
        attempt = rows[0]
        if attempt["accepted"]:
            require(
                cid in accepted and accepted[cid] == attempt,
                "Nightly acknowledgment differs",
            )
            broker = controls.broker_receipt(row, attempt, None, instant(at))
            evidence = {
                key: broker[key]
                for key in ("created_at", "submitted_at", "time_in_force")
            }
            row["execution"].update(evidence)
            submitted.append(
                {
                    "symbol": order.symbol,
                    "side": order.side,
                    "qty": order.qty,
                    "reason": order.reason,
                    "kind": order.kind,
                    "client_order_id": cid,
                    "execution": evidence,
                }
            )
        else:
            require(
                cid not in accepted
                and attempt["reason"]
                in (
                    "insufficient_reserved_cash",
                    "uncovered_sell",
                    "terminated_security",
                ),
                "Original explicit nightly refusal required",
            )
            refused.append(f"{order.side} {order.symbol}: {attempt['reason']}")
    require(
        {r["client_order_id"] for r in attempts}
        <= {row["client_order_id"] for row in pending},
        "Unplanned same-close attempted identity",
    )
    require(
        set(accepted) <= {r["client_order_id"] for r in attempts},
        "Same-close acknowledgment lacks original attempted identity",
    )
    return pending, submitted, refused


# Run the exact pure dispatcher and action builder with independently supplied inputs.
def pure_plan(report, policy, previous, observed, session, at, attempts, accepted):
    require(
        type(policy) is FrozenCurrentGradePolicy,
        "Explicit private frozen policy required",
    )
    require(observed["problem"] is None, "Account evidence unavailable before planning")
    require(
        str(report.panel.dates[-1]) == session,
        "Exact independent nightly report required",
    )
    held, positions = observed["held"], observed["positions"]
    equity, cash = observed["equity"], observed["cash"]
    prices = {
        name: float(report.panel.close[-1, index])
        for index, name in enumerate(report.panel.tickers)
        if np.isfinite(report.panel.close[-1, index])
    }
    prices = {**{row["symbol"]: row["current_price"] for row in positions}, **prices}
    event = event_risk.decision(report.panel)
    mode = controls.branch(previous, event, session)
    event_plan = mode["path"] == "event_priority"
    blocked, flags = market_daily._band_blocked(report)
    grades = {
        name: report.graded.letter(len(report.panel.dates) - 1, column)
        for column, name in enumerate(report.panel.tickers)
        if name != report.panel.benchmark
    }
    targets = live_policy.targets(report)
    orders, state, what = nightly_plan.plan(
        session,
        previous,
        equity,
        held,
        prices,
        targets,
        grades,
        event,
        finished={} if event_plan else market_daily._downgraded(report, held),
        entry_blocked=blocked,
        entries={} if event_plan else market_daily._price_entries(report),
        cash=cash,
        holding_policy=policy,
        report=report,
    )
    targets, _, metadata = market_daily._holding_plan_metadata(
        policy, event_plan, state, targets, grades, prices, held, equity, orders
    )
    pending, submitted, refused = planned_intents(
        orders, session, at, prices, policy, event_plan, accepted, attempts
    )
    if orders:
        state.pending = pending
    holdings = {
        row["symbol"]: actions.Holding(
            row["market_value"] / equity if equity else 0.0,
            row["avg_entry_price"] if row["avg_entry_price"] else None,
        )
        for row in positions
    }
    built = actions.build(
        report,
        targets,
        holdings,
        state.sessions_since_rebalance,
        {order.symbol: order.reason for order in orders},
    )
    built = market_daily._holding_actions(
        policy,
        built,
        orders,
        holdings,
        held,
        prices,
        equity,
        event_plan,
        (state.allocation_state or {}).get("receipt"),
    )
    for row in built:
        row["rejecting_band"] = flags.get(row["ticker"], False)
    redeploy = [order for order in orders if order.kind == paper.REDEPLOY_KIND]
    entry = {
        "session": session,
        "equity": equity,
        "cash": cash,
        "positions": positions,
        "orders": submitted,
        "planned": [
            {
                key: row.get(key)
                for key in ("symbol", "side", "qty", "reason", "kind", "execute_on")
            }
            for row in state.pending
            if row.get("execution_timing") == intraday_orders.INTRADAY_TIMING
        ],
        "execution_rule": intraday_orders.INTRADAY_TIMING
        if intraday_orders.INTRADAY_EXECUTION
        else "next_open",
        "refused": refused,
        "plan": what,
        "event_risk": {
            **event,
            "plan": what,
            "cycle": state.event_cycle,
            "outcome": state.event_outcomes[-1] if state.event_outcomes else None,
        },
        "until_rebalance": None,
        "idle_cash_share": market_daily._idle_cash_share(orders, prices, cash, equity),
        "redeploy": {
            "enabled": bool(paper.REDEPLOY_IDLE_CASH),
            "buffer": float(paper.REDEPLOY_BUFFER),
            "orders": len(redeploy),
            "notional": float(
                sum(order.qty * prices[order.symbol] for order in redeploy)
            ),
        },
        "actions": built,
        **metadata,
    }
    return state, pending, entry, mode


# Reject approximate or retyped integers before checking numeric model arithmetic.
def exact_integers(actual, expected, label):
    if type(expected) is int:
        require(
            type(actual) is int and actual == expected, label + " exact integer differs"
        )
    elif type(expected) is dict and type(actual) is dict:
        for key in expected.keys() & actual.keys():
            exact_integers(actual[key], expected[key], label + "." + str(key))
    elif type(expected) is list and type(actual) is list:
        for index, (left, right) in enumerate(zip(actual, expected, strict=False)):
            exact_integers(left, right, label + "." + str(index))


# Apply the producer's JSON representation without changing numeric quantities.
def serialized(value):
    return json.loads(json.dumps(live_policy_replay.plain(value), allow_nan=False))


# Compare all saved outputs while preserving original real written clocks verbatim.
def compare_saved(
    value, previous, state, pending, entry, settled, *, report, started, verified_at
):
    saved = value["nightly"]
    require(saved["status"] == "planned", "Expected original planned night")
    closing = live_policy_replay.instant(
        report.panel.dates[-1],
        calendar.session_close(report.panel.dates[-1].astype(object)),
    ) + timedelta(minutes=1)
    same(saved["session"], entry["session"], "Original nightly session")
    same(saved["at"], closing.isoformat(), "Original nightly decision clock")
    written = saved["entry"]["written"]
    written_at = instant(written)
    require(
        instant(started) <= written_at <= verified_at, "Original written clock differs"
    )
    if previous.history:
        require(
            instant(previous.history[-1]["written"]) <= written_at,
            "Original written history clock moved backwards",
        )
    if state.start_equity is None:
        state.start_equity = entry["equity"]
    expected = {
        **entry,
        "written": written,
        "pl": entry["equity"] - state.start_equity,
        "pl_pct": entry["equity"] / state.start_equity - 1
        if state.start_equity
        else 0.0,
        "settled": market_daily._settled_rows(settled, report.panel),
    }
    expected = serialized(expected)
    exact_integers(saved["entry"], expected, "Nightly entry")
    same(saved["entry"], expected, "Independent complete nightly entry")
    same(saved["persisted_policy"], state.policy_version, "Independent nightly policy")
    expected_pending = serialized(pending)
    exact_integers(value["new_intents"], expected_pending, "Funded intents")
    same(
        value["new_intents"],
        expected_pending,
        "Independent funded intents",
    )
    state.history = [
        row for row in previous.history if row["session"] != entry["session"]
    ] + [expected]
    expected_state = serialized(asdict(state))
    exact_integers(value["paper_state"], expected_state, "Nightly state")
    same(
        value["paper_state"],
        expected_state,
        "Independent complete nightly state",
    )
    return state
