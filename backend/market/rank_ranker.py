"""Pure-numpy walk-forward gradient-boosted decision-tree ranker.

Step-2 experimental ML ranker for the trading desk: a deterministic
gradient-boosted decision-tree regressor that predicts each name's forward
return (a continuous quantity the caller later ranks), fitted with strict
no-lookahead discipline under an expanding as-of walk and judged honestly
out-of-sample. Only numpy and the standard library are used - no pandas, no
sklearn, no scipy, no xgboost/lightgbm - so this runs in the same image as the
rest of the market research.

Scope: the ALGORITHM only. This module does not build features, read the real
data store, or evaluate the strategy; it fits and predicts on caller-supplied
matrices that obey the shared 12-feature contract (the exact column order
documented in the contract, float64, NaN only in rows the caller drops before
calling ``fit``). The label convention (buy at the next session's open after
the decision session, sell at session D+horizon's close) is likewise the
caller's: the ranker treats ``y`` as an opaque continuous target, and a row is
expected to be presented for training only when every feature and its label
are finite.

Hyper-parameters are bounded for prototype runtime: 100 shallow trees (depth 3)
at a 0.1 learning rate fit a full walk-forward over thousands of rows in
seconds. Determinism: the same seed produces bit-identical models and
predictions, and the seed also resolves any splits whose variance reduction
ties, so a different seed is free to build a different (equally good) tree.
"""

from __future__ import annotations

import numpy as np

# The default boosting and tree hyper-parameters, exported so tests and
# callers share a single source of truth for the documented defaults.
DEFAULT_N_ESTIMATORS = 100
DEFAULT_LEARNING_RATE = 0.1
DEFAULT_MAX_DEPTH = 3
DEFAULT_MIN_SAMPLES_LEAF = 10

# A split must reduce the node's weighted squared error by more than this to
# count as an improvement; an exact tie with the best gain (within a relative
# and absolute tolerance) is resolved by the seeded RNG.
_IMPROVEMENT_FLOOR = 1e-12
_GAIN_TOL = 1e-12


class _RegressionTree:
    """A shallow pure-numpy binary regression tree with variance-reducing splits.

    Internal to the ranker: each boosting round fits one of these to the
    current residual. Nodes are stored as parallel numpy arrays so ``predict``
    walks every row of a batch at once.
    """

    def __init__(self, max_depth: int, min_samples_leaf: int) -> None:
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.feature: np.ndarray | None = None
        self.threshold: np.ndarray | None = None
        self.left: np.ndarray | None = None
        self.right: np.ndarray | None = None
        self.value: np.ndarray | None = None

    def fit(
        self,
        x: np.ndarray,
        target: np.ndarray,
        weight: np.ndarray,
        rng: np.random.Generator,
    ) -> None:
        """Build the tree on ``target`` (the residual) from ``x``, in place."""
        nodes: list[dict[str, float | int]] = []

        def grow(indices: np.ndarray, depth: int) -> None:
            """Append this node, then its left and right subtrees, in preorder.

            A preorder layout is what makes ``left = node_index + 1`` always
            true (the left subtree is built immediately after its parent), so
            the right child index can be fixed only after the left subtree is
            complete. A breadth-first layout breaks this, which is the defect
            this replaces.
            """
            value = float(np.average(target[indices], weights=weight[indices]))
            idx = len(nodes)
            nodes.append(
                {
                    "feature": -1,
                    "threshold": 0.0,
                    "left": -1,
                    "right": -1,
                    "value": value,
                }
            )
            if depth >= self.max_depth or len(indices) < 2 * self.min_samples_leaf:
                return
            feature, threshold = _best_split(
                x, target, weight, indices, self.min_samples_leaf, rng
            )
            if feature is None:
                return
            column = x[indices, feature]
            left_rows = indices[column <= threshold]
            right_rows = indices[column > threshold]
            nodes[idx]["feature"] = feature
            nodes[idx]["threshold"] = threshold
            nodes[idx]["left"] = len(nodes)
            grow(left_rows, depth + 1)
            nodes[idx]["right"] = len(nodes)
            grow(right_rows, depth + 1)

        grow(np.arange(x.shape[0]), 0)
        self.feature = np.asarray([int(nd["feature"]) for nd in nodes], dtype=np.int64)
        self.threshold = np.asarray(
            [float(nd["threshold"]) for nd in nodes], dtype=np.float64
        )
        self.left = np.asarray([int(nd["left"]) for nd in nodes], dtype=np.int64)
        self.right = np.asarray([int(nd["right"]) for nd in nodes], dtype=np.int64)
        self.value = np.asarray([float(nd["value"]) for nd in nodes], dtype=np.float64)

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Return this tree's leaf value for every row of ``x``."""
        n = x.shape[0]
        current = np.zeros(n, dtype=np.int64)
        row = np.arange(n)
        for _ in range(self.max_depth + 1):
            feature = self.feature[current]
            is_leaf = feature < 0
            if is_leaf.all():
                break
            value = x[row, feature]
            go_left = np.isnan(value) | (value <= self.threshold[current])
            moved = np.where(go_left, self.left[current], self.right[current])
            current = np.where(is_leaf, current, moved)
        return self.value[current]


# Find the single best variance-reducing split among all candidate midpoints.
def _best_split(
    x: np.ndarray,
    target: np.ndarray,
    weight: np.ndarray,
    indices: np.ndarray,
    min_samples_leaf: int,
    rng: np.random.Generator,
) -> tuple[int, float] | tuple[None, None]:
    """Return (feature, threshold) of the best split on ``indices``.

    Every midpoint between consecutive distinct values of every feature is a
    candidate; each is scored by the reduction in the node's weighted squared
    error. Exact ties for the best gain are gathered and resolved by ``rng``,
    so the same seed always picks the same one while a different seed may pick
    a different equally-good split. Returns (None, None) when no split
    improves the node (constant target, all values equal, or a child too
    small).
    """
    node_target = target[indices]
    node_weight = weight[indices]
    total_w = float(node_weight.sum())
    sum_wy = float((node_weight * node_target).sum())
    sum_wyy = float((node_weight * node_target * node_target).sum())
    parent_sse = sum_wyy - sum_wy * sum_wy / total_w
    m = len(indices)

    candidates: list[tuple[float, int, float]] = []
    for feature in range(x.shape[1]):
        values = x[indices, feature]
        order = np.argsort(values, kind="stable")
        vs = values[order]
        ys = node_target[order]
        ws = node_weight[order]
        wc = np.cumsum(ws)
        wyc = np.cumsum(ws * ys)
        wyyc = np.cumsum(ws * ys * ys)
        ks = np.arange(min_samples_leaf, m - min_samples_leaf + 1)
        wl = wc[ks - 1]
        wyl = wyc[ks - 1]
        wyyl = wyyc[ks - 1]
        wr = wc[-1] - wl
        wyr = wyc[-1] - wyl
        wyyr = wyyc[-1] - wyyl
        gains = parent_sse - (wyyl - wyl * wyl / wl) - (wyyr - wyr * wyr / wr)
        valid = (vs[ks - 1] < vs[ks]) & np.isfinite(gains)
        if not valid.any():
            continue
        valid_ks = ks[valid]
        valid_gains = gains[valid]
        best_gain_f = float(valid_gains.max())
        tied = np.isclose(valid_gains, best_gain_f, rtol=_GAIN_TOL, atol=1e-15)
        for k in valid_ks[tied]:
            candidates.append((best_gain_f, feature, float((vs[k - 1] + vs[k]) / 2.0)))
    if not candidates:
        return None, None
    best_gain = max(gain for gain, _, _ in candidates)
    if best_gain <= _IMPROVEMENT_FLOOR:
        return None, None
    tied_all = [
        (feature, threshold)
        for gain, feature, threshold in candidates
        if np.isclose(gain, best_gain, rtol=_GAIN_TOL, atol=1e-15)
    ]
    if len(tied_all) == 1:
        return tied_all[0]
    return tied_all[int(rng.integers(0, len(tied_all)))]


# Validate a 2-D feature matrix, returning it as float64 (or raising).
def _check_x(x, *, allow_nan: bool, n_features_in: int | None = None) -> np.ndarray:
    """Return ``x`` as a float64 matrix after shape/finiteness checks."""
    arr = np.asarray(x, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError(
            "X must be a two-dimensional array of shape (n_samples, n_features)"
        )
    if arr.shape[0] == 0:
        raise ValueError("X must contain at least one row")
    if not allow_nan and not np.isfinite(arr).all():
        raise ValueError("X must contain only finite values for training")
    if n_features_in is not None and arr.shape[1] != n_features_in:
        raise ValueError(
            f"X has {arr.shape[1]} features but the model was fitted on {n_features_in}"
        )
    return arr


# Validate the label vector, returning it as finite float64 (or raising).
def _check_y(y, n_samples: int) -> np.ndarray:
    """Return ``y`` as a finite float64 length-``n_samples`` vector."""
    arr = np.asarray(y, dtype=np.float64)
    if arr.ndim != 1 or arr.shape[0] != n_samples:
        raise ValueError("y must be one-dimensional with one label per row of X")
    if not np.isfinite(arr).all():
        raise ValueError("y must contain only finite labels")
    return arr


# Validate the optional per-row weights, returning float64 (or raising).
def _check_sample_weight(sample_weight, n_samples: int) -> np.ndarray:
    """Return ``sample_weight`` as a finite non-negative float64 vector."""
    if sample_weight is None:
        return np.ones(n_samples, dtype=np.float64)
    arr = np.asarray(sample_weight, dtype=np.float64)
    if arr.ndim != 1 or arr.shape[0] != n_samples:
        raise ValueError(
            "sample_weight must be one-dimensional with one weight per row"
        )
    if not np.isfinite(arr).all() or (arr < 0).any():
        raise ValueError("sample_weight must be finite and non-negative")
    if not (arr > 0).any():
        raise ValueError("sample_weight must include at least one positive weight")
    return arr


class Ranker:
    """A deterministic gradient-boosted regression-tree ranker (numpy only).

    Predicts a continuous forward return from the shared 12-feature contract
    vector. Shallow trees are fit additively on the squared-error residual
    with a fixed learning rate; identical seeds produce bit-identical models
    and predictions, and the seed also resolves tied splits.
    """

    def __init__(
        self,
        *,
        seed: int = 0,
        n_estimators: int = DEFAULT_N_ESTIMATORS,
        learning_rate: float = DEFAULT_LEARNING_RATE,
        max_depth: int = DEFAULT_MAX_DEPTH,
        min_samples_leaf: int = DEFAULT_MIN_SAMPLES_LEAF,
    ) -> None:
        """Store and validate the boosting and tree hyper-parameters."""
        if not isinstance(seed, (int, np.integer)):
            raise TypeError("seed must be an integer")
        if not isinstance(n_estimators, (int, np.integer)) or n_estimators < 1:
            raise TypeError("n_estimators must be a positive integer")
        if not isinstance(max_depth, (int, np.integer)) or max_depth < 1:
            raise TypeError("max_depth must be a positive integer")
        if not isinstance(min_samples_leaf, (int, np.integer)) or min_samples_leaf < 1:
            raise TypeError("min_samples_leaf must be a positive integer")
        if not np.isfinite(learning_rate) or learning_rate <= 0:
            raise TypeError("learning_rate must be a positive finite number")
        self.seed = int(seed)
        self.n_estimators = int(n_estimators)
        self.learning_rate = float(learning_rate)
        self.max_depth = int(max_depth)
        self.min_samples_leaf = int(min_samples_leaf)
        self.n_features_in_: int | None = None
        self._base_prediction_: float | None = None
        self._trees_: list[_RegressionTree] = []
        self._fitted_: bool = False

    def fit(self, x, y, sample_weight=None) -> Ranker:
        """Fit the boosted ensemble to ``y`` from ``x`` and return ``self``.

        Validates shapes and finiteness, then fits ``n_estimators`` shallow
        trees to the squared-error residual, each scaled by ``learning_rate``
        and added to the running prediction. Training rows that are not fully
        finite raise ``ValueError``; the caller must have already dropped rows
        whose features or label are unavailable.
        """
        x_arr = _check_x(x, allow_nan=False)
        y_arr = _check_y(y, x_arr.shape[0])
        weight = _check_sample_weight(sample_weight, x_arr.shape[0])
        self.n_features_in_ = int(x_arr.shape[1])
        rng = np.random.default_rng(self.seed)
        base = float(np.average(y_arr, weights=weight))
        self._base_prediction_ = base
        self._trees_ = []
        prediction = np.full(x_arr.shape[0], base, dtype=np.float64)
        for _ in range(self.n_estimators):
            residual = y_arr - prediction
            tree = _RegressionTree(self.max_depth, self.min_samples_leaf)
            tree.fit(x_arr, residual, weight, rng)
            self._trees_.append(tree)
            prediction = prediction + self.learning_rate * tree.predict(x_arr)
        self._fitted_ = True
        return self

    def predict(self, x) -> np.ndarray:
        """Return the fitted model's forward-return prediction for every row.

        ``x`` must share the fitted feature count; a NaN feature value (a row
        the caller chose to score despite an unavailable feature) routes to
        the left branch rather than failing.
        """
        if not self._fitted_:
            raise ValueError("Ranker must be fitted before predict is called")
        x_arr = _check_x(x, allow_nan=True, n_features_in=self.n_features_in_)
        out = np.full(x_arr.shape[0], self._base_prediction_, dtype=np.float64)
        for tree in self._trees_:
            out = out + self.learning_rate * tree.predict(x_arr)
        return out

    @classmethod
    def walk_forward_rank(cls, folds, *, seed: int = 0, **kwargs) -> dict[str, object]:
        """Return the honest expanding-window out-of-sample predictions.

        ``folds`` is a sequence of dicts, each with the keys "train_X",
        "train_y", "test_X" and "test_y", in natural as-of order where every
        test fold is strictly after all of its own training data. For each
        fold t the caller's train set is the cumulative history known at that
        fold's boundary (an expanding window), and this method fits one Ranker
        per fold on ONLY that fold's train set, then predicts that fold's test
        rows. Because no fold's model ever sees its own test rows, and because
        the caller supplies expanding train sets, the concatenated
        out-of-sample vector is honest: no future label reaches any
        prediction. Returns a dict with "per_fold_predictions" (a list of
        arrays, one per fold in order) and "out_of_sample" (their
        concatenation, in the same order).
        """
        required = {"train_X", "train_y", "test_X", "test_y"}
        per_fold: list[np.ndarray] = []
        for fold in folds:
            missing = required - set(fold)
            if missing:
                raise ValueError(f"fold missing required keys: {sorted(missing)}")
            model = cls(seed=seed, **kwargs)
            model.fit(fold["train_X"], fold["train_y"])
            per_fold.append(model.predict(fold["test_X"]))
        out_of_sample = (
            np.concatenate(per_fold) if per_fold else np.zeros(0, dtype=np.float64)
        )
        return {
            "per_fold_predictions": per_fold,
            "out_of_sample": out_of_sample,
        }
