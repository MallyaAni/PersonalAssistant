"""Behavioural tests for the pure-numpy walk-forward GBDT ranker.

Pure synthetic numpy inputs, no database, no Redis, no network. Each test
asserts on a property of the algorithm (a feature drives the label, exact
determinism, the walk-forward protocol leaks no future information, training
order is irrelevant, validation raises, and numeric sanity) rather than on
any fitted market number.
"""

import numpy as np
import pytest

from backend.market.rank_ranker import Ranker

# A fixed feature layout matching the shared 12-column contract, so the
# ranker is exercised at its real input width.
N_FEATURES = 12


# Rank the values of an array, ties broken by position, for a Spearman
# correlation without scipy.
def _ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="stable")
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(values.size)
    return ranks


# Pearson correlation of the ranks: Spearman's rho.
def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    ra, rb = _ranks(a), _ranks(b)
    return float(np.corrcoef(ra - ra.mean(), rb - rb.mean())[0, 1])


# A supervised dataset where the first two features genuinely drive y.
def _driven_data(n: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, N_FEATURES))
    y = 2.0 * x[:, 0] - 1.5 * x[:, 1] + 0.05 * rng.normal(size=n)
    return x, y


# Three expanding-window folds over one dataset: each test fold is strictly
# after all of its training rows, and each train set is non-empty.
def _folds(n_total: int, boundaries: tuple[int, int, int], seed: int) -> list[dict]:
    x, y = _driven_data(n_total, seed)
    return [
        {"train_X": x[:lo], "train_y": y[:lo], "test_X": x[lo:hi], "test_y": y[lo:hi]}
        for lo, hi in ((boundaries[0], boundaries[1]), (boundaries[1], boundaries[2]))
    ]


def test_rank_correlates_with_the_driving_feature() -> None:
    """A real driver in the features must be picked up on held-out data."""
    x, y = _driven_data(900, 7)
    model = Ranker(seed=0, n_estimators=120).fit(x[:600], y[:600])
    pred = model.predict(x[600:])
    rho = _spearman(pred, y[600:])
    # The model must clearly do better than a coin flip on an unseen block.
    assert rho > 0.4, f"expected a strong OOS rank correlation, got {rho:.3f}"


def test_same_seed_is_bit_identical() -> None:
    """Determinism: identical seeds produce identical predictions."""
    x, y = _driven_data(300, 3)
    a = Ranker(seed=3, n_estimators=60).fit(x, y).predict(x)
    b = Ranker(seed=3, n_estimators=60).fit(x, y).predict(x)
    np.testing.assert_array_equal(a, b)


def test_walk_forward_concatenates_per_fold_predictions() -> None:
    """The OOS vector is exactly the per-fold predictions in fold order."""
    folds = _folds(200, (40, 90, 200), 11)
    result = Ranker.walk_forward_rank(folds, seed=0, n_estimators=60)
    assert len(result["per_fold_predictions"]) == 2
    expected = np.concatenate(result["per_fold_predictions"])
    np.testing.assert_array_equal(result["out_of_sample"], expected)


def test_walk_forward_leaks_no_future_information() -> None:
    """An earlier fold's predictions depend only on that fold's own training set.

    Fit a model on exactly the first fold's training rows and assert it
    reproduces that fold's walk-forward predictions, even though the walk
    ran over later folds too: no future label can have reached an earlier
    fold's predictions.
    """
    folds = _folds(200, (40, 90, 200), 13)
    result = Ranker.walk_forward_rank(folds, seed=0, n_estimators=60)
    solo = Ranker(seed=0, n_estimators=60).fit(folds[0]["train_X"], folds[0]["train_y"])
    np.testing.assert_array_equal(
        solo.predict(folds[0]["test_X"]), result["per_fold_predictions"][0]
    )


def test_training_row_order_is_irrelevant() -> None:
    """Shuffling the training rows must not change the fitted model."""
    x, y = _driven_data(500, 5)
    order = np.random.default_rng(5).permutation(500)
    a = Ranker(seed=0, n_estimators=60).fit(x, y).predict(x)
    b = Ranker(seed=0, n_estimators=60).fit(x[order], y[order]).predict(x)
    np.testing.assert_allclose(a, b, rtol=1e-12, atol=1e-12)


def test_walk_forward_requires_all_fold_keys() -> None:
    """A fold missing a required key raises rather than silently dropping it."""
    x, _ = _driven_data(40, 4)
    with pytest.raises(ValueError, match="missing required keys"):
        Ranker.walk_forward_rank([{"train_X": x, "train_y": np.zeros(40)}], seed=0)


def test_mismatched_shapes_raise() -> None:
    """Labels with the wrong length must be rejected before fitting."""
    x, _ = _driven_data(40, 4)
    with pytest.raises(ValueError, match="one label per row"):
        Ranker(seed=0).fit(x, np.zeros(30))


def test_non_finite_training_rows_raise() -> None:
    """A NaN in training features must be rejected, never silently ignored."""
    x, y = _driven_data(40, 4)
    x[3, 2] = np.nan
    with pytest.raises(ValueError, match="only finite values"):
        Ranker(seed=0).fit(x, y)


def test_predict_before_fit_raises() -> None:
    """An unfitted ranker must refuse to predict."""
    x, _ = _driven_data(10, 4)
    with pytest.raises(ValueError, match="before predict"):
        Ranker(seed=0).predict(x)


def test_constant_target_is_predicted_exactly() -> None:
    """A model fit on a constant label predicts that constant everywhere."""
    x, _ = _driven_data(120, 4)
    y = np.full(120, 0.037)
    pred = Ranker(seed=0, n_estimators=30).fit(x, y).predict(x)
    assert np.isfinite(pred).all()
    np.testing.assert_allclose(pred, 0.037, rtol=1e-9, atol=1e-9)


def test_feature_count_is_pinned_to_the_contract() -> None:
    """The fitted feature count records the shared 12-column contract."""
    x, y = _driven_data(60, 4)
    model = Ranker(seed=0).fit(x, y)
    assert model.n_features_in_ == N_FEATURES
