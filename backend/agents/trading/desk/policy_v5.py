"""`graded-equal-weight/5`: `/4` with the operator's hold limit raised to 25%.

On 2026-09-29 the operator raised the per-name hold limit from a fifth of
the account to a quarter, with `docs/research/cap-sweep-2026-09-27.md` as
the price list: the same rule (every A/A+ member of the point-in-time book
at equal weight, spare cash in cash) scored at eight caps on the
point-in-time book, 20 offsets, both costs. From 20% to 25% the rule earns
about 1.2 CAGR points a year more on 2016-2023 (28.7% against 27.5% at
25 bp) and 2.3 more on 2024-2026 (48.5% against 46.2%). What it pays for
that is a larger single name. The two caps give different books only on a
session with fewer than five A/A+ names: at five or more, 1/count is at
most 20% and neither cap binds; at one to four, `/4` holds each name at
20% and leaves the rest in cash, where this policy holds each at 25%. The
worst single-name day (the weight set at the previous close times that
name's simple return into the next close, the corrected metric of the
sweep's 2026-09-28 erratum) is 3.3% of the book against 2.7% on 2016-2023,
and the same 4.7% on 2024-2026, whose worst name-day came at a weight the
20% cap already allowed.

Nothing else differs from `/4`: the same grade floor ("every A/A+ name"),
the same gross (fully invested when the count allows), the same `targets`
arithmetic in the same order and the same `allocator(mask)`. So this module
reproduces `point_in_time.graded_equal_weight_allocator(mask, min_grade=A,
cap=0.25, gross=1.0)` - the arm the sweep scored as
`market_pit_scorecard.graded_arm(0.25)` - return for return, and equals
`policy_v4.targets` exactly whenever five or more names qualify;
`test_policy_v5.py` asserts both. `policy_v4.py` is not edited and stays
frozen: the `/4` shadow ledger's identity hash is over its bytes, the
dashboard's candidate line is the measured `/4` arm (`ew_graded_20`), and
the research studies replay it by name.

The constants are frozen, as `/4`'s are. A change to any number here is a
new policy with a new version string, never an edit to this one.
"""

from __future__ import annotations

import numpy as np

from backend.agents.trading.desk import grading

POLICY_VERSION = "graded-equal-weight/5"
# The operator's hold limit: no name above a quarter of equity (2026-09-29,
# raised from a fifth after the cap sweep priced the difference).
HOLD_CAP = 0.25
# "Every A/A+ name": the grade floor, unchanged from `/4`.
MIN_GRADE = grading.ORDINAL[grading.A]
# Fully invested when the count allows; the cap leaves the rest in cash.
GROSS = 1.0


# The policy's target weights for one session, from that session alone:
# every eligible name graded A or better with a finite price gets
# min(GROSS / count, HOLD_CAP); the benchmark and everything else get 0.
# The arithmetic is the registered arm's and `/4`'s, kept in the same order
# so the three agree to the last bit.
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

    # One session's targets under the policy, from row `t` alone.
    def allocate(report, panel, config, t: int) -> np.ndarray:
        return targets(
            report.graded.grades[t],
            panel.adj_close[t],
            mask[t],
            panel.index(panel.benchmark),
        )

    return allocate
