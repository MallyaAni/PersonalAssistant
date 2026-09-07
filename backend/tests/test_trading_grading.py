"""The grade, and the weights the analysts carry in it.

What has to hold: without weights the grade is exactly the rule as it
stood - equal weights, rotation at half; a weight set is scaled to the
same total so the grade thresholds keep their meaning; and the votes and
the summed conviction follow the same weights.
"""

import numpy as np

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
