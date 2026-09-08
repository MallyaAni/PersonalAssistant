"""The snapback study's pure parts.

What has to hold: the bottom-fraction flag is taken per session across
the universe only, and the paired spread is the per-session mean
difference with a Newey-West t that goes to nothing on noise.
"""

import numpy as np

from backend.cli.market_snapback import _bottom, _spread


def test_bottom_fraction_is_per_session_and_within_the_universe():
    values = np.array(
        [
            [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 0.0],
            [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0, 0.0],
        ]
    )
    universe = np.ones_like(values, dtype=bool)
    universe[:, -1] = False  # the outsider, lowest of all, is not in the universe
    flag = _bottom(values, universe, 0.2)
    assert flag[0].tolist() == [True, True] + [False] * 9
    assert flag[1].tolist() == [False] * 8 + [True, True, False]
    # Too few names on a session: nothing flagged.
    small = _bottom(values[:, :5], universe[:, :5], 0.2)
    assert not small.any()


def test_spread_is_the_paired_session_mean_difference():
    rng = np.random.default_rng(0)
    label = rng.normal(0.0, 0.01, size=(300, 20))
    a = np.zeros_like(label, dtype=bool)
    a[:, :10] = True
    b = ~a
    mean, t, n = _spread(label, a, b, lag=5)
    assert abs(mean) < 0.002
    assert abs(t) < 3.0
    assert n == 300 * 10
    label[:, :10] += 0.01
    mean, t, _n = _spread(label, a, b, lag=5)
    assert 0.008 < mean < 0.012
    assert t > 5.0
