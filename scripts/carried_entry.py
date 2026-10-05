"""Isolate an entry deadline's effect without changing selection or exit timing.

Research only. An unattempted buy survives until the next scheduled plan;
its original quantity and remaining original cash budget are preserved.
Sales keep their original same-session deadline. No new same-day sale
proceeds become purchase funding, even on later sessions.
"""

import numpy as np

from backend.agents.trading.desk import policy_v5
from backend.agents.trading.desk.simulate import _Book
from backend.market import learned_entry_evaluation as ledger
from backend.market import learned_execution_timing as timing
from backend.market import sequential_execution_replay as selector


# Preserve ordinary gate decisions while allowing only buys to cross a deadline.
def actions(opened, observed, delta, known, pending, final, counts, carry):
    regular = selector.gate(opened, observed, delta, known, pending, False, counts)
    return regular | (pending & known & final & ((delta < 0) | (not carry)))


# Carry frozen plan quantities and funding until replacement by the next plan.
def account(panel, grades, eligible, dataset, opens, first, phase, support, carry,
            buy_forecasts=None):
    timing.validate_replay(panel, grades, eligible, dataset, first, 0, phase)
    support, counts = timing.replay_controls(panel, 24, support, {
        "waiting_decisions": 0, "opening_unavailable": 0,
        "unsupported_plan_sessions": 0,
    })
    book = _Book(len(panel.tickers), 1, 0, panel, None, None)
    result = ledger.account_arrays(panel, first)
    result["nav"][0] = result["cash"][0] = 1
    result["exposure"][0] = 0
    flows = np.zeros(len(panel.tickers))
    trades = np.zeros(len(panel.tickers), dtype=int)
    traces, rows = [], {}
    active = False
    for day in range(first, len(panel.dates)):
        slot = day - first + 1
        plan_day = (day - first) % 20 == phase
        if plan_day:
            if active:
                timing.settle_intents(book, wanted, initial, intent, counts, rows)
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
            attempted = np.zeros(len(wanted), dtype=bool)
            counts["intents"] += int(intent.sum())
            budget = book.cash
            rows = timing.intent_traces(
                panel, day, phase, targets, nav, prior, initial, wanted, budget
            )
            traces.extend(rows.values())
            active = True
            counts["unsupported_plan_sessions"] += int(not support[day])
        if active and support[day] and (plan_day or carry):
            pending = intent & ~attempted
            if not plan_day:
                # An expired sale must never become a delayed sell intervention.
                pending &= wanted > initial
            if np.any(pending):
                for clock in range(25):
                    observed = dataset["current_close"][day, clock]
                    if np.any((book.shares > 0) & (~np.isfinite(observed) | (observed <= 0))):
                        counts["missing_held_observation"] += 1
                        continue
                    known = np.isfinite(observed) & (observed > 0)
                    delta = wanted - book.shares
                    available = pending & ~attempted & (np.abs(delta) > 1e-10)
                    acting = actions(opens[day], observed, delta, known, available,
                                     clock == 24, counts, carry)
                    if buy_forecasts is not None:
                        value = buy_forecasts[day, clock]
                        buys = available & known & (delta > 0)
                        acting = (acting & (delta < 0)) | (
                            buys & np.isfinite(value) & (value <= 0)
                        )
                    attempted |= acting
                    timing.trace_attempts(rows, acting, clock, clock == 24, observed)
                    for stock in np.flatnonzero(acting):
                        rows[stock]["attempt_date"] = str(panel.dates[day])
                    # Only now may the ledger inspect the subsequent execution bar.
                    prices = dataset["next_open"][day, clock]
                    counts["missing_execution"] += int(
                        (acting & (~np.isfinite(prices) | (prices <= 0))).sum()
                    )
                    before = book.shares.copy()
                    nav = book.equity(observed)
                    budget, dollars, fees = ledger.funded_fill(
                        book, np.where(acting, wanted, book.shares), prices,
                        budget, day, f"carried_entry_{clock}"
                    )
                    timing.trace_fills(rows, acting, prices, before, book, dollars)
                    filled = np.abs(dollars) > 1e-12
                    counts["fills"] += int(filled.sum())
                    counts["closing_fills"] += int(filled.sum()) if clock == 24 else 0
                    trades += filled
                    flows -= dollars
                    result["fees"][slot] += fees
                    result["turnover"][slot] += float(np.abs(dollars).sum()) / nav
            if not carry:
                timing.settle_intents(book, wanted, initial, intent, counts, rows)
                active = False
        result["nav"][slot] = book.equity(panel.adj_close[day])
        result["cash"][slot] = book.cash
        result["exposure"][slot] = 1 - book.cash / result["nav"][slot]
    if active:
        timing.settle_intents(book, wanted, initial, intent, counts, rows)
    contribution = flows + book.shares * np.where(
        np.isfinite(panel.adj_close[-1]), panel.adj_close[-1], 0
    )
    if not np.isclose(contribution.sum(), result["nav"][-1] - 1, atol=1e-8):
        raise ValueError("Carried account wealth does not reconcile")
    if counts["intents"] != sum(counts[k] for k in (
        "completed_intents", "expired_partial", "expired_unfilled"
    )):
        raise ValueError("Carried intent denominator does not reconcile")
    result.update(counts=counts, intent_trace=traces, stocks={
        ticker: {"net_gain_initial_nav_units": float(contribution[i]),
                 "fills": int(trades[i])} for i, ticker in enumerate(panel.tickers)
    })
    return result
