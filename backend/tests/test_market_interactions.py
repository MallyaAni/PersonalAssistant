"""The interaction study's pure parts.

What has to hold: the training mask for a test year excludes the
horizon of sessions before it, so no label reaches into the year; the
network's hold-out is the most recent tenth of the rows with the
horizon before it purged from training; the pairwise features are the
inputs and every product of two; the ridge recovers a linear signal;
and a selection by score grades the top fifth A and the next fifth B
with no veto.
"""

import numpy as np

from backend.cli.market_interactions import (
    _holdout,
    _pairs,
    _ridge,
    training_mask,
)


def test_training_mask_purges_the_horizon_before_the_test_year():
    years = np.array([2018] * 30 + [2019] * 10)
    mask = training_mask(years, 2019, horizon=5)
    assert mask[:25].all()
    assert not mask[25:30].any()  # the last five sessions of 2018 reach into 2019
    assert not mask[30:].any()


def test_the_holdout_is_split_first_and_purged():
    n = 100
    x = np.arange(n * 3, dtype=float).reshape(n, 3)
    y = np.arange(n, dtype=float)
    xa, ya, xv, yv = _holdout(x, y)
    # The validation is the most recent tenth of the rows.
    assert len(xv) == 10
    assert (xv == x[90:]).all()
    # The twenty sessions before it are purged from training, so their
    # forward labels do not reach into the validation window.
    assert len(xa) == 70
    assert (xa == x[:70]).all()


def test_pairs_adds_every_product():
    x = np.array([[1.0, 2.0, 3.0]])
    out = _pairs(x)
    assert out.shape == (1, 6)
    assert out[0].tolist() == [1.0, 2.0, 3.0, 2.0, 3.0, 6.0]


def test_ridge_recovers_a_linear_signal():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(2000, 3))
    y = 2.0 * x[:, 0] - x[:, 1] + rng.normal(scale=0.1, size=2000)
    pred = _ridge(x[:1500], y[:1500], x[1500:], lam=1.0)
    assert np.corrcoef(pred, y[1500:])[0, 1] > 0.95
