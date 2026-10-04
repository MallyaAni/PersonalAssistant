"""Restore authenticated frozen residual distributions without recalibration.

The caller authenticates original archive and receipt bytes. This pure loader
checks their typed-array relationships, original sample selection and maturity.
It neither fits estimators nor regenerates probability diagnostics.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

import numpy as np

from backend.market import probabilistic_execution as model
from backend.market.daily_arithmetic_bridge import _hash


# Preserve verified samples and current support for causal execution decisions.
@dataclass
class SavedDistributions:
    dates: np.ndarray
    symbols: tuple[str, ...]
    means: np.ndarray
    scales: np.ndarray
    score_mask: np.ndarray
    verification: dict
    _context: tuple = field(repr=False)
    _cache_month: str | None = field(default=None, repr=False)
    _cache: dict = field(default_factory=dict, repr=False)

    # Return only an originally available distribution at the requested observation.
    def provider(self, day, clock, stock):
        indices = (day, clock, stock)
        if any(
            isinstance(value, (bool, np.bool_))
            or not isinstance(value, (int, np.integer))
            or not 0 <= value < bound
            for value, bound in zip(indices, self.means.shape, strict=True)
        ):
            raise ValueError("Valid integer day, clock and stock indices required")
        if not self.score_mask[day, clock, stock]:
            return None
        month = str(self.dates[day].astype("datetime64[M]"))
        if month != self._cache_month:
            self._cache = {}
            restored, _, _, _ = _samples(*self._context, retain_month=month)
            self._cache = restored[month]
            self._cache_month = month
        sample = self._cache.get(self.symbols[stock])
        if sample is None:
            return None
        return model.Distribution(
            float(self.means[day, clock, stock]),
            float(self.scales[day, clock, stock]),
            sample.residuals,
            sample.weights,
        )


# Refuse a changed relationship rather than silently reconstructing another cohort.
def _require(condition, message):
    if not condition:
        raise ValueError(message)


# Bind original typed inputs, source semantics and recorded calibration clocks.
def _identity(
    dates,
    symbols,
    means,
    second,
    labels,
    valid,
    endpoints,
    manifest,
    data_as_of,
    horizon,
):
    expected = model._identity(
        dates, symbols, means, second, labels, valid, endpoints, data_as_of, horizon
    )
    saved = manifest.get("identity", {})
    for key, value in expected.items():
        if key != "numpy":
            _require(
                saved.get(key) == value, f"Original manifest identity differs: {key}"
            )
    _require(isinstance(saved.get("numpy"), str), "Original runtime identity required")
    return saved


# Require original saved forecast representation before deriving its support mask.
def _saved_support(probability, quantiles, shape, score, causal, manifest):
    probability, quantiles = np.asarray(probability), np.asarray(quantiles)
    _require(
        probability.shape == shape
        and probability.dtype == np.float64
        and quantiles.shape == (*shape, 3)
        and quantiles.dtype == np.float64,
        "Original float64 probability and quantile grids required",
    )
    _require(
        not np.isinf(probability).any() and not np.isinf(quantiles).any(),
        "Saved probabilities and quantiles must be finite or missing",
    )
    finite_p = np.isfinite(probability)
    finite_q = np.isfinite(quantiles).all(axis=-1)
    _require(
        np.all((probability[finite_p] >= 0) & (probability[finite_p] <= 1))
        and np.all(quantiles[finite_q, 0] <= quantiles[finite_q, 1])
        and np.all(quantiles[finite_q, 1] <= quantiles[finite_q, 2]),
        "Saved probability bounds or quantile ordering differ",
    )
    available = score & finite_p & finite_q
    _require(
        not np.any(finite_p & ~available), "Saved forecast outside original support"
    )
    for name, array in (
        ("probability_positive", probability),
        ("quantiles", quantiles),
        ("score_mask", available),
        ("causal_mask", causal),
    ):
        _require(
            manifest.get("arrays", {}).get(name) == _hash(array),
            f"Saved array hash differs: {name}",
        )
    return available.copy()


# Reconstruct only original sample rows and authenticate every recorded byte hash.
def _samples(
    dates,
    names,
    means,
    scales,
    outcomes,
    score,
    ends,
    completion,
    as_of,
    sessions,
    manifest,
    *,
    retain_month=None,
):
    months = dates.astype("datetime64[M]")
    receipts = manifest.get("months", [])
    _require(
        [row.get("month") for row in receipts] == [str(m) for m in np.unique(months)],
        "Complete original monthly receipt schedule required",
    )
    samples, available_count, total_rows, available_names = {}, 0, 0, {}
    for row in receipts:
        if retain_month is not None and row["month"] != retain_month:
            continue
        month = np.datetime64(row["month"], "M")
        first = np.busday_offset(
            month.astype("datetime64[D]"), 0, roll="forward", busdaycal=sessions
        )
        stop = int(np.searchsorted(dates, first))
        lower, cutoff = max(0, stop - model.MAX_DAYS), min(first, model.FREEZE)
        _require(
            row.get("fit_date") == str(first)
            and row.get("cutoff_exclusive") == str(cutoff)
            and row.get("lookback_first_index") == lower,
            "Original monthly maturity or lookback differs",
        )
        stocks = row.get("stocks", [])
        _require(
            [r.get("symbol") for r in stocks] == list(names),
            "Complete ordered stock receipts required",
        )
        train_days = (np.arange(len(dates)) >= lower) & (np.arange(len(dates)) < stop)
        mature = (ends < cutoff) & (completion <= as_of) & ~np.isnat(completion)
        train = score & np.isfinite(outcomes) & mature & train_days[:, None, None]
        samples[str(month)] = {}
        available_names[str(month)] = set()
        for stock, receipt in enumerate(stocks):
            day, clock = np.nonzero(train[:, :, stock])
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                residual = (
                    outcomes[day, clock, stock] - means[day, clock, stock]
                ) / scales[day, clock, stock]
            finite = np.isfinite(residual)
            day, clock, residual = day[finite], clock[finite], residual[finite]
            unique, counts = np.unique(day, return_counts=True)
            weights = (
                1.0 / counts[np.searchsorted(unique, day)]
                if len(day)
                else np.array([], dtype=np.float64)
            )
            status = (
                "excluded_benchmark"
                if names[stock] in ("SPY", "QQQ")
                else "available"
                if len(unique) >= model.MIN_DAYS
                else "insufficient_mature_sessions"
            )
            endpoint = str(ends[day, clock, stock].max()) if len(day) else None
            _require(
                receipt.get("status") == status
                and receipt.get("training_days") == len(unique)
                and receipt.get("training_rows") == len(day)
                and receipt.get("nonfinite_residual_rows") == int((~finite).sum())
                and receipt.get("maximum_endpoint") == endpoint,
                "Original residual sample count, status or endpoint differs",
            )
            for key, value in (
                ("day_indices", day),
                ("clock_indices", clock),
                ("residuals", residual),
                ("weights", weights),
            ):
                _require(
                    receipt.get("hashes", {}).get(key) == _hash(value),
                    f"Original residual sample hash differs: {key}",
                )
            total_rows += len(day)
            if status == "available":
                available_names[str(month)].add(names[stock])
                if retain_month is not None:
                    for array in (residual, weights, day, clock):
                        array.flags.writeable = False
                    samples[str(month)][names[stock]] = model.ResidualSample(
                        residual, weights, day, clock
                    )
                available_count += 1
    return samples, available_count, total_rows, available_names


# Restore fixed distributions from original manifests without probability regeneration.
def load_saved(
    dates,
    symbols,
    means,
    second_moments,
    labels,
    valid,
    outcome_end_dates,
    manifest,
    *,
    saved_probability,
    saved_quantiles,
    data_as_of,
    horizon,
):
    _require(horizon == model.HORIZON, "Matching one-decision horizon required")
    identity = _identity(
        dates,
        symbols,
        means,
        second_moments,
        labels,
        valid,
        outcome_end_dates,
        manifest,
        data_as_of,
        horizon,
    )
    (
        dates,
        names,
        means,
        second,
        outcomes,
        causal,
        ends,
        completion,
        observed,
        supported,
        as_of,
        sessions,
    ) = model._validate(
        dates,
        symbols,
        means,
        second_moments,
        labels,
        valid,
        outcome_end_dates,
        data_as_of,
    )
    with np.errstate(over="ignore", invalid="ignore"):
        variance = second - means * means
    moment_valid = (
        np.isfinite(means) & np.isfinite(variance) & (second >= 0) & (variance > 0)
    )
    scales = np.full(means.shape, np.nan)
    scales[moment_valid] = np.sqrt(variance[moment_valid])
    causal_support = (
        causal
        & supported[:, :, None]
        & (observed[:, :, None] <= as_of)
        & ~np.isin(names, ("SPY", "QQQ"))[None, None, :]
    )
    score = causal_support & moment_valid
    available = _saved_support(
        saved_probability, saved_quantiles, means.shape, score, causal_support, manifest
    )
    _require(
        manifest.get("causal_opportunities") == int(causal_support.sum())
        and manifest.get("available") == int(available.sum())
        and manifest.get("unavailable") == int((causal_support & ~available).sum())
        and manifest.get("invalid_moment_rows")
        == int((causal_support & ~moment_valid).sum())
        and manifest.get("confidence_guarantee") is False,
        "Original opportunity and availability counts differ",
    )
    context = (
        dates,
        names,
        means,
        scales,
        outcomes,
        score,
        ends,
        completion,
        as_of,
        sessions,
        deepcopy(manifest),
    )
    samples, count, rows, available_names = _samples(*context)
    for month in np.unique(dates.astype("datetime64[M]")):
        month_days = dates.astype("datetime64[M]") == month
        for stock, symbol in enumerate(names):
            _require(
                not available[month_days, :, stock].any()
                or symbol in available_names[str(month)],
                "Available forecast has no authenticated residual sample",
            )
    for array in (dates, means, scales, available, outcomes, score, completion):
        array.flags.writeable = False
    return SavedDistributions(
        dates,
        names,
        means,
        scales,
        available,
        {
            "status": "VERIFIED_SAVED_DISTRIBUTIONS",
            "months": len(samples),
            "available_stock_month_samples": count,
            "authenticated_sample_rows": rows,
            "available_observations": int(available.sum()),
            "original_numpy": identity["numpy"],
            "restoration_numpy": np.__version__,
            "no_refit_or_recalibration": True,
            "caller_authenticates_original_receipt_and_archive_bytes": True,
            "sample_cache": "one_month_only",
        },
        context,
    )
