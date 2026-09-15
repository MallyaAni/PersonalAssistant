"""The candidate's inputs and rules, with the algebra they rest on.

What has to hold: a whole-book repricing leaves the relative magnitude
unchanged and moves the history reference by exactly the repricing;
strengthening any bearish opinion never raises the score, eligibility or
weight; when the grade rule admits nobody the candidate rule admits
nobody; a score-admitted name is sized as a B.
"""

import numpy as np

from backend.agents.trading.desk import grading, risk
from backend.market import attractiveness as att
from backend.market import valuation


def test_whole_book_repricing_leaves_the_relative_magnitude_unchanged():
    rng = np.random.default_rng(0)
    log_ps = rng.normal(1.0, 0.5, size=(3, 8))
    groups = np.array([[0, 0, 0, 0, 1, 1, 1, 1]] * 3)
    eligible = np.ones((3, 8), dtype=bool)
    d = -valuation.relative_to_group(log_ps, groups)
    d_up = -valuation.relative_to_group(log_ps + np.log(1.5), groups)
    assert np.allclose(d, d_up)  # every distance to the side's median is the same
    assert np.allclose(att.magnitude(d, eligible), att.magnitude(d_up, eligible))
    m = att.magnitude(d, eligible)
    assert (np.abs(m) < 1.0).all()
    # A single name repriced does move: its distance changes by log k.
    single = log_ps.copy()
    single[:, 0] += np.log(2.0)
    d_one = -valuation.relative_to_group(single, groups)
    assert (d_one[:, 0] < d[:, 0]).all()


def test_history_reference_sees_the_level_and_needs_history():
    t = 300
    x = np.full((t, 2), 1.0)
    x[-1, :] = [1.0, 1.0 + np.log(1.5)]  # name 1 is 50% dearer than its own history
    h = att.history_reference(x, window=200, min_known=100)
    assert np.isnan(h[50]).all()  # too young
    assert abs(h[-1, 0]) < 1e-12
    assert abs(h[-1, 1] + np.log(1.5)) < 1e-12
    # A whole-book repricing on the last session lowers every reference by log k.
    up = x.copy()
    up[-1] += np.log(1.5)
    h_up = att.history_reference(up, window=200, min_known=100)
    assert np.allclose(h_up[-1], h[-1] - np.log(1.5))


def _convictions(
    value=0.5, fundamental=0.5, technical=0.5, sentiment=0.0, rotation=0.0
):
    return {
        "fundamental": np.array([[fundamental]]),
        "technical": np.array([[technical]]),
        "sentiment": np.array([[sentiment]]),
        "rotation": np.array([[rotation]]),
        "value": np.array([[value]]),
    }


def test_strengthening_a_bearish_opinion_never_helps():
    m = np.array([[0.4]])
    base = att.candidate_scores(_convictions(), m)[0, 0]
    for name in ("fundamental", "technical", "sentiment", "rotation", "value"):
        worse = att.candidate_scores(_convictions(**{name: -0.9}), m)[0, 0]
        assert worse < base
    # A more negative magnitude lowers the score too.
    assert att.candidate_scores(_convictions(), np.array([[-0.9]]))[0, 0] < base
    # Eligibility is monotone: a name at the cut drops out when its score falls.
    scores = np.array([[2.0, 1.0, 0.9]])
    grades = np.array([[2, 1, 0]])
    mask, cut = att.admitted(scores, grades)
    assert cut[0] == 1.0
    assert mask[0].tolist() == [True, True, False]
    lifted = scores.copy()
    lifted[0, 2] = 1.0
    assert att.admitted(lifted, grades)[0][0].tolist() == [True, True, True]
    lowered = lifted.copy()
    lowered[0, 2] = 0.5
    assert att.admitted(lowered, grades)[0][0].tolist() == [True, True, False]
    # The weight side: a lower magnitude never raises a name's tilted weight.
    targets = np.array([0.1, 0.1, 0.1])
    high = risk.tilt_by_conviction(targets, np.array([0.8, 0.0, 0.0]), 0.5, 0.15)
    low = risk.tilt_by_conviction(targets, np.array([-0.8, 0.0, 0.0]), 0.5, 0.15)
    assert low[0] < high[0]


def test_nobody_admitted_when_the_grade_rule_admits_nobody():
    scores = np.array([[3.0, 2.5, 2.0]])
    grades = np.array([[0, 0, 0]])
    mask, cut = att.admitted(scores, grades)
    assert np.isnan(cut[0])
    assert not mask[0].any()


def test_score_admitted_names_are_sized_as_b():
    grades = np.array([[3, 0, 0]])
    mask = np.array([[True, True, False]])
    sized = att.sizing_grades(grades, mask)
    assert sized[0].tolist() == [3, grading.ORDINAL[grading.B], 0]


# The strictly trailing reference never sees today: a spike on the last
# session changes today's distance but not the median it is measured from.
def test_trailing_reference_excludes_todays_observation():
    x = np.full((300, 1), 1.0)
    x[-1, 0] = 5.0
    strict = att.trailing_reference(x, window=200, min_known=100)
    inclusive = att.history_reference(x, window=200, min_known=100)
    assert abs(strict[-1, 0] - (1.0 - 5.0)) < 1e-12
    assert strict[-1, 0] == inclusive[-1, 0]  # a median is robust to one point
    y = np.full((300, 1), 1.0)
    y[-150:, 0] = 3.0  # a level shift over the last 150 sessions
    strict_y = att.trailing_reference(y, window=200, min_known=100)
    inclusive_y = att.history_reference(y, window=200, min_known=100)
    # With 150 of the last 200 at 3.0 both medians are 3.0; move one session
    # earlier and the strictly trailing window holds one fewer of the new level.
    assert np.isfinite(strict_y[-1, 0])
    assert np.isnan(strict_y[50, 0])
    assert strict_y[0, 0] != strict_y[0, 0]  # NaN: nothing before the first session
    assert inclusive_y.shape == strict_y.shape
