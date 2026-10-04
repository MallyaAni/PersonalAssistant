"""Probability timing on the unchanged periodic grade-equal funded account.

The selector sees observed prices and reserved cash, never a prospective fill.
Its cash-bounded requested fraction is an ex-ante estimate; actual fill quantity
and price remain the shared ledger's responsibility. Frozen distributions are
supplied and authenticated externally; this adapter performs no calibration.
"""

from __future__ import annotations

import numpy as np

from backend.market import probabilistic_execution as probability
from backend.market.learned_execution_timing import replay_account, validate_replay
from backend.market.sequential_execution_replay import supported_sessions

POLICY = "probabilistic-funded-timing/1-research"
TERMINAL = 24


# Select pending requests from the frozen distribution and current reserved cash.
def select(
    provider,
    day,
    clock,
    delta,
    known,
    pending,
    observed,
    nav,
    budget,
    cost,
    final,
    counts,
    trace,
    symbols,
    date,
    offset,
):
    requesting = pending & known
    notional = np.maximum(delta, 0) * np.where(requesting, observed, 0)
    spend = float(notional.sum()) * (1 + cost / 1e4)
    fraction = min(1.0, budget / spend) if spend > 0 else 1.0
    acting = np.zeros(len(delta), dtype=bool)
    for stock in np.flatnonzero(requesting):
        buying = delta[stock] > 0
        weight = float(abs(delta[stock]) * observed[stock] / nav)
        weight *= fraction if buying else 1.0
        if final:
            chosen = probability.Decision("execute", reason="shared_terminal_deadline")
        else:
            distribution = provider(day, clock, int(stock))
            if distribution is not None and not isinstance(
                distribution, probability.Distribution
            ):
                raise ValueError("Provider must return a Distribution or explicit None")
            chosen = probability.decision(
                distribution,
                "buy" if buying else "sell",
                weight,
                cost,
                horizon=probability.HORIZON,
            )
        acting[stock] = chosen.state == "execute"
        counts["waiting_decisions"] += int(chosen.state == "wait")
        counts["distribution_unavailable"] += int(chosen.state == "unavailable")
        counts["unfunded_decisions"] += int(chosen.state == "no_trade")
        counts["cash_limited_decisions"] += int(buying and fraction < 1)
        trace.append(
            {
                "intent_id": f"{offset}/{date}/{symbols[stock]}",
                "day": int(day),
                "date": str(date),
                "clock": int(clock),
                "stock": int(stock),
                "symbol": symbols[stock],
                "side": "buy" if buying else "sell",
                "pending_quantity": float(abs(delta[stock])),
                "observed_price": float(observed[stock]),
                "nav": float(nav),
                "reserved_cash": float(budget),
                "all_pending_buy_spend": spend,
                "buy_funding_fraction": fraction,
                "trade_fraction": weight,
                "cost_bps": float(cost),
                "horizon": probability.HORIZON,
                "state": chosen.state,
                "expected_log_utility": chosen.expected_log_utility,
                "reason": chosen.reason,
                "terminal_action": bool(final),
                "funding_is_ex_ante": True,
            }
        )
    return acting


# Reject malformed quote grids and providers before invoking the account engine.
def _validate(panel, dataset, provider):
    if not callable(provider):
        raise ValueError("A read-only callable distribution provider required")
    shape = (len(panel.dates), 25, len(panel.tickers))
    if len(set(panel.tickers)) != len(panel.tickers) or "SPY" not in panel.tickers:
        raise ValueError("Unique stock identities including SPY required")
    for name in ("current_close", "next_open"):
        value = np.asarray(dataset[name])
        if (
            value.shape != shape
            or value.dtype.kind not in "fiu"
            or np.isinf(value).any()
        ):
            raise ValueError("Aligned numeric finite-or-missing quote grids required")


# Replay timing with the original plans, first attempts and funding ledger.
def account(
    panel,
    grades,
    eligible,
    dataset,
    distribution_provider,
    first,
    cost_bps,
    offset,
    *,
    supported_days=None,
):
    _validate(panel, dataset, distribution_provider)
    validate_replay(panel, grades, eligible, dataset, first, cost_bps, offset)
    if supported_days is None:
        supported_days = np.zeros(len(panel.dates), dtype=bool)
        supported_days[first:] = supported_sessions(panel.dates[first:])
    decisions = []

    # Choose a clock without receiving later execution prices or outcome labels.
    def choose(
        day, clock, delta, known, pending, observed, nav, budget, cost, final, counts
    ):
        return select(
            distribution_provider,
            day,
            clock,
            delta,
            known,
            pending,
            observed,
            nav,
            budget,
            cost,
            final,
            counts,
            decisions,
            panel.tickers,
            panel.dates[day],
            offset,
        )

    # Price the already locked attempt using the identical next-open outcome contract.
    def prices(day, clock, final):
        return dataset["next_open"][day, clock]

    result = replay_account(
        panel,
        grades,
        eligible,
        dataset,
        first,
        cost_bps,
        offset,
        choose,
        prices,
        TERMINAL,
        supported_days=supported_days,
        record_intents=True,
        decision_counts={
            "waiting_decisions": 0,
            "distribution_unavailable": 0,
            "unfunded_decisions": 0,
            "cash_limited_decisions": 0,
            "unsupported_plan_sessions": 0,
        },
    )
    result["policy"] = POLICY
    result["decision_trace"] = decisions
    return result
