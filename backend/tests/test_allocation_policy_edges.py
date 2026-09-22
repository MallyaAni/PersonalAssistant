"""Policy-edge behavioural tests for the shared allocation decision.

This module is the review-owned boundary for the pure decision
(`desk.allocation.decide`) and the funded sizing call chain that consumes it
(`funded_execution.plan_funded` and the paper `paper.plan` with an
`allocation_context`). Every input here is a real price matrix and real
weights; nothing is mocked. The cases deliberately sit beside - never inside -
the cases `test_portfolio_allocation`, `test_allocation_acceptance` and
`test_paper_funded_allocation` already pin, so a fixed contract property is
asserted once in the repository.

Scope of what is pinned here, and why it is not covered elsewhere:

* The company cap, the regime cap and the index residual are applied in one
  composition step even when the raw desired weights exceed the cap: the
  residual fills only the post-cap gap, so a single-stock book can never carry
  more than `ENTRY_NAME_CAP` of stock plus the index.
* A volatility cut scales the capped stocks and the residual SPY by the same
  scalar, so a risk cut never leaves the index sleeve unscaled while the stock
  book carries the whole reduction (the "simultaneous market/stock risk" the
  milestone contract names).
* Missing QQQ history alone makes the decision unavailable and retains the
  actual holdings, even when SPY's own history is complete - the budget is the
  minimum of the two benchmarks, so partial benchmark evidence is not enough
  to run.
* A complete bearish trend (both SPY and QQQ below their 200-session means)
  with full volatility evidence targets all cash and names the trend as the
  binding ceiling - the price-level trend is a real ceiling, not only a
  missing-evidence fallback.
* The missing-evidence fallback cuts a held SPY position proportionally with
  held stocks to a known absolute ceiling; SPY is not treated as a protected
  sleeve once it is an actual holding.

The review reproduced an all-cash defect at two boundaries; the root integration
now fixes it and these are ordinary regression tests:

* A deliberate all-cash composition (`desired={}`) with explicit index
  eligibility is filled with the full SPY residual instead of staying all
  cash. `decide(..., desired={}, index_eligible=True, regime_cap=1.0)`
  returns `{SPY: 1.0}` with `cash == 0.0`; the paper path then issues a
  999-share SPY buy on a `desired_stock_weights={}` context. This contradicts
  the module's own stated contract - "an empty candidate targets all cash (a
  requested exit is never blocked by missing evidence)" - and the paper
  boundary's documented preservation of an intentionally empty (all-cash)
  composition. The existing `test_explicit_empty_selection_is_preserved_...`
  misses it because it asserts on `stable_desired` and on stock buys, never on
  SPY orders or the target index/cash buckets.
"""

from datetime import date, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import allocation, paper
from backend.agents.trading.desk.allocation import (
    ENTRY_NAME_CAP,
    POLICY_VOL,
    POLICY_VOL_TREND,
    QQQ,
    SPY,
    decide,
)
from backend.agents.trading.desk.paper_allocation import AllocationContext

BASE = date(2020, 1, 1)
ROWS = 220


# Consecutive session dates for a decision horizon.
def _dates(n: int) -> np.ndarray:
    """Return `n` consecutive datetime64[D] session dates from BASE."""
    return np.array([BASE + timedelta(days=i) for i in range(n)], dtype="datetime64[D]")


# Turn per-ticker simple-return series into a positive adjusted-close matrix.
def _prices(returns: dict[str, np.ndarray]) -> tuple[np.ndarray, list[str]]:
    """Return (T, N) positive prices and ticker order from return series."""
    tickers = list(returns)
    steps = len(next(iter(returns.values())))
    out = np.empty((steps + 1, len(tickers)))
    for col, name in enumerate(tickers):
        prices = np.empty(steps + 1)
        prices[0] = 100.0
        for row in range(steps):
            prices[row + 1] = prices[row] * (1.0 + returns[name][row])
        out[:, col] = prices
    return out, tickers


# Two stocks in exact opposition on top of SPY/QQQ at a fixed volatility.
def _hedge_matrix(n: int = 120) -> tuple[np.ndarray, list[str]]:
    """Return a matrix whose weighted joint return is identically zero."""
    pattern = np.where(np.arange(n - 1) % 2 == 0, 0.01, -0.01)
    return _prices({"AAA": pattern, "BBB": -pattern, SPY: pattern, QQQ: pattern})


# ---------------------------------------------------------------------------
# Resolved all-cash regressions, reproduced before the root integration fix.
# ---------------------------------------------------------------------------


# A deliberate all-cash target must stay all cash even when SPY is index
# eligible: the residual fills the gap between the caller's chosen stocks and
# the regime cap, not the gap left by choosing no stocks at all. The module's
# own contract says "an empty candidate targets all cash".
def test_deliberate_all_cash_stays_all_cash_with_index_eligibility():
    prices, tickers = _hedge_matrix()
    t = len(prices) - 1
    d = decide(
        _dates(len(prices)),
        prices,
        tickers,
        t,
        desired={},
        held={},
        regime_cap=1.0,
        event_cap=1.0,
        policy=POLICY_VOL,
        index_eligible=True,
    )
    assert d.desired_weights == {}
    assert d.cash == 1.0


# The same all-cash intent through the paper boundary must not become a full
# index buy: with `desired_stock_weights={}` and index eligibility, `paper.plan`
# currently issues a 999-share SPY buy and reports a target of `indexes: 1.0,
# cash: 0.0`, converting a deliberate exit into full market exposure.
def test_deliberate_all_cash_paper_plan_does_not_buy_spy():
    end = np.datetime64("2026-09-04", "D")
    start = end - np.timedelta64(ROWS - 1, "D")
    dates = start + np.arange(ROWS).astype("timedelta64[D]")
    context = AllocationContext(
        policy="vol",
        index_eligible=True,
        dates=dates,
        prices=np.full((ROWS, 5), 100.0),
        tickers=["AAA", "BBB", "CCC", SPY, "QQQ"],
        t=ROWS - 1,
        regime_cap=1.0,
        event_cap=1.0,
        desired_stock_weights={},
        cost_bps=10.0,
    )
    orders, _state, what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0, SPY: 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=context,
    )
    assert what == "allocation-rebalance"
    assert not any(o.side == "buy" for o in orders)
    assert _state.allocation_state["plan"]["target"]["cash"] == 1.0


# ---------------------------------------------------------------------------
# Contract properties that pass on the current code, pinned against regression.
# ---------------------------------------------------------------------------


# The company cap, the regime cap and the index residual are one composition
# step even when the raw desired weights exceed the cap: each stock is trimmed
# to `ENTRY_NAME_CAP`, and SPY fills only the post-cap gap to the regime cap,
# never a share of the excess that was capped away.
def test_company_cap_then_regime_then_residual_fills_only_the_gap():
    prices, tickers = _hedge_matrix()
    t = len(prices) - 1
    d = decide(
        _dates(len(prices)),
        prices,
        tickers,
        t,
        desired={"AAA": 0.5, "BBB": 0.5},
        held={},
        regime_cap=0.6,
        event_cap=1.0,
        policy=POLICY_VOL,
        index_eligible=True,
    )
    # Both names trim to the cap first, so the residual is regime - 2*cap.
    assert d.desired_weights == {
        "AAA": ENTRY_NAME_CAP,
        "BBB": ENTRY_NAME_CAP,
        SPY: 0.6 - 2 * ENTRY_NAME_CAP,
    }
    assert abs(sum(d.desired_weights.values()) - 0.6) < 1e-9
    assert d.cash == pytest.approx(0.4)


# A volatility cut must scale the capped stocks and the residual SPY by the
# same scalar: with both in the candidate, a risk reduction is carried by the
# whole book, never left to the stock sleeve alone while the index stays full.
def test_a_volatility_cut_scales_stocks_and_residual_index_together():
    n = 120
    pattern = np.where(np.arange(n - 1) % 2 == 0, 0.01, -0.01)
    # Stocks twice as volatile as the benchmarks, so the joint book exceeds the
    # SPY/QQQ budget and a real risk cut fires.
    prices, tickers = _prices(
        {"AAA": 2 * pattern, "BBB": 2 * pattern, SPY: pattern, QQQ: pattern}
    )
    t = len(prices) - 1
    d = decide(
        _dates(len(prices)),
        prices,
        tickers,
        t,
        desired={"AAA": 0.3, "BBB": 0.3},
        held={},
        regime_cap=1.0,
        event_cap=1.0,
        policy=POLICY_VOL,
        index_eligible=True,
    )
    assert d.available
    assert d.volatility is not None
    assert d.volatility.risk_scale < 1.0
    # The capped candidate carries AAA/BBB at the cap and SPY at the residual;
    # the final scalar must be applied to every one of them alike.
    candidate = {"AAA": ENTRY_NAME_CAP, "BBB": ENTRY_NAME_CAP, SPY: 0.7}
    scalar = d.volatility.risk_scale
    for name, weight in candidate.items():
        assert d.desired_weights[name] == pytest.approx(weight * scalar, rel=1e-9)
    assert d.desired_weights[SPY] / d.desired_weights["AAA"] == pytest.approx(
        0.7 / ENTRY_NAME_CAP, rel=1e-9
    )


# The budget is the minimum of the two benchmark risks, so missing QQQ history
# alone - with SPY's history complete - leaves the volatility evidence
# incomplete and the decision unavailable; the actual holdings are retained,
# never increased or fabricated from the surviving benchmark.
def test_missing_qqq_history_alone_makes_the_decision_unavailable():
    n = 120
    pattern = np.where(np.arange(n - 1) % 2 == 0, 0.01, -0.01)
    prices, tickers = _prices(
        {"AAA": pattern, "BBB": -pattern, SPY: pattern, QQQ: pattern}
    )
    prices[:61, tickers.index(QQQ)] = np.nan
    t = len(prices) - 1
    d = decide(
        _dates(len(prices)),
        prices,
        tickers,
        t,
        desired={"AAA": 0.3, "BBB": 0.3},
        held={"AAA": 0.1, "BBB": 0.1},
        regime_cap=1.0,
        event_cap=1.0,
        policy=POLICY_VOL,
    )
    assert not d.available
    assert d.desired_weights == {"AAA": 0.1, "BBB": 0.1}
    assert any("QQQ risk" in m for m in d.missing)
    assert not any("SPY risk" in m for m in d.missing)


# A complete bearish trend with full volatility evidence is a real ceiling,
# not only a missing-evidence fallback: when both SPY and QQQ close below their
# 200-session price means, the trend ceiling is 0 and the decision targets all
# cash, naming the trend as the binding constraint.
def test_complete_bearish_trend_targets_all_cash():
    n = 230
    pattern = np.where(np.arange(n - 1) % 2 == 0, 0.01, -0.01)
    tickers = ["AAA", "BBB", SPY, QQQ]
    prices = np.empty((n, 4))
    bench = 200.0 * (0.99 ** np.arange(n))
    prices[:, tickers.index(SPY)] = bench
    prices[:, tickers.index(QQQ)] = bench * 0.95
    prices[0, 0] = prices[0, 1] = 100.0
    for row in range(n - 1):
        prices[row + 1, 0] = prices[row, 0] * (1.0 + pattern[row])
        prices[row + 1, 1] = prices[row, 1] * (1.0 - pattern[row])
    assert prices[n - 1, tickers.index(SPY)] < float(
        np.mean(prices[60:, tickers.index(SPY)])
    )
    t = n - 1
    d = decide(
        _dates(n),
        prices,
        tickers,
        t,
        desired={"AAA": 0.3, "BBB": 0.3},
        held={},
        regime_cap=1.0,
        event_cap=1.0,
        policy=POLICY_VOL_TREND,
    )
    assert d.available
    assert d.volatility is not None
    assert d.volatility.trend_ceiling == 0.0
    assert all(weight == 0.0 for weight in d.desired_weights.values())
    assert d.cash == 1.0
    assert d.binding == allocation.BINDING_TREND


# In the missing-evidence fallback a held SPY position is cut proportionally
# with held stocks to a known absolute ceiling, exactly like any other name:
# the index is not a protected sleeve once it is an actual holding.
def test_fallback_cuts_held_spy_proportionally_with_stocks():
    n = 120
    prices = np.full((n, 4), np.nan)
    tickers = ["AAA", "BBB", SPY, QQQ]
    t = n - 1
    d = decide(
        _dates(n),
        prices,
        tickers,
        t,
        desired={"AAA": 0.3},
        held={"AAA": 0.3, SPY: 0.4},
        regime_cap=1.0,
        event_cap=0.5,
        policy=POLICY_VOL,
    )
    assert not d.available
    # Both held names cut by the same factor to the 0.5 event ceiling.
    assert d.desired_weights["AAA"] == pytest.approx(0.3 * 0.5 / 0.7, rel=1e-9)
    assert d.desired_weights[SPY] == pytest.approx(0.4 * 0.5 / 0.7, rel=1e-9)
    assert abs(sum(d.desired_weights.values()) - 0.5) < 1e-9
    assert d.binding == allocation.BINDING_EVENT
