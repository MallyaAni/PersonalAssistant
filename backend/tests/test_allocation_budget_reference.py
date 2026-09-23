"""The volatility budget's explicit reference and multiplier, on real inputs.

The budget is `min(SPY, QQQ)` risk by default, which is in practice SPY's and
caps what the book can carry. `decide` now takes `budget_reference` ("min",
"spy" or "qqq") and `budget_multiplier` as explicit keyword parameters - a
parameter, never a new default - surfaced in the diagnostics, the reasons and
the version string when not the default. These tests drive the real `decide`,
`funded_execution.daily_decision` and the paper `paper.plan` with a price
matrix whose stocks are far more volatile than the benchmarks, so the budget
actually binds and the effect of the parameters is read back from the
weights the decision returned, not only from the labels.
"""

from datetime import date, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import allocation, funded_execution, paper
from backend.agents.trading.desk.allocation import (
    BINDING_NONE,
    BINDING_VOL,
    BUDGET_MIN,
    BUDGET_QQQ,
    BUDGET_SPY,
    POLICY_VOL,
    QQQ,
    SPY,
    decide,
)
from backend.agents.trading.desk.paper_allocation import AllocationContext
from backend.tests.test_funded_simulator import CONFIG, _benchmarks, _report

BASE = date(2020, 1, 1)
ROWS = 220


# Consecutive session dates for a decision horizon.
def _dates(n: int) -> np.ndarray:
    """Return `n` consecutive datetime64[D] session dates from BASE."""
    return np.array([BASE + timedelta(days=i) for i in range(n)], dtype="datetime64[D]")


# A matrix whose two stocks move together at +-3% a session while SPY moves
# +-0.4% and QQQ +-0.6%: the stock book's risk is many times either budget,
# so the volatility budget binds and every budget parameter moves the target.
def _matrix() -> tuple[np.ndarray, list[str]]:
    """Return (prices, tickers) with volatile stocks over calm benchmarks."""
    sign = np.where(np.arange(ROWS - 1) % 2 == 0, 1.0, -1.0)
    series = {
        "AAA": 0.03 * sign,
        "BBB": 0.03 * sign,
        SPY: 0.004 * sign,
        QQQ: 0.006 * sign,
    }
    tickers = list(series)
    out = np.empty((ROWS, len(tickers)))
    for col, name in enumerate(tickers):
        out[:, col] = 100.0 * np.cumprod(np.concatenate([[1.0], 1.0 + series[name]]))
    return out, tickers


# Decide the two-stock book at the last row with the given budget parameters.
def _decide(**budget):
    """Return the decision for the volatile two-stock book under `budget`."""
    prices, tickers = _matrix()
    return decide(
        _dates(ROWS),
        prices,
        tickers,
        ROWS - 1,
        desired={"AAA": 0.15, "BBB": 0.15},
        held={},
        regime_cap=1.0,
        event_cap=1.0,
        policy=POLICY_VOL,
        **budget,
    )


# The defaults reproduce today's decision exactly: the same weights, reasons,
# diagnostics and version as a call that names no budget parameter at all.
def test_defaults_reproduce_the_decision_exactly():
    plain = _decide()
    explicit = _decide(budget_reference=BUDGET_MIN, budget_multiplier=1.0)
    assert explicit == plain
    assert plain.version == "portfolio-allocation/vol/1"
    assert plain.binding == BINDING_VOL
    assert plain.reasons == ("portfolio volatility scaled down to the SPY/QQQ budget",)
    assert plain.volatility.budget_reference == BUDGET_MIN
    assert plain.volatility.budget_multiplier == 1.0
    assert plain.volatility.budget == pytest.approx(
        min(plain.volatility.spy_risk, plain.volatility.qqq_risk)
    )


# Each reference is that benchmark's own risk: QQQ's is larger here, so the
# QQQ-referenced budget lets the book carry more, in proportion.
def test_the_reference_picks_the_benchmark_risk():
    base = _decide()
    spy = _decide(budget_reference=BUDGET_SPY)
    qqq = _decide(budget_reference=BUDGET_QQQ)
    assert spy.volatility.budget == pytest.approx(base.volatility.spy_risk)
    assert qqq.volatility.budget == pytest.approx(base.volatility.qqq_risk)
    assert base.volatility.spy_risk < base.volatility.qqq_risk
    assert spy.desired_weights == pytest.approx(base.desired_weights)
    ratio = base.volatility.qqq_risk / base.volatility.spy_risk
    for name in ("AAA", "BBB"):
        assert qqq.desired_weights[name] == pytest.approx(
            base.desired_weights[name] * ratio
        )
    assert qqq.version == "portfolio-allocation/vol/1+qqq1"
    assert spy.version == "portfolio-allocation/vol/1+spy1"
    assert qqq.volatility.budget_reference == BUDGET_QQQ
    assert "volatility budget reference: QQQ" in qqq.reasons
    assert qqq.reasons[0] == "portfolio volatility scaled down to the QQQ budget"


# The multiplier scales the budget and, while it binds, the weights with it;
# it is named in the version, the reasons and the diagnostics.
def test_the_multiplier_scales_the_budget_and_the_weights():
    base = _decide()
    scaled = _decide(budget_reference=BUDGET_QQQ, budget_multiplier=1.25)
    assert scaled.version == "portfolio-allocation/vol/1+qqq1.25"
    assert scaled.volatility.budget == pytest.approx(base.volatility.qqq_risk * 1.25)
    assert scaled.volatility.budget_multiplier == 1.25
    assert scaled.binding == BINDING_VOL
    assert scaled.reasons[0] == (
        "portfolio volatility scaled down to the QQQ x1.25 budget"
    )
    assert "volatility budget reference: QQQ x1.25" in scaled.reasons
    ratio = 1.25 * base.volatility.qqq_risk / base.volatility.spy_risk
    for name in ("AAA", "BBB"):
        assert scaled.desired_weights[name] == pytest.approx(
            base.desired_weights[name] * ratio
        )
    # A multiplier alone keeps the "min" reference in the version.
    assert _decide(budget_multiplier=2.0).version == "portfolio-allocation/vol/1+min2"
    # A budget large enough to stop binding returns the unscaled composition.
    loose = _decide(budget_multiplier=100.0)
    assert loose.binding == BINDING_NONE
    assert loose.desired_weights == {"AAA": 0.15, "BBB": 0.15}
    assert loose.volatility.risk_scale == 1.0


# An unknown reference or a non-positive, non-finite or boolean multiplier
# is a caller error before any calculation.
@pytest.mark.parametrize(
    "budget",
    [
        {"budget_reference": "nasdaq"},
        {"budget_reference": "SPY"},
        {"budget_multiplier": 0.0},
        {"budget_multiplier": -1.0},
        {"budget_multiplier": float("nan")},
        {"budget_multiplier": float("inf")},
        {"budget_multiplier": True},
        {"budget_multiplier": "1.25"},
    ],
)
def test_invalid_budget_parameters_are_rejected(budget):
    with pytest.raises(ValueError, match="budget_"):
        _decide(**budget)


# Both benchmark histories stay required evidence whatever the reference: a
# missing QQQ history makes the decision unavailable under "spy" exactly as
# it does under the default, so the reference never hides missing evidence.
def test_the_reference_does_not_relax_the_benchmark_evidence():
    prices, tickers = _matrix()
    prices[ROWS - 5, tickers.index(QQQ)] = np.nan
    d = decide(
        _dates(ROWS),
        prices,
        tickers,
        ROWS - 1,
        desired={"AAA": 0.15, "BBB": 0.15},
        held={"AAA": 0.1},
        regime_cap=1.0,
        event_cap=1.0,
        policy=POLICY_VOL,
        budget_reference=BUDGET_SPY,
    )
    assert not d.available
    assert d.volatility.budget is None
    assert any(QQQ in m for m in d.missing)
    assert d.desired_weights == {"AAA": 0.1}


# The simulator's daily decision passes the parameters through unchanged and
# the decision it returns carries them.
def test_daily_decision_threads_the_budget_parameters():
    report = _report()
    price_map = {
        s: float(report.panel.adj_close[60, j])
        for j, s in enumerate(report.panel.tickers)
    }
    common = {
        "policy": "vol",
        "index_eligible": False,
        "benchmark_prices": _benchmarks(report.panel),
        "desired": {"N0": 0.15, "N3": 0.15},
        "held": {},
        "prices": price_map,
        "equity": 1.0,
        "regime_cap": 1.0,
        "event_cap": 1.0,
    }
    plain = funded_execution.daily_decision(report, report.panel, CONFIG, 60, **common)
    scaled = funded_execution.daily_decision(
        report,
        report.panel,
        CONFIG,
        60,
        budget_reference=BUDGET_QQQ,
        budget_multiplier=1.5,
        **common,
    )
    assert plain.decision.version == "portfolio-allocation/vol/1"
    assert scaled.decision.version == "portfolio-allocation/vol/1+qqq1.5"
    assert scaled.decision.volatility.budget == pytest.approx(
        plain.decision.volatility.qqq_risk * 1.5
    )
    assert funded_execution._policy_of(scaled.decision) == "vol"


# The paper context carries the parameters to the decision and persists them
# with the allocation state; with the budget relaxed the same book targets
# more stock, read back from the persisted plan payload.
def test_paper_context_threads_and_persists_the_budget_parameters():
    prices, tickers = _matrix()
    session = "2026-09-04"
    end = np.datetime64(session, "D")
    dates = (
        end - np.timedelta64(ROWS - 1, "D") + np.arange(ROWS).astype("timedelta64[D]")
    )
    marks = {s: float(prices[-1, j]) for j, s in enumerate(tickers)}

    def _plan(**budget):
        """Return (orders, state) for the volatile book under `budget`."""
        context = AllocationContext(
            policy=POLICY_VOL,
            index_eligible=False,
            dates=dates,
            prices=prices,
            tickers=tickers,
            t=ROWS - 1,
            regime_cap=1.0,
            event_cap=1.0,
            desired_stock_weights={"AAA": 0.15, "BBB": 0.15},
            **budget,
        )
        return paper.plan(
            session,
            paper.PaperState(),
            100_000.0,
            {},
            marks,
            {},
            {},
            cash=100_000.0,
            allocation_context=context,
        )

    _orders, plain, _what = _plan()
    _orders, scaled, _what = _plan(budget_reference=BUDGET_QQQ, budget_multiplier=1.25)
    assert plain.allocation_state["budget_reference"] == BUDGET_MIN
    assert plain.allocation_state["budget_multiplier"] == 1.0
    assert scaled.allocation_state["budget_reference"] == BUDGET_QQQ
    assert scaled.allocation_state["budget_multiplier"] == 1.25
    plain_stock = plain.allocation_state["plan"]["target"]["stocks"]
    scaled_stock = scaled.allocation_state["plan"]["target"]["stocks"]
    assert 0.0 < plain_stock < scaled_stock <= 0.3
    assert scaled.allocation_state["plan"]["reason"] == (
        "portfolio volatility scaled down to the QQQ x1.25 budget"
    )
    # A mapping context is coerced the same way.
    _orders, mapped, _what = paper.plan(
        session,
        paper.PaperState(),
        100_000.0,
        {},
        marks,
        {},
        {},
        cash=100_000.0,
        allocation_context={
            "policy": POLICY_VOL,
            "dates": dates,
            "prices": prices,
            "tickers": tickers,
            "t": ROWS - 1,
            "regime_cap": 1.0,
            "event_cap": 1.0,
            "desired_stock_weights": {"AAA": 0.15, "BBB": 0.15},
            "budget_reference": BUDGET_QQQ,
            "budget_multiplier": 1.25,
        },
    )
    assert (
        mapped.allocation_state["plan"]["target"]
        == (scaled.allocation_state["plan"]["target"])
    )
    assert allocation.BUDGET_REFERENCES == ("min", "spy", "qqq")
