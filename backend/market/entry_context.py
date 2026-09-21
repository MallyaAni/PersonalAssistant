"""Point-in-time quarterly context for the ten-session entry ablation; research only.

The entry pilot decides with price features alone. This module joins the
seven corrected quarterly features from ``fundamental_features`` to every
decision at the session before the decision day, and derives the three
companion blocks the ablation compares against price-only: the imputed
economic values, their missingness flags, and each referenced fiscal period's
age. Everything is read at decision day minus one; a decision with no prior
session cannot be given context and fails rather than guessing.
"""

import numpy as np

from backend.market import fundamental_features as ff

# The seven corrected quarterly features carried from the adapter.
ECONOMIC = ff.FEATURE_NAMES
K = len(ECONOMIC)

# Ages outside [0, MAX_AGE_DAYS] are invalid; unknown ages are encoded as this.
MAX_AGE_DAYS = 2000
UNKNOWN_AGE = 2000.0


# Read one observation's fundamental block one session before its decision day.
def prior_context(features: ff.FundamentalFeatures, day: int, name: int):
    """Return the (K,) values and period ends for one row read at day minus one.

    A decision at day zero has no prior session and raises; the caller never
    reads the decision day's own or any future session's fundamentals.
    """
    if day < 1:
        raise ValueError(f"no prior session for decision day {day}")
    read = int(day) - 1
    return (
        features.values[read, int(name)],
        features.period_ends[read, int(name)],
    )


# Join the fundamental block to every observation at day-1, with validation.
def context_block(
    features: ff.FundamentalFeatures, days: np.ndarray, names: np.ndarray
):
    """Return (R, K) raw values and (R, K) period ends, read one session early.

    Every observation must have a prior session; the first session in the
    panel has none and fails, so no feature ever leaks the decision day.
    """
    rows = len(days)
    values = np.full((rows, K), np.nan)
    ends = np.full((rows, K), np.datetime64("NaT", "D"))
    for r in range(rows):
        if days[r] < 1:
            raise ValueError(f"day-zero observation {r} cannot read prior context")
        v, e = prior_context(features, int(days[r]), int(names[r]))
        values[r] = v
        ends[r] = e
    return values, ends


# Per-feature fiscal-period age at each read session, clamped and validated.
def fiscal_ages(
    dates: np.ndarray, days: np.ndarray, values: np.ndarray, ends: np.ndarray
):
    """Return (R, K) days from each period end to the read session.

    A referenced period ending after the read session is invalid data and
    fails. Ages are clamped to [0, MAX_AGE_DAYS]; an unknown age (missing
    feature, or a finite value with no period end) is MAX_AGE_DAYS.
    """
    ages = np.full(values.shape, UNKNOWN_AGE)
    for r in range(len(days)):
        when = dates[int(days[r]) - 1]
        for k in range(values.shape[1]):
            if np.isnan(values[r, k]) or np.isnat(ends[r, k]):
                continue
            age = int((when - ends[r, k]) / np.timedelta64(1, "D"))
            if age < 0:
                raise ValueError(f"negative fiscal age {age} for row {r} column {k}")
            ages[r, k] = min(float(age), float(MAX_AGE_DAYS))
    return ages


# Per-column training-only medians, zero when a column is all-missing in training.
def training_medians(values: np.ndarray, train: np.ndarray):
    """Return (K,) medians over training rows only; zero for all-missing columns.

    Evaluation rows never influence the imputation values, and a column with
    no finite training value falls back to a median of zero.
    """
    medians = np.zeros(values.shape[1])
    for k in range(values.shape[1]):
        finite = values[train, k][np.isfinite(values[train, k])]
        if len(finite):
            medians[k] = float(np.median(finite))
    return medians


# Missingness flags before any imputation; a genuine zero keeps flag 0.
def missing_flags(values: np.ndarray):
    """Return (R, K) 0/1 flags marking values missing before imputation."""
    return np.isnan(values).astype(np.float32)


# Fill missing values with the fixed medians, leaving genuine zeros as zeros.
def impute(values: np.ndarray, medians: np.ndarray):
    """Return (R, K) with NaN replaced by the per-column median, as float32."""
    return np.where(np.isnan(values), medians, values).astype(np.float32)


# Assemble the (R, 21) context block: imputed values, missing flags, ages.
def context_columns(
    features: ff.FundamentalFeatures,
    days: np.ndarray,
    names: np.ndarray,
    dates: np.ndarray,
    train: np.ndarray,
):
    """Return the (R, 7+7+7) context block and the (K,) training medians.

    The block is imputed economic values, missingness flags computed before
    imputation, and fiscal ages, each anchored to the prior session.
    """
    values, ends = context_block(features, days, names)
    medians = training_medians(values, train)
    flags = missing_flags(values)
    ages = fiscal_ages(dates, days, values, ends)
    filled = impute(values, medians)
    return np.column_stack((filled, flags, ages)), medians
