"""Stock-conditioned execution timing without a distance-from-open trigger.

The waiting forecast and its second moment must describe the SAME immediate
versus one-decision-later price ratio. Ten-session holding risk is incompatible.
Expected-log utility is a second-order approximation, not optimal stopping.
The funded diagnostic retains the existing same-session closing deadline.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.agents.trading.desk import policy_v5
from backend.agents.trading.desk.simulate import _Book
from backend.market import learned_entry_evaluation as replay
from backend.market.fill_timing import session_scale

HORIZON = "one_decision_log_price_advantage"
POLICY = "learned-execution-risk/1"


# Carry an explicit decision and its expected utility rather than a price target.
@dataclass(frozen=True)
class TimingDecision:
    state: str
    waiting_utility: float | None = None
    variance: float | None = None
    reason: str = ""


# Compare waiting's stock-specific expected saving with its funded portfolio risk.
def decision(mean, second_moment, side, trade_fraction, cost_bps, *, horizon):
    if side not in ("buy", "sell") or horizon != HORIZON:
        raise ValueError("buy/sell and matching one-decision risk horizon required")
    if any(
        isinstance(value, (bool, np.bool_))
        for value in (
            mean,
            second_moment,
            trade_fraction,
            cost_bps,
        )
    ):
        return TimingDecision("unavailable", reason="invalid numeric forecast")
    try:
        mu, second, weight, cost = map(
            float, (mean, second_moment, trade_fraction, cost_bps)
        )
    except (TypeError, ValueError, OverflowError):
        return TimingDecision("unavailable", reason="invalid numeric forecast")
    if not np.isfinite([mu, second, weight, cost]).all():
        return TimingDecision("unavailable", reason="missing forecast or funding")
    if weight < 0 or weight > 1 or cost < 0 or cost >= 1e4:
        return TimingDecision("unavailable", reason="invalid funded trade or cost")
    if second < 0 or second < mu * mu:
        return TimingDecision("unavailable", reason="inconsistent forecast moments")
    if weight == 0:
        return TimingDecision("no_trade", reason="no funded trade")
    variance = second - mu * mu
    direction = 1 if side == "buy" else -1
    factor = 1 + direction * cost / 1e4
    effective = weight * factor
    saving = direction * (mu - 0.5 * second)
    utility = effective * saving - 0.5 * effective * effective * variance
    if not np.isfinite(utility):
        return TimingDecision("unavailable", reason="nonfinite utility")
    return TimingDecision("wait" if utility > 0 else "execute", utility, variance)


# Obtain an observed auction price for accounting without selecting by future prices.
def closing_prices(panel, cubes):
    prices = np.full(panel.adj_close.shape, np.nan)
    for stock, ticker in enumerate(panel.tickers):
        cube = cubes.get(ticker)
        if cube is None:
            continue
        positions, matched, scales = session_scale(
            cube, panel.dates, panel.adj_close[:, stock]
        )
        valid = matched & np.isfinite(scales) & (scales > 0)
        valid &= np.isfinite(cube.auction_open) & (cube.auction_open > 0)
        prices[positions[valid], stock] = cube.auction_open[valid] * scales[valid]
    return prices


# Choose funded stock actions separately from the existing closing deadline.
def actions(
    delta,
    known,
    pending,
    observed,
    nav,
    budget,
    means,
    risk,
    cost_bps,
    deadline,
    counts,
):
    if deadline:
        return pending & known
    cost = cost_bps / 1e4
    notional = np.maximum(delta, 0) * np.where(pending & known, observed, 0)
    spend = float(notional.sum()) * (1 + cost)
    fraction = min(1.0, budget / spend) if spend > 0 else 1.0
    acting = np.zeros(len(delta), dtype=bool)
    for stock in np.flatnonzero(pending & known):
        buying = delta[stock] > 0
        weight = abs(delta[stock]) * observed[stock] / nav
        weight *= fraction if buying else 1
        chosen = decision(
            means[stock, 2],
            risk[stock],
            "buy" if buying else "sell",
            weight,
            cost_bps,
            horizon=HORIZON,
        )
        acting[stock] = chosen.state == "execute"
        counts["waiting_decisions"] += int(chosen.state == "wait")
        counts["risk_refusals"] += int(chosen.state == "unavailable")
        counts["cash_limited_attempts"] += int(buying and fraction < 1)
    return acting


# Reject misaligned timelines and invalid account controls before any trading path.
def validate_account(
    panel, grades, eligible, dataset, forecasts, risk, closing, first, cost_bps, offset
):
    if (
        isinstance(first, (bool, np.bool_))
        or not isinstance(first, (int, np.integer))
        or not 1 <= first < len(panel.dates)
    ):
        raise ValueError("first session must have an actual prior plan session")
    shape = (len(panel.dates), 25, len(panel.tickers))
    if np.shape(forecasts) != (*shape, 3) or np.shape(risk) != shape:
        raise ValueError("aligned mean and short-horizon risk arrays required")
    if (
        closing.shape != panel.adj_close.shape
        or isinstance(offset, (bool, np.bool_))
        or not isinstance(offset, (int, np.integer))
        or not 0 <= offset < 20
    ):
        raise ValueError("aligned closing prices and a declared phase required")
    if (
        isinstance(cost_bps, (bool, np.bool_))
        or not isinstance(cost_bps, (int, float, np.integer, np.floating))
        or not np.isfinite(cost_bps)
        or not 0 <= cost_bps < 1e4
    ):
        raise ValueError("finite nonnegative cost below 10000bp required")
    if not np.array_equal(dataset["dates"], panel.dates):
        raise ValueError("prediction/account calendars differ")


# Validate common funded-account inputs independently of a particular forecast family.
def validate_replay(panel, grades, eligible, dataset, first, cost_bps, offset):
    if (
        isinstance(first, (bool, np.bool_))
        or not isinstance(first, (int, np.integer))
        or not 1 <= first < len(panel.dates)
    ):
        raise ValueError("first session must have an actual prior plan session")
    if (
        isinstance(offset, (bool, np.bool_))
        or not isinstance(offset, (int, np.integer))
        or not 0 <= offset < 20
    ):
        raise ValueError("a declared account phase is required")
    if (
        isinstance(cost_bps, (bool, np.bool_))
        or not isinstance(cost_bps, (int, float, np.integer, np.floating))
        or not np.isfinite(cost_bps)
        or not 0 <= cost_bps < 1e4
    ):
        raise ValueError("finite nonnegative cost below 10000bp required")
    shape = (len(panel.dates), len(panel.tickers))
    if np.shape(grades) != shape or np.shape(eligible) != shape:
        raise ValueError("grades and eligibility must match the source panel")
    if any(
        np.shape(dataset[key]) != (shape[0], 25, shape[1])
        for key in ("current_close", "next_open")
    ) or not np.array_equal(dataset["dates"], panel.dates):
        raise ValueError("observations and execution outcomes must match the panel")


# Open one trace per original intent using only its prior-close funded plan.
def intent_traces(panel, day, offset, targets, nav, prior, initial, wanted, budget):
    rows = {}
    for stock in np.flatnonzero(np.abs(wanted - initial) > 1e-10):
        rows[stock] = {
            "intent_id": (f"{offset}/{panel.dates[day]}/{panel.tickers[stock]}"),
            "date": str(panel.dates[day]),
            "symbol": panel.tickers[stock],
            "target_weight": float(targets[stock]),
            "prior_nav": float(nav),
            "prior_price": float(prior[stock]),
            "initial_shares": float(initial[stock]),
            "desired_shares": float(wanted[stock]),
            "morning_cash": float(budget),
            "side": "buy" if wanted[stock] > initial[stock] else "sell",
            "attempt_clock": None,
            "terminal_action": False,
            "observed_price": None,
            "realized_price": None,
            "filled_delta": 0.0,
            "fee": 0.0,
        }
    return rows


# Record the first selected attempt before its future execution price is observed.
def trace_attempts(rows, acting, clock, final, observed):
    for stock, trace in rows.items():
        if acting[stock]:
            trace["attempt_clock"] = int(clock)
            trace["terminal_action"] = final
            trace["observed_price"] = float(observed[stock])


# Attach actual price, quantity and fee evidence to the already locked attempt.
def trace_fills(rows, acting, prices, before_fill, book, dollars):
    for stock, trace in rows.items():
        if acting[stock]:
            price = prices[stock]
            trace["realized_price"] = (
                float(price) if np.isfinite(price) and price > 0 else None
            )
            trace["filled_delta"] = float(book.shares[stock] - before_fill[stock])
            trace["fee"] = float(abs(dollars[stock]) * book.cost)


# Settle every original intent into its completion, partial or unfilled category.
def settle_intents(book, wanted, initial, intent, counts, rows):
    remains = np.abs(wanted - book.shares) > 1e-10
    changed = np.abs(initial - book.shares) > 1e-10
    counts["completed_intents"] += int((intent & ~remains).sum())
    counts["expired_partial"] += int((intent & remains & changed).sum())
    counts["expired_unfilled"] += int((intent & remains & ~changed).sum())
    for stock, trace in rows.items():
        trace["outcome"] = (
            "completed"
            if not remains[stock]
            else "partial"
            if changed[stock]
            else "unfilled"
        )


# Choose and lock a clock's actions before pricing and funding those attempts.
def execute_clock(
    book,
    wanted,
    intent,
    attempted,
    observed,
    day,
    clock,
    terminal_clock,
    budget,
    cost_bps,
    choose_actions,
    execution_prices,
    counts,
    rows,
):
    if np.any((book.shares > 0) & (~np.isfinite(observed) | (observed <= 0))):
        counts["missing_held_observation"] += 1
        return None
    nav = book.equity(observed)
    delta = wanted - book.shares
    pending = intent & ~attempted & (np.abs(delta) > 1e-10)
    known = np.isfinite(observed) & (observed > 0)
    final = clock == terminal_clock
    acting = np.asarray(
        choose_actions(
            day,
            clock,
            delta,
            known,
            pending,
            observed,
            nav,
            budget,
            cost_bps,
            final,
            counts,
        )
    )
    if acting.dtype != bool or acting.shape != pending.shape:
        raise ValueError("selector must return a boolean action per stock")
    if np.any(acting & ~(pending & known)):
        raise ValueError("selector cannot act on unknown or finished intents")
    # Lock the first decision before observing whether its price exists.
    attempted |= acting
    trace_attempts(rows, acting, clock, final, observed)
    prices = np.asarray(execution_prices(day, clock, final))
    if prices.shape != pending.shape:
        raise ValueError("execution prices must align with the stock book")
    counts["missing_execution"] += int(
        (acting & (~np.isfinite(prices) | (prices <= 0))).sum()
    )
    request = np.where(acting, wanted, book.shares)
    before_fill = book.shares.copy() if rows else None
    budget, dollars, fees = replay.funded_fill(
        book, request, prices, budget, day, f"learned_timing_{clock}"
    )
    filled = np.abs(dollars) > 1e-12
    counts["fills"] += int(filled.sum())
    counts["closing_fills"] += int(filled.sum()) if final else 0
    trace_fills(rows, acting, prices, before_fill, book, dollars)
    return budget, dollars, fees, nav, filled


# Validate terminal/session permissions and keep selector counters separate from fills.
def replay_controls(panel, terminal_clock, supported_days, decision_counts):
    if (
        isinstance(terminal_clock, (bool, np.bool_))
        or not isinstance(terminal_clock, (int, np.integer))
        or not 0 <= terminal_clock < 25
    ):
        raise ValueError("terminal clock must belong to the declared session grid")
    if supported_days is None:
        supported_days = np.ones(len(panel.dates), dtype=bool)
    else:
        supported_days = np.asarray(supported_days)
        if supported_days.dtype != bool or supported_days.shape != panel.dates.shape:
            raise ValueError("session support must be explicit boolean calendar rows")
    counts = dict.fromkeys(
        (
            "intents",
            "completed_intents",
            "expired_partial",
            "expired_unfilled",
            "fills",
            "missing_execution",
            "missing_held_observation",
            "closing_fills",
        ),
        0,
    )
    if decision_counts:
        if set(decision_counts) & set(counts):
            raise ValueError("selector counters cannot overwrite account counters")
        counts.update(decision_counts)
    return supported_days, counts


# Carry one funded book through the same target plans while a selector sets its clock.
def replay_account(
    panel,
    grades,
    eligible,
    dataset,
    first,
    cost_bps,
    offset,
    choose_actions,
    execution_prices,
    terminal_clock,
    *,
    supported_days=None,
    record_intents=False,
    decision_counts=None,
):
    validate_replay(panel, grades, eligible, dataset, first, cost_bps, offset)
    supported_days, counts = replay_controls(
        panel, terminal_clock, supported_days, decision_counts
    )
    book = _Book(len(panel.tickers), 1, cost_bps, panel, None, None)
    result = replay.account_arrays(panel, first)
    result["nav"][0] = result["cash"][0] = 1
    result["exposure"][0] = 0
    cashflows = np.zeros(len(panel.tickers))
    trades = np.zeros(len(panel.tickers), dtype=int)
    traces = []
    for day in range(first, len(panel.dates)):
        row = day - first + 1
        if (day - first) % 20 == offset:
            prior = panel.adj_close[day - 1]
            targets = policy_v5.targets(
                grades[day - 1], prior, eligible[day - 1], panel.tickers.index("SPY")
            )
            nav = book.equity(prior)
            wanted = book.shares.copy()
            known = np.isfinite(prior) & (prior > 0)
            wanted[known] = targets[known] * nav / prior[known]
            initial = book.shares.copy()
            intent = np.abs(wanted - initial) > 1e-10
            attempted = np.zeros(len(panel.tickers), dtype=bool)
            counts["intents"] += int(intent.sum())
            budget = book.cash
            trace_rows = (
                intent_traces(
                    panel, day, offset, targets, nav, prior, initial, wanted, budget
                )
                if record_intents
                else {}
            )
            traces.extend(trace_rows.values())
            if not supported_days[day] and "unsupported_plan_sessions" in counts:
                counts["unsupported_plan_sessions"] += 1
            clocks = range(terminal_clock + 1) if supported_days[day] else ()
            for clock in clocks:
                execution = execute_clock(
                    book,
                    wanted,
                    intent,
                    attempted,
                    dataset["current_close"][day, clock],
                    day,
                    clock,
                    terminal_clock,
                    budget,
                    cost_bps,
                    choose_actions,
                    execution_prices,
                    counts,
                    trace_rows,
                )
                if execution is None:
                    continue
                budget, dollars, fees, nav, filled = execution
                trades += filled
                cashflows -= dollars + np.abs(dollars) * book.cost
                result["fees"][row] += fees
                result["turnover"][row] += float(np.abs(dollars).sum()) / nav
            settle_intents(book, wanted, initial, intent, counts, trace_rows)
        result["nav"][row] = book.equity(panel.adj_close[day])
        result["cash"][row] = book.cash
        result["exposure"][row] = 1 - book.cash / result["nav"][row]
    contribution = cashflows + book.shares * np.where(
        np.isfinite(panel.adj_close[-1]), panel.adj_close[-1], 0
    )
    if not np.isclose(contribution.sum(), result["nav"][-1] - 1, atol=1e-8):
        raise RuntimeError("timing-only stock wealth does not reconcile")
    if counts["intents"] != sum(
        counts[key]
        for key in (
            "completed_intents",
            "expired_partial",
            "expired_unfilled",
        )
    ):
        raise RuntimeError("timing-only intent denominator does not reconcile")
    result["counts"] = counts
    if record_intents:
        result["intent_trace"] = traces
    result["stocks"] = {
        ticker: {
            "net_gain_initial_nav_units": float(contribution[stock]),
            "fills": int(trades[stock]),
        }
        for stock, ticker in enumerate(panel.tickers)
    }
    return result


# Preserve the original one-step policy and auction-terminal accounting unchanged.
def account(
    panel, grades, eligible, dataset, forecasts, risk, closing, first, cost_bps, offset
):
    validate_account(
        panel,
        grades,
        eligible,
        dataset,
        forecasts,
        risk,
        closing,
        first,
        cost_bps,
        offset,
    )

    # Apply the original mean/risk decision at the supplied causal observation.
    def select(
        day, clock, delta, known, pending, observed, nav, budget, cost, final, counts
    ):
        return actions(
            delta,
            known,
            pending,
            observed,
            nav,
            budget,
            forecasts[day, clock],
            risk[day, clock],
            cost,
            final,
            counts,
        )

    # Keep the old terminal auction proxy separate from ordinary next-open outcomes.
    def prices_at(day, clock, final):
        return closing[day] if final else dataset["next_open"][day, clock]

    return replay_account(
        panel,
        grades,
        eligible,
        dataset,
        first,
        cost_bps,
        offset,
        select,
        prices_at,
        23,
        decision_counts={
            "waiting_decisions": 0,
            "risk_refusals": 0,
            "cash_limited_attempts": 0,
        },
    )
