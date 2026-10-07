"""Manual personal guidance from adopted learned weights and execution forecasts.

The person's declared account is never a broker-verified balance. Paper holdings,
paper cash and anticipated sale proceeds are not funding for this response.
"""

import math
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import allocation, funded_execution, intraday_orders
from backend.market import (
    adaptive_growth_policy,
    calendar,
    decision_view,
    desk_freshness,
    entry_timing,
    execution_quotes,
    holdings,
    learned_live_holding,
    learned_live_timing,
)
from backend.market import forward_probability_timing as timing
from backend.market.joint_funded_policy import MARKET_TIMED_POLICY
from backend.market.live_probability_timing import POLICY

VERSION = "learned-personal-guidance/1"


# Select this path only for a dated record that explicitly names the learned policy.
def adopted(record):
    return (record.get("targets") or {}).get("policy") == MARKET_TIMED_POLICY


# Preserve neutral chart and grade metadata while removing every legacy action gate.
def _neutral(record, held, equity, snapshot, quoted, now, account):
    weights = {name: 0.0 for name in record.get("grades") or {}}
    result = decision_view.build(
        record,
        held,
        equity,
        snapshot,
        quoted,
        now,
        weights,
        expected_account=account,
    )
    result.update(
        version=VERSION,
        policy=MARKET_TIMED_POLICY,
        account_basis="manual_personal_inputs_not_broker_verified",
        portfolio_allocation=None,
    )
    result.pop("timing", None)
    technical, value = desk_freshness.grade_inputs(snapshot, record, now)
    readings = holdings.live_grades(record, technical, value)
    for name, row in result["rows"].items():
        for key in (
            "timing",
            "entry_status",
            "entry_reason",
            "entry_action",
            "risk_plan",
            "missing_sessions",
        ):
            row.pop(key, None)
        row.update(
            action="Hold",
            move_weight=0.0,
            strategy_action="Hold",
            strategy_move_weight=0.0,
            executable=False,
            valid_until=None,
            blocker="Learned guidance unavailable",
            reason="Learned guidance unavailable",
            grade=((record.get("grades") or {}).get(name) or {}).get("grade"),
            grade_intraday=(readings.get(name) or {}).get("grade_live"),
        )
    return result


# Require the reviewed release and the exact selected weights of its dated plan.
def _approve(root, record, now):
    raw, config = learned_live_holding.read_configuration(root, now)
    paper = record.get("paper") or {}
    targets = record.get("targets") or {}
    weights = targets.get("weights")
    if (
        not adopted(record)
        or paper.get("policy") != MARKET_TIMED_POLICY
        or paper.get("selected_targets") != targets
        or (paper.get("learned_holding") or {}).get("config_sha256")
        != sha256(raw).hexdigest()
        or not isinstance(weights, dict)
        or set(weights) != set(record.get("grades") or {})
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= adaptive_growth_policy.CAP
            for value in weights.values()
        )
        or sum(weights.values()) > 1 + 1e-10
    ):
        raise ValueError("Exact approved learned plan required")
    offset = calendar._future_session_offset(
        np.datetime64(record["session"]),
        np.datetime64(now.date()),
    )
    if offset not in (0, 1):
        raise ValueError("Learned plan is stale")
    if (
        sha256((Path(root) / learned_live_timing.CONFIG).read_bytes()).hexdigest()
        != config["timing_config_sha256"]
    ):
        raise ValueError("Installed holding and timing configuration differ")
    return raw, config, dict(weights)


# Validate current quote marks and the person's explicit whole-share quantities.
def _account(result, held, equity, cash):
    if cash is not None:
        decision_view._validate_cash(cash, equity)
    shares, prices = {}, {}
    for position in held:
        if (
            position.ticker in shares
            or not math.isfinite(position.shares)
            or position.shares <= 0
            or position.shares != math.floor(position.shares)
        ):
            raise ValueError("Unique personal whole-share holdings required")
        shares[position.ticker] = int(position.shares)
    for name, row in result["rows"].items():
        quote = row["quote"]
        if quote.get("eligible") and quote.get("spread_verified") is True:
            prices[name] = quote["bid"] / 2 + quote["ask"] / 2
    if any(name not in prices for name in shares):
        raise ValueError("Current price required for every personal holding")
    return shares, prices


# Preserve uncovered holdings and cap additions by explicit cash, pending buys and risk.
def _basket(
    result,
    record,
    shares,
    prices,
    weights,
    equity,
    cash,
    pending,
    budget,
    snapshot,
    now,
    cost,
):
    desired = dict(weights)
    technical, _ = desk_freshness.grade_inputs(snapshot, record, now)
    expiries = desk_freshness.grade_expiries(snapshot, technical)
    paused = record.get("event_risk") or {}
    no_buys = (
        paused.get("factor") == 0.5
        or paused.get("execution_pending")
        or paused.get("calendar_known") is False
    )
    references = {}
    for name, row in result["rows"].items():
        current = shares.get(name, 0) * prices.get(name, 0) / equity
        target = desired.get(name, current)
        if name in desired and (record["grades"][name] or {}).get("grade") == "C":
            target = 0.0
        row.update(
            target_weight=target, current_weight=current, delta_weight=target - current
        )
        row.update(blocker=None, reason="At learned target")
        gap = target - current
        row.update(
            strategy_action="Buy" if gap > 0 else "Sell" if gap < 0 else "Hold",
            strategy_move_weight=gap,
        )
        decision_view._apply_risk_budget(
            row,
            name,
            snapshot,
            current,
            name in technical,
            expiries.get(name),
            now,
            budget,
            personal=True,
        )
        if target > current:
            if no_buys or name in pending:
                target = current
                row["blocker"] = "FOMC pause" if no_buys else "Personal buy pending"
            elif budget is not None:
                plan = row["risk_plan"]
                target = current + (
                    plan["max_add_weight"] if plan["status"] == "available" else 0.0
                )
            if cash is None:
                target = current
                row["blocker"] = "Available cash unconfirmed"
        desired[name] = target
        quote = row["quote"]
        if name in prices:
            references[name] = (
                prices[name]
                if target == current
                else quote["ask"]
                if target > current
                else quote["bid"]
            )
    if sum(desired.values()) > 1 + 1e-10:
        raise ValueError(
            "Selected weights and protected holdings exceed personal equity"
        )
    decision = allocation.AllocationDecision(
        MARKET_TIMED_POLICY,
        record["session"],
        desired,
        max(0.0, 1 - sum(desired.values())),
        True,
        (),
        (),
        None,
        allocation.BINDING_NONE,
    )
    return funded_execution.plan_funded(
        decision,
        shares,
        references,
        equity,
        cash or 0.0,
        cost_bps=cost,
        whole_shares=True,
        index_eligible=False,
        entry_cap=adaptive_growth_policy.CAP,
        min_trade=0.0,
    )


# Build one current whole-share basket without reserving proceeds from its sells.
def _plan(
    result,
    record,
    held,
    equity,
    cash,
    weights,
    pending,
    budget,
    snapshot,
    now,
    cost,
    account,
):
    shares, prices = _account(result, held, equity, cash)
    basket = _basket(
        result,
        record,
        shares,
        prices,
        weights,
        equity,
        cash,
        set(pending or ()),
        budget,
        snapshot,
        now,
        cost,
    )
    if basket.blocked:
        raise ValueError(basket.reason)
    intents = _intents(basket, record, account, now)
    ordered = {intent["symbol"] for intent in intents}
    for name, row in result["rows"].items():
        if name not in ordered and row["strategy_action"] != "Hold":
            row.update(reason=row["blocker"] or "No funded whole-share adjustment")
    return shares, intents


# Keep mandatory company exits out of the discretionary learned timing reader.
def _ordinary(intents, record):
    return [
        intent
        for intent in intents
        if not (
            intent["side"] == "sell"
            and record["grades"][intent["symbol"]].get("grade") == "C"
        )
    ]


# Refresh captured prices and recheck older quotes at inference completion.
def _quote_rows(result, snapshot, packet, now):
    for name, quote in (packet.snapshot["quotes"] if packet else {}).items():
        snapshot.setdefault("quotes", {})[name] = deepcopy(quote)
        if name in result["rows"]:
            result["rows"][name]["quote"] = {**quote, "at": quote["as_of"]}
    for row in result["rows"].values():
        quote = row["quote"]
        row["quote"] = execution_quotes.describe(
            {
                "bp": quote.get("bid"),
                "ap": quote.get("ask"),
                "bs": quote.get("bid_size"),
                "as": quote.get("ask_size"),
                "t": quote.get("at"),
            },
            quote.get("feed"),
            True,
            now,
        )


# Keep unavailable timing from suppressing an independently supported company exit.
def _acquire(root, result, now, ordinary, clock, transport):
    try:
        return learned_live_timing.acquire(
            root,
            now,
            symbols=[intent["symbol"] for intent in ordinary],
            clock=clock,
            transport=transport,
        )
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        learned_live_timing.market.source.CaptureError,
    ) as exc:
        result["learned_unavailable"] = str(exc)
        return None


# Translate the funded basket into original named probabilistic timing intents.
def _intents(basket, record, account, now):
    identity = timing._digest(
        {
            "account": account,
            "session": now.date().isoformat(),
            "desired": basket.desired,
        }
    )
    return [
        {
            "symbol": order.symbol,
            "side": order.side,
            "qty": int(order.qty),
            "client_order_id": "personal-"
            + identity[:20]
            + "-"
            + order.symbol
            + "-"
            + order.side,
            "session": record["session"],
            "execute_on": now.date().isoformat(),
            "execution_timing": intraday_orders.INTRADAY_TIMING,
            "timing_policy": POLICY,
        }
        for order in basket.orders
    ]


# Supply declared personal funding without reading or copying the paper account.
def _personal_receipt(equity, cash, shares, completed, now):
    receipt = {
        "reason": "",
        "nav": equity,
        "budget": cash or 0.0,
        "held": shares,
        "captured_at": now.isoformat(),
        "completed_at": completed.isoformat(),
        "basis": "manual_personal_inputs_not_broker_verified",
    }
    return {"receipt": receipt, "receipt_sha256": timing._digest(receipt)}


# Use learned timing only for ordinary gaps; company exits retain their immediate path.
def _apply(result, record, intents, reader, snapshot, now, equity, cost):
    clock = entry_timing.session_clock(now.date())
    quotes = snapshot.get("quotes") or {}
    for intent in intents:
        name, side = intent["symbol"], intent["side"]
        row = result["rows"][name]
        quote = row["quote"]
        mandatory = (
            side == "sell" and (record["grades"].get(name) or {}).get("grade") == "C"
        )
        final = clock["final"] <= now < clock["close"]
        if mandatory or final:
            execute, reason, evidence = (
                True,
                "Company exit" if mandatory else "Session completion",
                None,
            )
        elif reader is None:
            execute, reason, evidence = False, "Learned observation unavailable", None
        else:
            verdict = reader(intent, {}, quotes.get(name), now, now.date())
            evidence = verdict["timed"]
            execute = verdict["send"] is not None
            reason = (
                "Learned timing ready"
                if execute
                else evidence["reason"] or "Learned timing waiting"
            )
        price = quote["ask"] if side == "buy" else quote["bid"]
        move = intent["qty"] * price / equity * (1 if side == "buy" else -1)
        row.update(
            action="Buy"
            if execute and side == "buy"
            else "Sell"
            if execute
            else "Hold",
            move_weight=move if execute else 0.0,
            executable=execute,
            blocker=None if execute else reason,
            reason=reason,
            valid_until=min(
                desk_freshness.timestamp(quote["valid_until"]),
                now + timedelta(seconds=execution_quotes.MAX_AGE_SECONDS),
                clock["close"],
            ).isoformat(),
            timing={
                "state": "triggered" if execute else "waiting",
                "rule": POLICY,
                "side": side,
                "session": now.date().isoformat(),
                "trading_day": True,
                "level_fraction": None,
                "close_cutoff": clock["cutoff"].isoformat(),
                "moc_deadline": clock["moc"].isoformat(),
                "open": (quotes.get(name) or {}).get("open"),
                "level": None,
                "trigger_bar": evidence.get("trigger_bar") if evidence else None,
                "trigger_price": price if execute else None,
                "reason": reason,
            },
            learned_timing=evidence,
            planned_qty=intent["qty"],
            sizing_cost_bps=cost,
        )


# Return manual learned guidance without incumbent fallback after learned failure.
def build(
    root,
    record,
    held,
    equity,
    snapshot,
    quoted,
    now,
    *,
    cash=None,
    pending=None,
    risk_budget_pct=None,
    expected_account=None,
    clock=None,
    transport=None,
):
    now = now.astimezone(calendar.NEW_YORK)
    result = _neutral(record, held, equity, snapshot, quoted, now, expected_account)
    current_snapshot = deepcopy(snapshot)
    try:
        raw, config, weights = _approve(root, record, now)
        session_clock = entry_timing.session_clock(now.date())
        if (
            not session_clock
            or not session_clock["open"] <= now < session_clock["close"]
        ):
            raise ValueError("Regular session closed")
        result["timing"] = {
            "rule": POLICY,
            "level": None,
            "session": now.date().isoformat(),
            "close_cutoff": session_clock["cutoff"].isoformat(),
            "moc_deadline": session_clock["moc"].isoformat(),
            "latched": False,
        }
        shares, intents = _plan(
            result,
            record,
            held,
            equity,
            cash,
            weights,
            pending,
            risk_budget_pct,
            snapshot,
            now,
            config["cost_bps"],
            expected_account,
        )
        ordinary = _ordinary(intents, record)
        reader = None
        if (
            ordinary
            and session_clock["open"] + entry_timing.BAR <= now < session_clock["final"]
        ):
            observation = _acquire(root, result, now, ordinary, clock, transport)
            actual = (clock or (lambda: datetime.now(calendar.NEW_YORK)))().astimezone(
                calendar.NEW_YORK
            )
            if observation:
                learned_live_timing.validate_observation(root, observation, actual)
            if observation and observation.config["cost_bps"] != config["cost_bps"]:
                raise ValueError("Personal and execution cost configuration differ")
            # Recompute funding at captured prices and retain original grade clocks.
            _quote_rows(
                result,
                current_snapshot,
                observation.packet if observation else None,
                actual,
            )
            now = actual
            result["timing"]["latched"] = observation is not None
            shares, intents = _plan(
                result,
                record,
                held,
                equity,
                cash,
                weights,
                pending,
                risk_budget_pct,
                snapshot,
                now,
                config["cost_bps"],
                expected_account,
            )
            ordinary = _ordinary(intents, record)
            reader = (
                timing.build_forecast_reader(
                    observation.forecast,
                    now,
                    observation.packet.snapshot,
                    ordinary,
                    _personal_receipt(equity, cash, shares, observation.completed, now),
                    config["cost_bps"],
                    [],
                    evidence_root=Path(root),
                )
                if ordinary and observation
                else None
            )
        if (Path(root) / learned_live_holding.CONFIG).read_bytes() != raw:
            raise ValueError("Installed holding configuration changed during guidance")
        if _approve(root, record, now)[0] != raw:
            raise ValueError("Reviewed personal release changed during guidance")
        result["as_of"] = now.isoformat()
        _apply(
            result,
            record,
            intents,
            reader,
            current_snapshot,
            now,
            equity,
            config["cost_bps"],
        )
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        learned_live_timing.market.source.CaptureError,
    ) as exc:
        for row in result["rows"].values():
            row.update(
                action="Hold",
                move_weight=0.0,
                executable=False,
                valid_until=None,
                blocker=str(exc),
                reason=str(exc),
            )
            row.pop("timing", None)
    return result, current_snapshot
