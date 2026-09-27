"""`graded-equal-weight/4` reproduces the measured `ew_graded_20` arm exactly.

A synthetic desk report over about 300 sessions holds eight names and SPY,
with grades that move between A+, A, B and C from session to session and
a membership mask that admits and removes names, so selection, the cap and
the cash remainder all get exercised. The acceptance criterion is byte
identity: `simulate.run` with the policy's allocator returns the same
daily series as with `point_in_time.graded_equal_weight_allocator(mask,
min_grade=A, cap=0.20, gross=1.0)`, the arm registered as `ew_graded_20`,
at several reset offsets and both costs.
"""

from datetime import date, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import (
    grading,
    paper,
    point_in_time,
    policy_v4,
    regime,
    simulate,
)
from backend.agents.trading.desk.desk import DeskReport
from backend.agents.trading.desk.opinions import Opinion
from backend.cli import market_pit_scorecard as sc
from backend.market.panel import Panel
from backend.market.universe import AI_COMPUTE

NAMES = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH")
T = 300


# A report whose grades churn and whose prices have gaps, so the policy has
# to select, cap, hold cash and skip an unpriced name.
def _report(seed: int = 0) -> DeskReport:
    rng = np.random.default_rng(seed)
    n = len(NAMES)
    days = []
    d = date(2022, 1, 3)
    while len(days) < T:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    dates = np.array(days, dtype="datetime64[D]")
    log = rng.normal(0.0004, 0.02, size=(T, n + 1)).cumsum(axis=0)
    close = 100.0 * np.exp(log)
    # One name is unpriced for its first thirty sessions (before any reset
    # could have bought it), so "finite price" matters to the selection.
    close[:30, 2] = np.nan
    panel = Panel(
        dates=dates,
        tickers=NAMES + ("SPY",),
        open=close * (1 + rng.normal(0, 0.002, size=close.shape)),
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={t: (AI_COMPUTE,) for t in NAMES},
        benchmark="SPY",
    )
    grades = rng.choice(
        [grading.ORDINAL[g] for g in ("A+", "A", "B", "C")],
        size=(T, n + 1),
        p=[0.3, 0.3, 0.2, 0.2],
    )
    grades[:, n] = 0
    conviction = rng.normal(size=(T, n + 1))
    conviction[:, n] = np.nan
    graded = grading.Graded(grades, conviction.copy(), {}, conviction)
    state = regime.RegimeState(
        0.0, 0.0, 0.5, 0.0, 0.0, 0.0, "ai", 0.1, 0.0, 1.0, 1.0, (), 0.0, False
    )
    view = regime.RegimeView(
        [state] * T, Opinion("rotation", np.full((T, n + 1), np.nan))
    )
    return DeskReport(
        panel, {t: "ai" for t in NAMES}, {}, view, graded, graded.as_scores(), []
    )


# A membership mask that admits two names late and removes one early.
def _mask() -> np.ndarray:
    mask = np.ones((T, len(NAMES) + 1), dtype=bool)
    mask[:, -1] = False
    mask[:120, 6] = False
    mask[:200, 7] = False
    mask[180:, 5] = False
    return mask


# The constants are the registered arm's and the operator's, frozen.
def test_the_policy_is_named_and_frozen():
    assert policy_v4.POLICY_VERSION == "graded-equal-weight/4"
    assert policy_v4.HOLD_CAP == 0.20
    assert grading.ORDINAL[grading.A] == policy_v4.MIN_GRADE
    assert policy_v4.GROSS == 1.0
    assert policy_v4.POLICY_VERSION != paper.POLICY_VERSION


# One session: every eligible A-or-better name with a finite price gets
# min(1/count, cap), the benchmark and everything else nothing.
def test_targets_for_one_session():
    grades = np.array([3, 2, 1, 0, 3, 2, 3, 0])
    prices = np.array([1.0, 1.0, 1.0, 1.0, np.nan, 1.0, 1.0, 1.0])
    eligible = np.array([True, True, True, True, True, False, True, True])
    out = policy_v4.targets(grades, prices, eligible, 7)
    # AAA, BBB, GGG qualify (EEE unpriced, FFF ineligible, CCC B, DDD C).
    assert out[0] == out[1] == out[6] == pytest.approx(0.20)
    assert out[[2, 3, 4, 5, 7]].sum() == 0
    many = policy_v4.targets(np.full(8, 3), np.ones(8), np.ones(8, dtype=bool), 7)
    assert many[:7].sum() == pytest.approx(1.0)
    assert many[7] == 0
    assert many[0] == pytest.approx(1 / 7)
    # An A+ name graded on the benchmark column stays at zero.
    assert (
        policy_v4.targets(np.full(8, 3), np.ones(8), np.ones(8, dtype=bool), 0)[0] == 0
    )


# The allocator reads only row t of the mask, grades and prices.
def test_allocator_reads_only_the_decision_row():
    report = _report()
    mask = _mask()
    allocate = policy_v4.allocator(mask)
    t = 50
    expected = policy_v4.targets(
        report.graded.grades[t], report.panel.adj_close[t], mask[t], 8
    )
    assert np.array_equal(allocate(report, report.panel, None, t), expected)
    # Nothing on row t is held on a name ineligible on row t.
    assert allocate(report, report.panel, None, 100)[7] == 0


# The acceptance criterion: the simulator's daily returns under the policy
# are identical, element for element, to the registered ew_graded_20 arm at
# several offsets and both costs.
@pytest.mark.parametrize("offset", [0, 7, 13, 19])
@pytest.mark.parametrize("cost_bps", [10.0, 25.0])
def test_policy_reproduces_the_measured_arm_exactly(offset, cost_bps):
    report = _report()
    mask = _mask()
    restricted = point_in_time.restrict(report, mask)
    since = date.fromisoformat(str(report.panel.dates[offset]))
    plain = dict(
        since=since, use_exits=False, rebalance=paper.REBALANCE_EVERY, cost_bps=cost_bps
    )
    ours = simulate.run(restricted, allocator=policy_v4.allocator(mask), **plain)
    arm = simulate.run(
        restricted,
        allocator=point_in_time.graded_equal_weight_allocator(
            mask, min_grade=grading.ORDINAL[grading.A], cap=0.20, gross=1.0
        ),
        **plain,
    )
    registered = simulate.run(
        restricted, allocator=sc.ARMS["ew_graded_20"](restricted, mask), **plain
    )
    assert np.array_equal(ours.returns, arm.returns, equal_nan=True)
    assert np.array_equal(ours.returns, registered.returns, equal_nan=True)
    assert np.array_equal(ours.equity, arm.equity, equal_nan=True)
    assert np.array_equal(ours.invested, arm.invested, equal_nan=True)
    assert ours.rebalances == arm.rebalances
    assert ours.traded == arm.traded
    # The run actually traded and held something: not a vacuous match.
    finite = ours.returns[np.isfinite(ours.returns)]
    assert len(finite) > 200
    assert np.abs(finite).max() > 0
    assert np.nanmax(ours.top_weight) <= 0.20 + 0.10  # drift between resets only
