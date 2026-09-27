"""`graded-equal-weight/4`: the release-train candidate, as one named policy.

The 2026-09-26 point-in-time arms (`docs/research/pit-arms-2026-09-26.md`)
found that the desk's grade selects a little and that everything the
frozen rule `/3` builds on top of it - inverse-volatility weights, the
0.30 volatility target, the regime multipliers, top-decile concentration,
the band entries - is what loses about fifteen CAGR points a year on the
choosing window. The arm that passed gate H against the incumbent is
`ew_graded_20` in `market_pit_scorecard.ARMS`: every member the desk grades
A or better, equal weight, capped at the operator's 20% hold limit, spare
cash in cash. This module is that arm under its policy name, so the
simulator can run it and the nightly can shadow it, and it must reproduce
`point_in_time.graded_equal_weight_allocator(mask, min_grade=A, cap=0.20,
gross=1.0)` return for return - `test_policy_v4.py` asserts exactly that.

The constants are frozen. They are not tuned values: the hold limit is the
operator's decision of 2026-09-25 (a name is never more than a fifth of
the account, after DELL reached 31.6% under the green-day skip), the grade
floor is "every A/A+ name" as the arm was registered, and gross is fully
invested when ten or more names qualify. There is no volatility target, no
regime multiplier, no inverse-vol tilt and no grade ladder here, on
purpose: each of those is what `risk.desk_targets` does for `/3`, and each
was measured to cost return. A change to any number here is a new policy
with a new version string, never an edit to this one.
"""

from __future__ import annotations

import numpy as np

from backend.agents.trading.desk import grading

POLICY_VERSION = "graded-equal-weight/4"
# The operator's hold limit: no name above a fifth of equity (2026-09-25).
HOLD_CAP = 0.20
# "Every A/A+ name": the grade floor the arm was registered with.
MIN_GRADE = grading.ORDINAL[grading.A]
# Fully invested when the count allows; the cap leaves the rest in cash.
GROSS = 1.0


# The policy's target weights for one session, from that session alone:
# every eligible name graded A or better with a finite price gets
# min(GROSS / count, HOLD_CAP); the benchmark and everything else get 0.
# The arithmetic is the registered arm's, kept in the same order so the two
# agree to the last bit.
def targets(
    grades_today: np.ndarray,
    prices_today: np.ndarray,
    eligible_today: np.ndarray,
    benchmark_index: int,
) -> np.ndarray:
    """Return the (N,) weight vector for one session."""
    grades_today = np.asarray(grades_today)
    prices_today = np.asarray(prices_today, dtype=float)
    eligible = np.asarray(eligible_today, dtype=bool) & (grades_today >= MIN_GRADE)
    eligible[benchmark_index] = False
    eligible &= np.isfinite(prices_today)
    out = np.zeros(len(grades_today))
    count = int(eligible.sum())
    if count:
        out[eligible] = min(GROSS / count, HOLD_CAP)
    return out


# A `simulate.run(allocator=...)` callable for the policy on a membership
# mask. It reads only row `t` of the mask, the grades and the prices, so it
# cannot see the future through the unsliced panel the hook receives.
def allocator(mask: np.ndarray):
    """Return a callable (report, panel, config, t) -> target weights."""
    mask = np.asarray(mask, dtype=bool)

    def allocate(report, panel, config, t: int) -> np.ndarray:
        return targets(
            report.graded.grades[t],
            panel.adj_close[t],
            mask[t],
            panel.index(panel.benchmark),
        )

    return allocate
