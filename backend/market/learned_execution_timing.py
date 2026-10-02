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


# Replay unchanged target plans while only the timing policy chooses when to fill.
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
    book = _Book(len(panel.tickers), 1, cost_bps, panel, None, None)
    result = replay.account_arrays(panel, first)
    result["nav"][0] = result["cash"][0] = 1
    result["exposure"][0] = 0
    cashflows = np.zeros(len(panel.tickers))
    trades = np.zeros(len(panel.tickers), dtype=int)
    counts = dict.fromkeys(
        (
            "intents",
            "completed_intents",
            "expired_partial",
            "expired_unfilled",
            "fills",
            "waiting_decisions",
            "risk_refusals",
            "missing_execution",
            "missing_held_observation",
            "cash_limited_attempts",
            "closing_fills",
        ),
        0,
    )
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
            # Existing close window begins after the completed 15:30 bar.
            for clock in range(24):
                observed = dataset["current_close"][day, clock]
                if np.any(
                    (book.shares > 0) & (~np.isfinite(observed) | (observed <= 0))
                ):
                    counts["missing_held_observation"] += 1
                    continue
                nav = book.equity(observed)
                delta = wanted - book.shares
                pending = intent & ~attempted & (np.abs(delta) > 1e-10)
                known = np.isfinite(observed) & (observed > 0)
                acting = actions(
                    delta,
                    known,
                    pending,
                    observed,
                    nav,
                    budget,
                    forecasts[day, clock],
                    risk[day, clock],
                    cost_bps,
                    clock == 23,
                    counts,
                )
                # Lock the first decision before observing whether its price exists.
                attempted |= acting
                prices = (
                    closing[day] if clock == 23 else dataset["next_open"][day, clock]
                )
                counts["missing_execution"] += int(
                    (acting & (~np.isfinite(prices) | (prices <= 0))).sum()
                )
                request = np.where(acting, wanted, book.shares)
                budget, dollars, fees = replay.funded_fill(
                    book, request, prices, budget, day, f"learned_timing_{clock}"
                )
                filled = np.abs(dollars) > 1e-12
                counts["fills"] += int(filled.sum())
                counts["closing_fills"] += int(filled.sum()) if clock == 23 else 0
                trades += filled
                cashflows -= dollars + np.abs(dollars) * book.cost
                result["fees"][row] += fees
                result["turnover"][row] += float(np.abs(dollars).sum()) / nav
            remains = np.abs(wanted - book.shares) > 1e-10
            changed = np.abs(initial - book.shares) > 1e-10
            counts["completed_intents"] += int((intent & ~remains).sum())
            counts["expired_partial"] += int((intent & remains & changed).sum())
            counts["expired_unfilled"] += int((intent & remains & ~changed).sum())
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
    result["stocks"] = {
        ticker: {
            "net_gain_initial_nav_units": float(contribution[stock]),
            "fills": int(trades[stock]),
        }
        for stock, ticker in enumerate(panel.tickers)
    }
    return result
