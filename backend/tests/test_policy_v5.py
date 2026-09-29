"""`graded-equal-weight/5` is `/4` with a 25% cap, and the arm the cap sweep scored.

The report is `test_policy_v4`'s: about 300 sessions, eight names and SPY,
grades churning between A+, A, B and C (about five of eight qualify on an
ordinary session, so the cap binds on many and not on others), a name
unpriced for its first thirty sessions and a membership mask that admits
and removes names. The acceptance criteria are byte identity with the
point-in-time allocator at `cap=0.25` (the arm the sweep registered as
`market_pit_scorecard.graded_arm(0.25)`) in `simulate.run`, byte identity
with `policy_v4.targets` whenever five or more names qualify, a quarter of
the book each when four do, and 1/count when the cap does not bind.
"""

import ast
import inspect
import textwrap
from datetime import date

import numpy as np
import pytest

from backend.agents.trading.desk import (
    grading,
    paper,
    point_in_time,
    policy_v4,
    policy_v5,
    simulate,
)
from backend.cli import market_pit_scorecard as sc
from backend.tests.test_policy_v4 import NAMES, _mask, _report

A = grading.ORDINAL[grading.A]


# The constants: the operator's new cap and a new version; everything else
# is `/4`'s.
def test_the_policy_is_named_and_frozen():
    assert policy_v5.POLICY_VERSION == "graded-equal-weight/5"
    assert policy_v5.HOLD_CAP == 0.25
    assert policy_v5.MIN_GRADE == A == policy_v4.MIN_GRADE
    assert policy_v5.GROSS == policy_v4.GROSS == 1.0
    assert policy_v5.POLICY_VERSION != policy_v4.POLICY_VERSION
    assert policy_v5.POLICY_VERSION != paper.POLICY_VERSION
    # `/4` itself is untouched by the release.
    assert policy_v4.POLICY_VERSION == "graded-equal-weight/4"
    assert policy_v4.HOLD_CAP == 0.20


# "Nothing else differs from /4" is checked, not said: the `targets` and
# `allocator` definitions parse to the same syntax tree as `/4`'s (comments
# aside), so the arithmetic is the same code in the same order.
def test_the_code_is_v4s_but_for_the_cap():
    for name in ("targets", "allocator"):
        ours = inspect.getsource(getattr(policy_v5, name))
        theirs = inspect.getsource(getattr(policy_v4, name))
        assert ast.dump(ast.parse(textwrap.dedent(ours))) == ast.dump(
            ast.parse(textwrap.dedent(theirs))
        ), name


# One session: every eligible A-or-better name with a finite price gets
# min(1/count, 0.25), the benchmark and everything else nothing.
def test_targets_for_one_session():
    grades = np.array([3, 2, 1, 0, 3, 2, 3, 0])
    prices = np.array([1.0, 1.0, 1.0, 1.0, np.nan, 1.0, 1.0, 1.0])
    eligible = np.array([True, True, True, True, True, False, True, True])
    out = policy_v5.targets(grades, prices, eligible, 7)
    # AAA, BBB, GGG qualify (EEE unpriced, FFF ineligible, CCC B, DDD C):
    # three names under a quarter each, where `/4` holds a fifth each.
    assert out[0] == out[1] == out[6] == 0.25
    assert out[[2, 3, 4, 5, 7]].sum() == 0
    assert policy_v4.targets(grades, prices, eligible, 7)[0] == 0.20
    # An A+ name graded on the benchmark column stays at zero.
    assert (
        policy_v5.targets(np.full(8, 3), np.ones(8), np.ones(8, dtype=bool), 0)[0] == 0
    )


# Four qualifying names: a quarter each, the book fully invested - the one
# count at which the new cap and 1/count coincide. `/4` holds 80% there.
def test_four_names_hold_a_quarter_each():
    grades = np.array([3, 3, 2, 2, 1, 0, 0, 0, 3])
    everyone = np.ones(9, dtype=bool)
    out = policy_v5.targets(grades, np.ones(9), everyone, 8)
    assert list(out[:4]) == [0.25] * 4
    assert out[4:].sum() == 0
    assert out.sum() == 1.0
    fifth = policy_v4.targets(grades, np.ones(9), everyone, 8)
    assert list(fifth[:4]) == [0.20] * 4
    assert fifth.sum() == pytest.approx(0.80)


# Below the cap the weight is 1/count exactly, the same float `/4` gives.
@pytest.mark.parametrize("count", [5, 6, 7, 9, 10, 13])
def test_below_the_cap_each_name_is_one_over_the_count(count):
    n = 14
    grades = np.zeros(n + 1, dtype=int)
    grades[:count] = 3
    out = policy_v5.targets(grades, np.ones(n + 1), np.ones(n + 1, dtype=bool), n)
    assert (out[:count] == policy_v5.GROSS / count).all()
    assert (out[count:] == 0).all()
    assert out.sum() == pytest.approx(1.0)
    assert np.array_equal(
        out, policy_v4.targets(grades, np.ones(n + 1), np.ones(n + 1, dtype=bool), n)
    )


# Session by session on the churning report, with a random membership row
# and a few unpriced names: bit-identical to `/4` whenever five or more
# names qualify; a quarter against a fifth on every qualifying name when
# one to four do; nothing either way when none do. Both main cases occur
# many times; the empty session is rare here, so it is also built by hand.
def test_equal_to_v4_whenever_five_or_more_qualify():
    report = _report()
    rng = np.random.default_rng(5)
    grades = report.graded.grades
    prices = report.panel.adj_close.copy()
    prices[rng.random(prices.shape) < 0.05] = np.nan
    bench = report.panel.index(report.panel.benchmark)
    seen = {"same": 0, "capped": 0, "empty": 0}
    for t in range(len(report.panel.dates)):
        eligible = rng.random(len(NAMES) + 1) < 0.85
        ours = policy_v5.targets(grades[t], prices[t], eligible, bench)
        theirs = policy_v4.targets(grades[t], prices[t], eligible, bench)
        qualifies = ours > 0
        count = int(qualifies.sum())
        if count >= 5:
            assert np.array_equal(ours, theirs), t
            seen["same"] += 1
        elif count:
            assert (ours[qualifies] == 0.25).all(), t
            assert (theirs[qualifies] == 0.20).all(), t
            assert np.array_equal(theirs > 0, qualifies), t
            seen["capped"] += 1
        else:
            assert not theirs.any(), t
            seen["empty"] += 1
    assert seen["same"] > 20, seen
    assert seen["capped"] > 20, seen
    nobody = np.zeros(len(NAMES) + 1, dtype=bool)
    assert not policy_v5.targets(grades[0], prices[0], nobody, bench).any()
    assert not policy_v4.targets(grades[0], prices[0], nobody, bench).any()


# The allocator reads only row t of the mask, grades and prices.
def test_allocator_reads_only_the_decision_row():
    report = _report()
    mask = _mask()
    allocate = policy_v5.allocator(mask)
    t = 50
    expected = policy_v5.targets(
        report.graded.grades[t], report.panel.adj_close[t], mask[t], 8
    )
    assert np.array_equal(allocate(report, report.panel, None, t), expected)
    # Nothing on row t is held on a name ineligible on row t.
    assert allocate(report, report.panel, None, 100)[7] == 0


# The acceptance criterion: the simulator's daily returns under the policy
# are identical, element for element, to the point-in-time allocator at a
# 25% cap and to the sweep's registered `graded_arm(0.25)`, at several
# offsets and both costs - and not to `/4`'s, so the cap really binds here.
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
    ours = simulate.run(restricted, allocator=policy_v5.allocator(mask), **plain)
    arm = simulate.run(
        restricted,
        allocator=point_in_time.graded_equal_weight_allocator(
            mask, min_grade=A, cap=0.25, gross=1.0
        ),
        **plain,
    )
    registered = simulate.run(
        restricted, allocator=sc.graded_arm(0.25)(restricted, mask), **plain
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
    assert np.nanmax(ours.top_weight) <= 0.25 + 0.10  # drift between resets only
    # And it is a different book from `/4`'s on the same report.
    v4 = simulate.run(restricted, allocator=policy_v4.allocator(mask), **plain)
    assert not np.array_equal(ours.equity, v4.equity, equal_nan=True)
