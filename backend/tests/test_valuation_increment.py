"""The valuation-increment experiment's statistics, on inputs with known answers.

What has to hold: the rank correlation is one on a monotone pair and NaN
on a constant; the HAC t on an independent series has an effective size
near its length and on a series made of repeated blocks a much smaller
one; the beta-adjusted label of the benchmark against itself is zero and
a name with zero beta keeps its own return.
"""

import numpy as np

from backend.cli import market_valuation_increment as vi


def test_rank_correlation_on_known_pairs():
    a = np.array([1.0, 2.0, 3.0, 4.0])
    assert abs(vi.rank_corr(a, np.exp(a)) - 1.0) < 1e-12
    assert abs(vi.rank_corr(a, -a) + 1.0) < 1e-12
    assert np.isnan(vi.rank_corr(a, np.ones(4)))
    assert np.isnan(vi.rank_corr(a[:2], a[:2]))


def test_hac_effective_size_shrinks_with_overlap():
    rng = np.random.default_rng(1)
    iid = rng.normal(size=2000)
    out = vi.hac(iid, lag=20)
    assert out["n"] == 2000
    assert 0.6 * 2000 < out["n_effective"] < 1.6 * 2000
    blocks = np.repeat(rng.normal(size=100), 20)  # each value held twenty sessions
    dependent = vi.hac(blocks, lag=20)
    assert dependent["n_effective"] < 0.2 * 2000
    assert abs(dependent["t"]) < abs(out["t"]) * 10  # finite, not exploded


def test_labels_are_beta_adjusted_from_the_next_close():
    rng = np.random.default_rng(2)
    t = 400
    market = np.cumprod(1 + rng.normal(0, 0.01, size=t))
    flat = np.full(t, 50.0)  # zero beta, zero return
    prices = np.column_stack((market, flat, market * 2))
    y = vi.labels(prices, benchmark=0)
    # The benchmark against itself is zero; a doubled benchmark has beta one
    # and the same log return, so its excess is zero too.
    assert np.allclose(y[200:-21, 0], 0.0)
    assert np.allclose(y[200:-21, 2], 0.0, atol=1e-6)
    # A flat name has zero own return and zero beta: label zero.
    assert np.allclose(y[200:-21, 1], 0.0)
    # The last twenty-one rows have no endpoint.
    assert np.isnan(y[-vi.HORIZON :]).all()
