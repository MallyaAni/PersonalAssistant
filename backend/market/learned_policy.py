"""Experimental walk-forward forecasts with explicit observation-time gates.

The caller supplies a historically recorded feature panel, membership and
adjusted opens.  This module deliberately cannot turn a present-day universe
or a recent, restated snapshot into an adoption-grade historical backtest.
It produces shadow forecasts only; account sizing and order placement stay in
the existing desk.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from hashlib import sha256

import numpy as np

RANKER_HORIZON = 10
RANKER_LABEL_END = RANKER_HORIZON + 1
BRAKE_HORIZON = 20
RANKER_MIN_SESSIONS = 750
BRAKE_MIN_SESSIONS = 1000
BRAKE_REFIT_SESSIONS = 63
POLICY_RANK = "learned-rank/1-shadow"
POLICY_BLEND = "learned-blend/1-shadow"
POLICY_BRAKE = "learned-brake/1-shadow"


@dataclass(frozen=True)
class HistoricalInputs:
    """Aligned, already archived observations; unknown membership is -1."""

    dates: np.ndarray
    tickers: tuple[str, ...]
    adjusted_open: np.ndarray
    adjusted_open_recorded_on: np.ndarray
    features: np.ndarray
    feature_recorded_on: np.ndarray
    membership: np.ndarray
    membership_recorded_on: np.ndarray
    spy: str = "SPY"
    # Reconstructed research uses assumed session availability, never a claim
    # that the old input was archived then. Its forecasts cannot size live targets.
    evidence_basis: str = "recorded"
    rank_features: tuple[bool, ...] | None = None


@dataclass(frozen=True)
class Forecasts:
    """Out-of-sample predictions and the training cutoff for each row."""

    values: np.ndarray
    fit_session: np.ndarray
    last_training_label_end: np.ndarray
    model_hash: tuple[str, ...]
    dates: np.ndarray
    tickers: tuple[str, ...]
    evidence_basis: str = "recorded"


# Reject malformed or retrospectively published inputs before fitting.
def validate(inputs: HistoricalInputs) -> tuple[np.ndarray, int]:  # noqa: C901
    """Return the session dates and SPY column after strict causal checks."""
    dates = np.asarray(inputs.dates, dtype="datetime64[D]")
    if inputs.evidence_basis not in ("recorded", "retrospective-price"):
        raise ValueError("unknown learning evidence basis")
    if dates.ndim != 1 or len(dates) < 2 or np.isnat(dates).any():
        raise ValueError("dates must be a nonempty exchange-session calendar")
    if np.any(dates[1:] <= dates[:-1]):
        raise ValueError("dates must be strictly increasing")
    if (
        len(set(inputs.tickers)) != len(inputs.tickers)
        or inputs.spy not in inputs.tickers
    ):
        raise ValueError("tickers must be unique and include SPY")
    shape = (len(dates), len(inputs.tickers))
    opens = np.asarray(inputs.adjusted_open, dtype=float)
    features = np.asarray(inputs.features, dtype=float)
    members = np.asarray(inputs.membership)
    if opens.shape != shape or members.shape != shape:
        raise ValueError("opens and membership must align with dates and tickers")
    if features.ndim != 3 or features.shape[:2] != shape or features.shape[2] == 0:
        raise ValueError("features must be a nonempty (session, ticker, feature) cube")
    if inputs.rank_features is not None and (
        len(inputs.rank_features) != features.shape[2]
        or any(type(flag) is not bool for flag in inputs.rank_features)
    ):
        raise ValueError("rank-feature mask must contain one boolean per feature")
    if np.isinf(features).any() or np.isinf(opens).any():
        raise ValueError("infinite input is not a missing observation")
    if np.any(np.isfinite(opens) & (opens <= 0)):
        raise ValueError("available adjusted opens must be positive")
    open_when = np.asarray(inputs.adjusted_open_recorded_on, dtype="datetime64[D]")
    if open_when.shape != shape:
        raise ValueError("adjusted-open publication dates must align with opens")
    if np.any(
        np.isfinite(opens) & (np.isnat(open_when) | (open_when > dates[:, None]))
    ):
        raise ValueError("an adjusted open was not recorded by its session")
    if not np.isin(members, (-1, 0, 1)).all():
        raise ValueError("membership must be unknown, absent or present")
    feature_when = np.asarray(inputs.feature_recorded_on, dtype="datetime64[D]")
    member_when = np.asarray(inputs.membership_recorded_on, dtype="datetime64[D]")
    if feature_when.shape != features.shape or member_when.shape != shape:
        raise ValueError("recorded-on arrays must align with their observations")
    if np.any(
        np.isfinite(features)
        & (np.isnat(feature_when) | (feature_when > dates[:, None, None]))
    ):
        raise ValueError("a feature was not recorded by its decision session")
    if np.any(
        (members != -1) & (np.isnat(member_when) | (member_when > dates[:, None]))
    ):
        raise ValueError("membership was not recorded by its decision session")
    return dates, inputs.tickers.index(inputs.spy)


# Derive the fixed next-open-to-open target on one consistent adjusted basis.
def relative_open_labels(inputs: HistoricalInputs) -> np.ndarray:
    """Return ten-session log returns relative to SPY, NaN if unknown."""
    _, spy = validate(inputs)
    opens = np.asarray(inputs.adjusted_open, dtype=float)
    out = np.full(opens.shape, np.nan)
    for t in range(len(opens) - RANKER_LABEL_END):
        start = opens[t + 1]
        end = opens[t + RANKER_LABEL_END]
        if not (np.isfinite(start[spy]) and np.isfinite(end[spy])):
            continue
        with np.errstate(divide="ignore", invalid="ignore"):
            out[t] = np.log(end / start) - np.log(end[spy] / start[spy])
    out[np.asarray(inputs.membership) != 1] = np.nan
    out[:, spy] = np.nan
    return out


# Rank each feature only among names known to belong on that session.
def cross_sectional_ranks(inputs: HistoricalInputs) -> np.ndarray:
    """Return percentile ranks; missing features and nonmembers stay NaN."""
    validate(inputs)
    raw = np.asarray(inputs.features, dtype=float)
    out = np.full(raw.shape, np.nan)
    for t in range(raw.shape[0]):
        for k in range(raw.shape[2]):
            valid = (inputs.membership[t] == 1) & np.isfinite(raw[t, :, k])
            valid[inputs.tickers.index(inputs.spy)] = False
            values = raw[t, valid, k]
            if inputs.rank_features is not None and not inputs.rank_features[k]:
                out[t, valid, k] = values
                continue
            if len(values) < 2:
                continue
            order = np.argsort(values, kind="stable")
            sorted_values = values[order]
            ranks = np.empty(len(values), dtype=float)
            left = 0
            while left < len(values):
                right = left + 1
                while (
                    right < len(values) and sorted_values[right] == sorted_values[left]
                ):
                    right += 1
                ranks[order[left:right]] = ((left + right - 1) / 2) / (len(values) - 1)
                left = right
            out[t, valid, k] = ranks
    return out


# A label can enter a fit only after the last required open has happened.
def eligible_training_sessions(fit_session: int, horizon_end: int) -> np.ndarray:
    """Return training decision indices whose labels end before the fit."""
    if fit_session < 0 or horizon_end < 1:
        raise ValueError("fit session and horizon must be nonnegative")
    return np.arange(max(0, fit_session - horizon_end), dtype=int)


# Validate later-observed outcomes independently from decision-time features.
def _ranker_outcomes(inputs, dates, observed_labels, labels_recorded_on):
    if observed_labels is None:
        if labels_recorded_on is not None:
            raise ValueError("label dates require observed labels")
        y = relative_open_labels(inputs)
        label_when = np.broadcast_to(dates[:, None], y.shape)
    else:
        if labels_recorded_on is None:
            raise ValueError("observed labels require publication dates")
        y = np.asarray(observed_labels, dtype=float)
        label_when = np.asarray(labels_recorded_on, dtype="datetime64[D]")
        if y.shape != inputs.membership.shape or label_when.shape != y.shape:
            raise ValueError("observed labels and publication dates must align")
        if np.isinf(y).any() or np.any(np.isfinite(y) & np.isnat(label_when)):
            raise ValueError("observed label has no valid publication date")
        for t in range(len(dates)):
            finite = np.isfinite(y[t])
            if finite.any() and (
                t + RANKER_LABEL_END >= len(dates)
                or np.any(label_when[t, finite] < dates[t + RANKER_LABEL_END])
            ):
                raise ValueError("observed label predates its exit session")
    return y, label_when


# Freeze the fit before each calendar month and score only later sessions.
def walk_forward_ranker(
    inputs: HistoricalInputs,
    *,
    first_training_sessions: int = RANKER_MIN_SESSIONS,
    observed_labels: np.ndarray | None = None,
    labels_recorded_on: np.ndarray | None = None,
) -> Forecasts:
    """Fit monthly only on labels published before the scoring month."""
    dates, spy = validate(inputs)
    if first_training_sessions < 2:
        raise ValueError("training history is too short")
    from sklearn.ensemble import HistGradientBoostingRegressor

    x = cross_sectional_ranks(inputs)
    y, label_when = _ranker_outcomes(inputs, dates, observed_labels, labels_recorded_on)
    prediction = np.full(y.shape, np.nan)
    fit_dates = np.full(len(dates), np.datetime64("NaT", "D"))
    cutoffs = np.full(len(dates), -1, dtype=int)
    hashes: list[str] = []
    months = dates.astype("datetime64[M]")
    month_starts = np.flatnonzero(np.r_[True, months[1:] != months[:-1]])
    for start_number, start in enumerate(month_starts):
        if start < first_training_sessions:
            continue
        end = (
            month_starts[start_number + 1]
            if start_number + 1 < len(month_starts)
            else len(dates)
        )
        eligible = eligible_training_sessions(int(start), RANKER_LABEL_END)
        train_mask = (
            np.isfinite(y[eligible])
            & (label_when[eligible] < dates[start])
            & (inputs.membership[eligible] == 1)
            & np.isfinite(x[eligible]).any(axis=2)
        )
        train_mask[:, spy] = False
        if np.count_nonzero(train_mask.any(axis=1)) < first_training_sessions:
            continue
        train_x = x[eligible][train_mask]
        columns = np.isfinite(train_x).any(axis=0)
        if not columns.any():
            continue
        model = HistGradientBoostingRegressor(
            max_iter=200,
            learning_rate=0.03,
            max_leaf_nodes=31,
            min_samples_leaf=200,
            l2_regularization=0.0,
            early_stopping=False,
            random_state=0,
        )
        model.fit(train_x[:, columns], y[eligible][train_mask])
        valid = (inputs.membership[start:end] == 1) & np.isfinite(
            x[start:end][:, :, columns]
        ).any(axis=2)
        valid[:, spy] = False
        block = prediction[start:end]
        if valid.any():
            block[valid] = model.predict(x[start:end][valid][:, columns])
        fit_dates[start:end] = dates[start]
        used = eligible[train_mask.any(axis=1)]
        cutoffs[start:end] = int(used[-1] + RANKER_LABEL_END)
        digest = sha256()
        digest.update(np.ascontiguousarray(columns).tobytes())
        digest.update(np.ascontiguousarray(train_x[:, columns]).tobytes())
        digest.update(np.ascontiguousarray(y[eligible][train_mask]).tobytes())
        digest.update(pickle.dumps(model, protocol=5))
        hashes.append(f"{dates[start]}:{digest.hexdigest()}")
    return Forecasts(
        prediction,
        fit_dates,
        cutoffs,
        tuple(hashes),
        dates.copy(),
        inputs.tickers,
        inputs.evidence_basis,
    )


# Mark a crash only when a later close is more than eight percent under the
# highest QQQ close observed since the decision close.
def future_drawdown_labels(qqq_close: np.ndarray) -> np.ndarray:
    """Return the fixed 20-session crash labels, NaN while immature."""
    closes = np.asarray(qqq_close, dtype=float)
    if closes.ndim != 1:
        raise ValueError("QQQ closes must be one-dimensional")
    labels = np.full(len(closes), np.nan)
    for t in range(len(closes) - BRAKE_HORIZON):
        window = closes[t : t + BRAKE_HORIZON + 1]
        if not np.isfinite(window).all() or np.any(window <= 0):
            continue
        peaks = np.maximum.accumulate(window)
        labels[t] = float(np.min(window / peaks - 1) < -0.08)
    return labels


# Validate a crash outcome separately from the market's decision features.
def _brake_outcomes(calendar, qqq_close, observed_labels, labels_recorded_on):
    if observed_labels is None:
        if labels_recorded_on is not None:
            raise ValueError("brake label dates require observed labels")
        labels = future_drawdown_labels(qqq_close)
        label_when = calendar
    else:
        if labels_recorded_on is None:
            raise ValueError("observed brake labels require publication dates")
        labels = np.asarray(observed_labels, dtype=float)
        label_when = np.asarray(labels_recorded_on, dtype="datetime64[D]")
        if labels.shape != calendar.shape or label_when.shape != calendar.shape:
            raise ValueError("brake labels and publication dates must align")
        if np.isinf(labels).any() or np.any(np.isfinite(labels) & np.isnat(label_when)):
            raise ValueError("brake label has no valid publication date")
        for t in np.flatnonzero(np.isfinite(labels)):
            if (
                t + BRAKE_HORIZON >= len(calendar)
                or label_when[t] < calendar[t + BRAKE_HORIZON]
            ):
                raise ValueError("brake label predates its outcome session")
    return labels, label_when


# Impute from a fit's own past rows and retain missingness as model evidence.
def _brake_matrix(block, medians, mean, scale):
    missing = ~np.isfinite(block)
    filled = np.where(missing, medians, block)
    return np.concatenate(((filled - mean) / scale, missing.astype(float)), axis=1)


# Refit the same market-only risk model on matured observations every quarter.
def walk_forward_brake(
    market_features: np.ndarray,
    features_recorded_on: np.ndarray,
    dates: np.ndarray,
    qqq_close: np.ndarray,
    qqq_recorded_on: np.ndarray,
    *,
    first_training_sessions: int = BRAKE_MIN_SESSIONS,
    observed_labels: np.ndarray | None = None,
    labels_recorded_on: np.ndarray | None = None,
    evidence_basis: str = "recorded",
) -> Forecasts:
    """Return out-of-sample crash probabilities with a 20-session purge."""
    from sklearn.linear_model import LogisticRegression

    if evidence_basis not in ("recorded", "retrospective-price"):
        raise ValueError("unknown learning evidence basis")

    calendar = np.asarray(dates, dtype="datetime64[D]")
    x = np.asarray(market_features, dtype=float)
    published = np.asarray(features_recorded_on, dtype="datetime64[D]")
    close_published = np.asarray(qqq_recorded_on, dtype="datetime64[D]")
    if (
        calendar.ndim != 1
        or x.ndim != 2
        or x.shape[0] != len(calendar)
        or published.shape != x.shape
        or len(qqq_close) != len(calendar)
        or close_published.shape != calendar.shape
    ):
        raise ValueError("market features, publication dates and QQQ must align")
    if np.isnat(calendar).any() or np.any(calendar[1:] <= calendar[:-1]):
        raise ValueError("the market calendar must be strictly increasing")
    if np.any(np.isfinite(x) & (np.isnat(published) | (published > calendar[:, None]))):
        raise ValueError("market feature was not recorded by decision close")
    if np.any(
        np.isfinite(qqq_close)
        & (np.isnat(close_published) | (close_published > calendar))
    ):
        raise ValueError("QQQ close was not recorded by its session")
    labels, label_when = _brake_outcomes(
        calendar, qqq_close, observed_labels, labels_recorded_on
    )
    prediction = np.full(len(calendar), np.nan)
    fit_dates = np.full(len(calendar), np.datetime64("NaT", "D"))
    cutoffs = np.full(len(calendar), -1, dtype=int)
    hashes: list[str] = []
    for start in range(first_training_sessions, len(calendar), BRAKE_REFIT_SESSIONS):
        end = min(start + BRAKE_REFIT_SESSIONS, len(calendar))
        eligible = eligible_training_sessions(start, BRAKE_HORIZON)
        valid = (
            np.isfinite(labels[eligible])
            & (label_when[eligible] < calendar[start])
            & np.isfinite(x[eligible]).any(axis=1)
        )
        if (
            valid.sum() < first_training_sessions
            or len(np.unique(labels[eligible][valid])) < 2
        ):
            continue
        train_x = x[eligible][valid]
        columns = np.isfinite(train_x).any(axis=0)
        if not columns.any():
            continue
        selected = train_x[:, columns]
        medians = np.nanmedian(selected, axis=0)
        filled = np.where(np.isfinite(selected), selected, medians)
        mean, scale = filled.mean(axis=0), filled.std(axis=0)
        scale[scale == 0] = 1
        model = LogisticRegression(C=1.0, max_iter=300, random_state=0)
        model.fit(
            _brake_matrix(selected, medians, mean, scale), labels[eligible][valid]
        )
        score_valid = np.isfinite(x[start:end][:, columns]).any(axis=1)
        score_block = prediction[start:end]
        if score_valid.any():
            score_block[score_valid] = model.predict_proba(
                _brake_matrix(
                    x[start:end][score_valid][:, columns], medians, mean, scale
                )
            )[:, 1]
        fit_dates[start:end] = calendar[start]
        cutoffs[start:end] = int(eligible[valid][-1] + BRAKE_HORIZON)
        digest = sha256()
        digest.update(np.ascontiguousarray(columns).tobytes())
        digest.update(np.ascontiguousarray(medians).tobytes())
        digest.update(np.ascontiguousarray(filled).tobytes())
        digest.update(np.ascontiguousarray(labels[eligible][valid]).tobytes())
        digest.update(pickle.dumps(model, protocol=5))
        hashes.append(f"{calendar[start]}:{digest.hexdigest()}")
    return Forecasts(
        prediction,
        fit_dates,
        cutoffs,
        tuple(hashes),
        calendar.copy(),
        (),
        evidence_basis,
    )


# Hold the prior exposure between two predeclared probability thresholds.
def brake_scale_path(probability: np.ndarray) -> np.ndarray:
    """Return the causal 1.0 or 0.5 exposure ceiling for every session."""
    p = np.asarray(probability, dtype=float)
    if p.ndim != 1 or np.any(np.isfinite(p) & ((p < 0) | (p > 1))):
        raise ValueError("probabilities must be one-dimensional and in [0, 1]")
    out = np.ones(len(p))
    scale = 1.0
    for t, value in enumerate(p):
        if np.isfinite(value):
            if value >= 0.45:
                scale = 0.5
            elif value < 0.30:
                scale = 1.0
        out[t] = scale
    return out


# Feed the learned ranking into the existing grade, regime, volatility and
# concentration engine without changing its eligibility or its caps.
def policy_targets(
    report, forecasts: Forecasts, t: int, *, policy: str, config=None
) -> np.ndarray:
    """Return shadow target weights through the same desk risk function."""
    from dataclasses import replace

    from backend.agents.trading.desk import risk

    if forecasts.evidence_basis != "recorded":
        raise ValueError("retrospective forecasts cannot enter the desk target adapter")
    if policy not in (POLICY_RANK, POLICY_BLEND):
        raise ValueError("unknown learned shadow policy")
    panel = report.panel
    if (
        forecasts.values.shape != report.scores.shape
        or len(panel.dates) != len(forecasts.fit_session)
        or forecasts.tickers != panel.tickers
        or not np.array_equal(forecasts.dates, panel.dates)
    ):
        raise ValueError("forecasts must align with the desk report")
    if t < 0 or t >= len(panel.dates):
        raise IndexError("decision session outside the desk report")
    if np.isnat(forecasts.fit_session[t]) or forecasts.last_training_label_end[t] >= t:
        raise ValueError("no purged walk-forward fit is available at this session")
    scores = forecasts.values[t].copy()
    if policy == POLICY_BLEND:
        rule = np.asarray(report.scores[t], dtype=float)
        common = np.isfinite(rule) & np.isfinite(scores)
        if common.sum() < 2:
            return np.zeros(len(panel.tickers))
        scores[common] = 0.5 * _vector_ranks(scores[common]) + 0.5 * _vector_ranks(
            rule[common]
        )
        scores[~common] = np.nan
    window = replace(
        panel,
        dates=panel.dates[: t + 1],
        open=panel.open[: t + 1],
        high=panel.high[: t + 1],
        low=panel.low[: t + 1],
        close=panel.close[: t + 1],
        adj_close=panel.adj_close[: t + 1],
        volume=panel.volume[: t + 1],
    )
    _, target = risk.desk_targets(
        scores,
        report.graded.grades[t],
        window,
        report.regime.states[t],
        config or risk.BOOK_CONFIG,
    )
    target[panel.index(panel.benchmark)] = 0.0
    return target


# Give a blended score the same unit interval scale for each input ranking.
def _vector_ranks(values: np.ndarray) -> np.ndarray:
    """Return midranks on [0, 1] for one finite cross section."""
    order = np.argsort(values, kind="stable")
    sorted_values = values[order]
    out = np.empty(len(values))
    left = 0
    while left < len(values):
        right = left + 1
        while right < len(values) and sorted_values[right] == sorted_values[left]:
            right += 1
        out[order[left:right]] = ((left + right - 1) / 2) / (len(values) - 1)
        left = right
    return out


# Offer the same target function to the simulator's standard allocator hook;
# pre-fit sessions remain in cash rather than receiving a hindsight ranking.
def allocator_for(forecasts: Forecasts, policy: str):
    """Return a shadow allocator compatible with `simulate.run`."""
    if policy not in (POLICY_RANK, POLICY_BLEND):
        raise ValueError("unknown learned shadow policy")

    # Size one session using only its already-fitted out-of-sample forecast.
    def allocate(report, panel, config, t: int) -> np.ndarray:
        """Return the shared desk target or cash before the first fit."""
        if panel.tickers != forecasts.tickers or not np.array_equal(
            panel.dates, forecasts.dates
        ):
            raise ValueError("forecast and simulator calendars must align")
        if (
            np.isnat(forecasts.fit_session[t])
            or forecasts.last_training_label_end[t] >= t
        ):
            return np.zeros(len(panel.tickers))
        return policy_targets(report, forecasts, t, policy=policy, config=config)

    return allocate
