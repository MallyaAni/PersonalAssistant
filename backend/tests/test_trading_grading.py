"""The grade, and the weights the analysts carry in it.

What has to hold: without weights the grade is exactly the rule as it
stood - equal weights, rotation at half; a weight set is scaled to the
same total so the grade thresholds keep their meaning; and the votes and
the summed conviction follow the same weights.
"""

import numpy as np
import pytest

from backend.agents.trading.desk import grading

NAMES = ("fundamental", "technical", "sentiment", "rotation", "value")


# Weights default to the rule and a different set is scaled to its total.
def test_analyst_weights_default_to_equal_and_scale_to_the_same_total():
    equal = grading.analyst_weights(None, NAMES)
    assert equal == {
        "fundamental": 1.0,
        "technical": 1.0,
        "sentiment": 1.0,
        "rotation": 0.5,
        "value": 1.0,
    }
    tilted = grading.analyst_weights({"value": 2.0, "technical": 0.5}, NAMES)
    assert abs(sum(tilted.values()) - 4.5) < 1e-9
    assert tilted["value"] > tilted["fundamental"] > tilted["technical"]
    assert tilted["rotation"] < tilted["fundamental"]  # kept at its own half


def _convictions():
    return {
        "fundamental": np.full((1, 2), 0.5),
        "technical": np.full((1, 2), -0.5),
        "sentiment": np.zeros((1, 2)),
        "value": np.zeros((1, 2)),
    }


# With weights the votes and the summed conviction follow the same set;
# without them the grade is what it always was.
def test_weights_move_the_votes_and_the_summed_conviction():
    bull = np.ones((1, 2), dtype=int)
    bear = -np.ones((1, 2), dtype=int)
    flat = np.zeros((1, 2), dtype=int)
    plain = grading.grade_stances(bull, bear, flat, None, flat, _convictions())
    heavy = grading.grade_stances(
        bull,
        bear,
        flat,
        None,
        flat,
        _convictions(),
        {"fundamental": 3.0, "technical": 1.0, "sentiment": 1.0, "value": 1.0},
    )
    assert plain.votes[0, 0] == 0.0  # one bull, one bear, equal weights
    assert heavy.votes[0, 0] > 0.0  # the heavier bull carries it
    assert np.isclose(plain.conviction[0, 0], 0.0)
    assert heavy.conviction[0, 0] > 0.0
    again = grading.grade_stances(bull, bear, flat, None, flat, _convictions())
    assert np.array_equal(plain.grades, again.grades)
    assert np.array_equal(plain.votes, again.votes)


# One name's grade from its stances follows the panel's rule exactly:
# the same thresholds, the release's role, and the bearish veto.
def test_one_name_grades_like_the_panel():
    from backend.agents.trading.desk.grading import ANALYST_WEIGHTS, grade_from_stances

    base = {"fundamental": 0, "technical": 0, "sentiment": 0, "value": 0, "rotation": 0}
    assert grade_from_stances(base, ANALYST_WEIGHTS)[0] == "C"
    assert grade_from_stances({**base, "technical": 1}, ANALYST_WEIGHTS)[0] == "B"
    assert (
        grade_from_stances({**base, "fundamental": 1, "technical": 1}, ANALYST_WEIGHTS)[
            0
        ]
        == "A"
    )
    assert (
        grade_from_stances({**base, "sentiment": 1, "rotation": 1}, ANALYST_WEIGHTS)[0]
        == "A"
    )
    assert (
        grade_from_stances(
            {**base, "sentiment": 1, "value": 1, "fundamental": 1}, ANALYST_WEIGHTS
        )[0]
        == "A+"
    )
    vetoed = {**base, "sentiment": 1, "value": 1, "fundamental": 1, "technical": -1}
    assert grade_from_stances(vetoed, ANALYST_WEIGHTS)[0] == "B"


# A sixth stance votes as another analyst under the unchanged rule: a full
# vote in the sum, no veto, no part in the release or strong-agreement
# clauses; it cannot be named after one of the five, and a zero sixth
# stance leaves the grade, the votes and the conviction exactly as they
# were.
def test_extra_stance_is_a_full_vote_that_never_vetoes():
    from backend.agents.trading.desk.grading import ANALYST_WEIGHTS, grade_from_stances

    def cell(f, t, s, v, x):
        arrays = [np.full((1, 1), k, dtype=int) for k in (f, t, s, v)]
        flat = np.zeros((1, 1), dtype=int)
        graded = grading.grade_stances(
            arrays[0], arrays[1], arrays[2], flat, arrays[3], None, ANALYST_WEIGHTS,
            extra={"table:x": np.full((1, 1), x, dtype=int)},
        )
        return graded.letter(0, 0), float(graded.votes[0, 0])

    # Alone it makes a B (one bull, nobody bearish); with one core bull an A;
    # with the release an A+ (release and votes >= 2).
    assert cell(0, 0, 0, 0, 1) == ("B", 1.0)
    assert cell(1, 0, 0, 0, 1) == ("A", 2.0)
    assert cell(0, 0, 1, 0, 1) == ("A+", 2.0)
    # Bearish it subtracts a vote without capping: the release with two core
    # bulls stays A+ at three votes; with one core bull the A+ at votes 2
    # falls to A (release and votes >= 1), not to B.
    assert cell(1, 1, 1, 0, -1) == ("A+", 2.0)
    assert cell(1, 0, 1, 0, -1) == ("A", 1.0)
    assert cell(0, 0, 0, 0, -1) == ("C", -1.0)
    # A bearish core analyst still vetoes whatever the sixth says.
    assert cell(1, -1, 1, 1, 1) == ("B", 3.0)
    # The one-name rule agrees cell for cell, so the sixth vote is "another
    # analyst's" by the rule the page re-grades with.
    for f in (-1, 0, 1):
        for s in (-1, 0, 1):
            for x in (-1, 0, 1):
                stances = {
                    "fundamental": f, "technical": 0, "sentiment": s, "rotation": 0,
                    "value": 1, "table:x": x,
                }
                expected = grade_from_stances(stances, ANALYST_WEIGHTS)
                assert cell(f, 0, s, 1, x) == expected
    # Zero leaves everything as it was, to the bit.
    bull = np.ones((2, 3), dtype=int)
    bear = -np.ones((2, 3), dtype=int)
    flat = np.zeros((2, 3), dtype=int)
    convictions = {
        "fundamental": np.full((2, 3), 0.3), "technical": np.full((2, 3), -0.2),
        "sentiment": np.full((2, 3), 0.1), "value": np.full((2, 3), 0.7),
    }
    plain = grading.grade_stances(
        bull, bear, flat, None, bull, convictions, ANALYST_WEIGHTS
    )
    with_zero = grading.grade_stances(
        bull, bear, flat, None, bull, {**convictions, "table:x": np.zeros((2, 3))},
        ANALYST_WEIGHTS, extra={"table:x": flat},
    )
    assert np.array_equal(plain.grades, with_zero.grades)
    assert np.array_equal(plain.votes, with_zero.votes)
    assert np.array_equal(plain.conviction, with_zero.conviction)
    assert set(with_zero.stances) == set(plain.stances) | {"table:x"}
    with pytest.raises(ValueError, match="an analyst is"):
        grading.grade_stances(bull, bear, flat, None, bull, extra={"sentiment": flat})
    with pytest.raises(ValueError, match="shaped like the panel"):
        grading.grade_stances(bull, bear, flat, None, bull, extra={"table:x": flat[:1]})
