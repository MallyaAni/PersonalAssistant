"""Research-only daily carried accounts with frozen prior-close share orders.

Prices are adjusted synthetic units, not broker fills. Grade-equal targets use
the existing rule at a daily cadence, not the full live rotation/execution path.
No same-plan sale proceeds may fund purchases. Every plan expires after one open.
"""

from __future__ import annotations

import numpy as np

from backend.agents.trading.desk import policy_v5
from backend.market import adaptive_growth_policy, allocation_controls

POLICY = "daily-arithmetic-funded-bridge/1"
METHODS = ("calibrated", "mean", "equal")


# Validate aligned causal observations and an explicit completed-close anchor.
def _inputs(panel, grades, eligible, means, method, cost_bps, first):
    dates, names = np.asarray(panel.dates), tuple(panel.tickers)
    if (
        dates.ndim != 1
        or dates.dtype != np.dtype("datetime64[D]")
        or np.isnat(dates).any()
        or np.any(dates[1:] <= dates[:-1])
        or not names
        or len(set(names)) != len(names)
        or "SPY" not in names
        or "QQQ" not in names
    ):
        raise ValueError("Complete chronological calendar and SPY/QQQ symbols required")
    if (
        isinstance(first, (bool, np.bool_))
        or not isinstance(first, (int, np.integer))
        or not 0 <= first < len(dates) - 1
    ):
        raise ValueError("Completed-close anchor must precede a next execution session")
    if (
        isinstance(cost_bps, (bool, np.bool_))
        or not isinstance(cost_bps, (int, float, np.integer, np.floating))
        or not np.isfinite(cost_bps)
        or not 0 <= cost_bps < 10000
        or method not in METHODS
    ):
        raise ValueError("Declared method and finite per-side cost required")
    shape = (len(dates), len(names))
    for field in ("open", "close", "adj_close"):
        values = np.asarray(getattr(panel, field))
        if (
            values.shape != shape
            or values.dtype.kind not in "fiu"
            or np.isinf(values).any()
            or np.any(np.isfinite(values) & (values <= 0))
        ):
            raise ValueError("Aligned positive-or-missing daily prices required")
    grades, eligible, means = (
        np.asarray(grades),
        np.asarray(eligible),
        np.asarray(means),
    )
    if (
        grades.shape != shape
        or grades.dtype.kind not in "fiu"
        or not np.isfinite(grades).all()
        or np.any(~np.isin(grades, [-1, 0, 1, 2, 3]))
        or eligible.shape != shape
        or eligible.dtype.kind != "b"
        or means.shape != shape
        or means.dtype.kind not in "fiu"
        or np.isinf(means).any()
    ):
        raise ValueError(
            "Aligned ordinal grades, eligibility and arithmetic means required"
        )
    if method != "equal" and first < 252:
        raise ValueError("Risk allocation needs 253 completed closes at the anchor")
    return dates, names, grades, eligible, means


# Mark every held quantity without treating unavailable prices as zero value.
def _nav(cash, shares, prices, names):
    held = shares > 0
    missing = held & (~np.isfinite(prices) | (prices <= 0))
    if missing.any():
        unavailable = ", ".join(names[i] for i in np.flatnonzero(missing))
        raise ValueError(f"Held close valuation unavailable: {unavailable}")
    value = np.zeros(len(shares))
    value[held] = shares[held] * prices[held]
    nav = float(cash + value.sum())
    if not np.isfinite(nav) or nav <= 0 or cash < -1e-12:
        raise ValueError("Nonpositive NAV or unfunded cash")
    return nav, value


# Freeze close-time quantities and preserve exact bounded no-change holdings.
def _plan(
    panel,
    grades,
    eligible,
    means,
    method,
    day,
    cash,
    shares,
    cost_bps,
    radii=None,
    *,
    hold_b=False,
):
    closes = np.asarray(panel.adj_close[day])
    names = tuple(panel.tickers)
    nav, values = _nav(cash, shares, closes, names)
    benchmark = np.array([names.index("SPY"), names.index("QQQ")])
    if method == "equal":
        membership = eligible[day].copy()
        membership[benchmark] = False
        target = policy_v5.targets(
            grades[day].copy(), closes.copy(), membership, benchmark[0]
        )
        receipt = {"status": "equal_rule", "policy": policy_v5.POLICY_VERSION}
    else:
        extra = {} if radii is None else {"trade_radius": np.asarray(radii[day]).copy()}
        extra.update({"hold_b": True} if hold_b else {})
        target, receipt = adaptive_growth_policy.allocate(
            np.asarray(panel.adj_close[: day + 1]).copy(),
            grades[day].copy(),
            eligible[day].copy(),
            means[day].copy(),
            values / nav,
            cash / nav,
            cost_bps,
            benchmark,
            mean_units="arithmetic",
            horizon_sessions=1,
            **extra,
        )
    target = np.asarray(target)
    if (
        target.shape != shares.shape
        or target.dtype.kind not in "fiu"
        or not np.isfinite(target).all()
        or np.any(target < 0)
        or np.any(target > policy_v5.HOLD_CAP + 1e-10)
        or target.sum() > 1 + 1e-10
        or np.any(target[benchmark] > 0)
    ):
        raise ValueError("Invalid target weights returned by daily allocator")
    current = values / nav
    desired = shares.copy()
    known = np.isfinite(closes) & (closes > 0)
    desired[known] = target[known] * nav / closes[known]
    if hold_b or (radii is not None and np.any(np.asarray(radii[day]) != 0)):
        unchanged = known & (target == current)
        desired[unchanged] = shares[unchanged]
    if receipt.get("status") == "unavailable":
        # Preserve exact ownership when risk is missing; retain real cap/exits.
        desired = shares.copy()
        trim = known & (target < current)
        desired[trim] = target[trim] * nav / closes[trim]
    if np.any((target > 0) & ~known):
        raise ValueError("Positive target has no completed-close share reference")
    if hold_b:
        bounded = grades[day] == 1
        if np.any(target[bounded] > current[bounded]):
            raise ValueError("Held-B target exceeds current ownership")
        desired[bounded] = np.minimum(desired[bounded], shares[bounded])
    if np.any((desired > shares + 1e-12) & (~eligible[day] | (grades[day] < 2))):
        raise ValueError("Daily allocator attempted an ineligible addition")
    plan = {
        "decision_index": int(day),
        "decision_session": str(panel.dates[day]),
        "nav": nav,
        "cash_budget": float(cash),
        "current_weights": current.copy(),
        "targets": target.astype(float, copy=True),
        "desired_shares": desired,
        "submitted_delta": desired - shares,
        "held_before": shares.copy(),
        "prices": closes.copy(),
        "receipt": receipt,
    }
    if radii is not None:
        plan["trade_radius"] = np.asarray(radii[day]).copy()
    return plan


# Execute one expiring plan without recycling sale proceeds into its buy budget.
def _execute(
    plan, prices, shares, cash, basis, realized, cashflows, cost, names, session
):
    delta = np.asarray(plan["submitted_delta"])
    before = shares.copy()
    known = np.isfinite(prices) & (prices > 0)
    buys, sells = np.maximum(delta, 0), np.minimum(np.maximum(-delta, 0), shares)
    known_spend = float((buys[known] * prices[known]).sum()) * (1 + cost)
    budget = min(float(plan["cash_budget"]), float(cash))
    scale = min(1.0, budget / known_spend) if known_spend > 0 else 0.0
    executed = np.where(known, buys * scale - sells, 0.0)
    notional = executed * np.where(known, prices, 0.0)
    fees = np.abs(notional) * cost
    sale = executed < 0
    removed_basis = np.zeros(len(shares))
    removed_basis[sale] = basis[sale] * (-executed[sale] / shares[sale])
    profit = np.where(sale, -notional - fees - removed_basis, 0)
    basis += np.maximum(notional, 0) + np.where(executed > 0, fees, 0) - removed_basis
    realized += profit
    cashflows -= notional + fees
    cash -= float((notional + fees).sum())
    shares += executed
    if cash < -1e-12 or np.any(shares < -1e-12) or np.any(basis < -1e-12):
        raise RuntimeError("Covered quantity or pre-sale funding invariant failed")
    cash = max(0.0, cash)
    basis[shares == 0] = 0
    intents = []
    for column in np.flatnonzero(delta != 0):
        status = (
            "missing_open"
            if not known[column]
            else (
                "filled"
                if np.isclose(executed[column], delta[column], rtol=1e-12, atol=1e-15)
                else "cash_limited"
            )
        )
        intents.append(
            {
                "id": f"{plan['decision_session']}:{names[column]}",
                "decision_session": plan["decision_session"],
                "execution_session": str(session),
                "symbol": names[column],
                "side": "buy" if delta[column] > 0 else "sell",
                "requested_delta": float(delta[column]),
                "filled_delta": float(executed[column]),
                "unfilled_delta": float(delta[column] - executed[column]),
                "price": float(prices[column]) if known[column] else None,
                "fee": float(fees[column]),
                "removed_basis": float(removed_basis[column]),
                "realized_profit": float(profit[column]),
                "held_before": float(before[column]),
                "cash_budget": budget,
                "buy_scale": scale,
                "status": status,
                "expires_after_open": True,
            }
        )
    return cash, float(fees.sum()), float(np.abs(notional).sum()), intents


# Allocate complete carried-state evidence without creating an output artifact.
def _arrays(dates, names, first):
    count, stocks = len(dates) - first, len(names)
    result = {
        "dates": dates[first:].copy(),
        "symbols": list(names),
        "nav": np.full(count, np.nan),
        "cash": np.full(count, np.nan),
        "exposure": np.full(count, np.nan),
        "turnover": np.zeros(count),
        "fees": np.zeros(count),
        "gross_notional": np.zeros(count),
        "shares": np.zeros((count, stocks)),
        "cost_basis": np.zeros((count, stocks)),
        "realized_profit": np.zeros((count, stocks)),
        "cashflows": np.zeros((count, stocks)),
        "intent_trace": [],
        "allocation_trace": [],
        "counts": {
            "plans": 0,
            "intents": 0,
            "filled_intents": 0,
            "missing_open": 0,
            "cash_limited": 0,
            "allocator_unavailable": 0,
        },
    }
    return result


# Retain a closing account and its per-stock fee-inclusive profit decomposition.
def _record(result, local, cash, shares, basis, realized, cashflows, prices, names):
    nav, values = _nav(cash, shares, prices, names)
    result["nav"][local], result["cash"][local] = nav, cash
    result["exposure"][local] = float(values.sum() / nav)
    for key, values in (
        ("shares", shares),
        ("cost_basis", basis),
        ("realized_profit", realized),
        ("cashflows", cashflows),
    ):
        result[key][local] = values


# Assemble terminal per-stock reconciliation without treating exits as profits.
def _finish(result, shares, basis, realized, cashflows, marks, names):
    values = np.zeros(len(shares))
    held = shares > 0
    values[held] = shares[held] * marks[held]
    unrealized = values - basis
    contribution = realized + unrealized
    if not np.isclose(
        contribution.sum(), result["nav"][-1] - 1, rtol=1e-10, atol=1e-12
    ):
        raise RuntimeError("Fee-inclusive stock profit does not reconcile to NAV")
    result["stocks"] = {
        name: {
            "shares": float(shares[i]),
            "cost_basis": float(basis[i]),
            "realized_profit": float(realized[i]),
            "unrealized_profit": float(unrealized[i]),
            "cashflows": float(cashflows[i]),
            "marked_value": float(values[i]),
            "net_gain_initial_nav_units": float(contribution[i]),
        }
        for i, name in enumerate(names)
    }
    return result


# Carry daily funded books with explicit optional held-B and error-band decisions.
def run_account(
    panel,
    grades,
    eligible,
    means,
    *,
    method,
    cost_bps,
    first,
    radii=None,
    hold_b=False,
):
    if not isinstance(hold_b, (bool, np.bool_)) or (hold_b and method != "calibrated"):
        raise ValueError("Boolean held-B option requires the learned risk arm")
    dates, names, grades, eligible, means = _inputs(
        panel,
        grades,
        eligible,
        means,
        method,
        cost_bps,
        first,
    )
    if radii is not None:
        radii = np.asarray(radii)
        if (
            method == "equal"
            or radii.shape != np.shape(panel.adj_close)
            or radii.dtype.kind not in "fiu"
            or np.isinf(radii).any()
            or np.any(np.isfinite(radii) & (radii < 0))
        ):
            raise ValueError("Aligned nonnegative-or-missing risk-arm radii required")
    opens = allocation_controls.adjusted_open(panel.open, panel.close, panel.adj_close)
    result = _arrays(dates, names, first)
    shares, basis, realized, cashflows = (np.zeros(len(names)) for _ in range(4))
    cash, cost = 1.0, float(cost_bps) / 1e4
    _record(
        result,
        0,
        cash,
        shares,
        basis,
        realized,
        cashflows,
        panel.adj_close[first],
        names,
    )
    plan = None
    for day in range(first, len(dates)):
        local = day - first
        if plan is not None:
            cash, fees, traded, intents = _execute(
                plan,
                opens[day],
                shares,
                cash,
                basis,
                realized,
                cashflows,
                cost,
                names,
                dates[day],
            )
            result["fees"][local] = fees
            result["gross_notional"][local] = traded
            result["turnover"][local] = traded / plan["nav"]
            result["intent_trace"].extend(intents)
            result["counts"]["intents"] += len(intents)
            for intent in intents:
                result["counts"][
                    intent["status"]
                    if intent["status"] != "filled"
                    else "filled_intents"
                ] += 1
            _record(
                result,
                local,
                cash,
                shares,
                basis,
                realized,
                cashflows,
                panel.adj_close[day],
                names,
            )
        plan = _plan(
            panel,
            grades,
            eligible,
            means,
            method,
            day,
            cash,
            shares,
            cost_bps,
            radii,
            **({"hold_b": True} if hold_b else {}),
        )
        result["allocation_trace"].append(plan)
        result["counts"]["plans"] += 1
        if plan["receipt"].get("status") == "unavailable":
            result["counts"]["allocator_unavailable"] += 1
    result.update(
        policy=POLICY,
        method=method,
        cost_bps=float(cost_bps),
        first=int(first),
        price_basis="adjusted_synthetic_units_from_open_times_adjusted_close_over_close",
        pending_plan=plan,
        decision_clock="previous_completed_close",
        execution_clock="next_official_open_proxy",
        prices={
            "open": opens[first:].copy(),
            "close": np.asarray(panel.adj_close[first:]).copy(),
        },
    )
    result["returns"] = np.r_[np.nan, result["nav"][1:] / result["nav"][:-1] - 1]
    if hold_b:
        result.update(policy="learned-held-exits-funded/1-research", hold_b=True)
    if radii is not None:
        result["trade_radius"] = radii[first:].copy()
    return _finish(
        result, shares, basis, realized, cashflows, panel.adj_close[-1], names
    )


# Buy one ETF at the matched next open and retain it through the common last close.
def benchmark_account(panel, *, ticker, cost_bps, first):
    shape = np.shape(panel.adj_close)
    dates, names, _, _, _ = _inputs(
        panel,
        np.full(shape, 2),
        np.ones(shape, bool),
        np.full(shape, np.nan),
        "equal",
        cost_bps,
        first,
    )
    if ticker not in ("SPY", "QQQ"):
        raise ValueError("Declared SPY or QQQ benchmark required")
    column, cost = names.index(ticker), float(cost_bps) / 1e4
    opens = allocation_controls.adjusted_open(panel.open, panel.close, panel.adj_close)
    if not np.isfinite(opens[first + 1, column]):
        raise ValueError("Missing common benchmark opening purchase")
    result = _arrays(dates, names, first)
    shares, basis, realized, cashflows = (np.zeros(len(names)) for _ in range(4))
    _record(
        result,
        0,
        1.0,
        shares,
        basis,
        realized,
        cashflows,
        panel.adj_close[first],
        names,
    )
    quantity = 1 / (opens[first + 1, column] * (1 + cost))
    shares[column], basis[column], cashflows[column] = quantity, 1.0, -1.0
    result["fees"][1] = quantity * opens[first + 1, column] * cost
    result["turnover"][1] = quantity * opens[first + 1, column]
    result["gross_notional"][1] = result["turnover"][1]
    result["intent_trace"].append(
        {
            "id": f"{dates[first]}:{ticker}",
            "decision_session": str(dates[first]),
            "execution_session": str(dates[first + 1]),
            "symbol": ticker,
            "side": "buy",
            "requested_delta": quantity,
            "filled_delta": quantity,
            "unfilled_delta": 0.0,
            "price": float(opens[first + 1, column]),
            "fee": float(result["fees"][1]),
            "removed_basis": 0.0,
            "realized_profit": 0.0,
            "held_before": 0.0,
            "cash_budget": 1.0,
            "buy_scale": 1.0,
            "status": "filled",
            "expires_after_open": True,
            "order_type": "benchmark_cash_notional_purchase_at_open",
        }
    )
    result["counts"].update(plans=1, intents=1, filled_intents=1)
    for day in range(first + 1, len(dates)):
        _record(
            result,
            day - first,
            0.0,
            shares,
            basis,
            realized,
            cashflows,
            panel.adj_close[day],
            names,
        )
    result.update(
        policy="daily-arithmetic-bridge-etf-buyhold/1",
        method=ticker,
        cost_bps=float(cost_bps),
        first=int(first),
        prices={
            "open": opens[first:].copy(),
            "close": np.asarray(panel.adj_close[first:]).copy(),
        },
    )
    result["returns"] = np.r_[np.nan, result["nav"][1:] / result["nav"][:-1] - 1]
    return _finish(
        result, shares, basis, realized, cashflows, panel.adj_close[-1], names
    )
