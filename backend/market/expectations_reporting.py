"""Reporting-only evidence for the legacy earnings-expectations pipeline.

This preserves the legacy first-filed/fuzzy-quarter selector, not verified SEC
units, fiscal periods, historical membership or original-response provenance.
Eligibility requires positive revenue operands and a finite legacy log quotient.
It never supplies or changes a model feature, target, fit or allocation.
"""

from dataclasses import dataclass
from datetime import date, datetime

import numpy as np

from backend.market import edgar

VERSION = "legacy-growth-computability/1"


@dataclass(frozen=True)
class GrowthEvidence:
    """An aligned, read-only witness beside the existing dataset rows."""

    latest_revenue: np.ndarray
    prior_revenue: np.ndarray
    usable: np.ndarray
    reason: tuple[str, ...]
    tickers: tuple[str, ...]
    feature_dates: tuple[date, ...]
    source_times: tuple[datetime | None, ...]
    source_filed: tuple[date | None, ...]
    schema: str = VERSION


# Distinguish unavailable operands, the positive-revenue domain and failed arithmetic.
def _growth_reason(current: float, prior: float) -> str:
    if np.isnan(current):
        return "missing_current"
    if not np.isfinite(current):
        return "nonfinite_current"
    if np.isnan(prior):
        return "missing_prior"
    if not np.isfinite(prior):
        return "nonfinite_prior"
    if current <= 0:
        return "nonpositive_current"
    if prior <= 0:
        return "nonpositive_prior"
    with np.errstate(all="ignore"):
        growth = np.log(np.divide(current, prior))
    return "available" if np.isfinite(growth) else "nonfinite_legacy_growth"


# Observe the same strict pre-session operands as the producer without changing it.
def growth_evidence(panel, records, meta) -> GrowthEvidence:
    count = len(meta)
    latest = np.full(count, np.nan)
    prior = np.full(count, np.nan)
    reasons, tickers, feature_dates, source_times, source_filed = [], [], [], [], []
    known = {}
    for i, row in enumerate(meta):
        if len(row) < 5:
            raise ValueError("growth evidence requires explicit feature indices")
        column, feature = row[0], row[4]
        if any(
            isinstance(value, (bool, np.bool_))
            or not isinstance(value, (int, np.integer))
            for value in (column, feature)
        ):
            raise ValueError("growth evidence indices must be integers")
        if not 0 <= column < len(panel.tickers) or not 0 <= feature < len(panel.dates):
            raise ValueError("growth evidence index is outside the supplied panel")
        day = panel.dates[feature].astype("datetime64[D]")
        if np.isnat(day):
            raise ValueError("growth evidence requires a dated feature session")
        ticker = panel.tickers[column]
        record = records.get(ticker)
        if record is not None and record.ticker != ticker:
            raise ValueError("growth evidence record does not match its ticker")
        tickers.append(ticker)
        feature_dates.append(day.astype(object))
        source_times.append(record.source_time if record is not None else None)
        if record is None:
            source_filed.append(None)
        else:
            if ticker not in known:
                known[ticker] = edgar._known_quarters(
                    record.facts,
                    "revenue",
                    panel.dates,
                    strict_before_session=True,
                )
            values, _first_visible, filed = known[ticker]
            latest[i], prior[i] = values[0][feature], values[4][feature]
            source_filed.append(
                None if np.isnat(filed[feature]) else filed[feature].astype(object)
            )
        reasons.append(_growth_reason(latest[i], prior[i]))
    usable = np.array([reason == "available" for reason in reasons], dtype=bool)
    for array in (latest, prior, usable):
        array.flags.writeable = False
    return GrowthEvidence(
        latest,
        prior,
        usable,
        tuple(reasons),
        tuple(tickers),
        tuple(feature_dates),
        tuple(source_times),
        tuple(source_filed),
    )


# Keep both forecasts and their target on one finite, identically shaped cohort.
def common_forecast_mask(expected, naive, target) -> np.ndarray:
    arrays = tuple(np.asarray(values) for values in (expected, naive, target))
    if any(values.ndim != 1 or values.shape != arrays[0].shape for values in arrays):
        raise ValueError("forecast comparisons require aligned one-dimensional arrays")
    return np.isfinite(arrays[0]) & np.isfinite(arrays[1]) & np.isfinite(arrays[2])


# Compute finite-cohort accuracy without inventing correlation for constant samples.
def forecast_metrics(prediction, target) -> tuple[int, float | None, float | None]:
    prediction, target = (
        np.asarray(prediction, dtype=float),
        np.asarray(target, dtype=float),
    )
    common_forecast_mask(prediction, prediction, target)
    if not np.isfinite(prediction).all() or not np.isfinite(target).all():
        raise ValueError("accuracy metrics require a finite selected cohort")
    count = len(target)
    if not count:
        return 0, None, None
    with np.errstate(all="ignore"):
        errors = np.abs(prediction - target)
        scale = float(errors.max())
        if np.isfinite(scale):
            mae = float(np.mean(errors / scale) * scale) if scale else 0.0
        else:
            # An individual difference can overflow while its average still fits.
            scale = max(np.max(np.abs(prediction)), np.max(np.abs(target)))
            mae = float(np.mean(np.abs(prediction / scale - target / scale)) * scale)
    if not np.isfinite(mae):
        mae = None
    if count < 2 or np.all(prediction == prediction[0]) or np.all(target == target[0]):
        return count, mae, None
    # Anchor before scaling to retain small variation around a large common offset.
    centered = []
    for values in (prediction, target):
        with np.errstate(all="ignore"):
            differences = values - values[0]
            if not np.isfinite(differences).all():
                bounded = values / np.max(np.abs(values))
                differences = bounded - bounded[0]
            scaled = differences / np.max(np.abs(differences))
        centered.append(scaled - scaled.mean())
    a, b = centered
    with np.errstate(all="ignore"):
        corr = float((a @ b) / (np.linalg.norm(a) * np.linalg.norm(b)))
    return count, mae, float(np.clip(corr, -1, 1)) if np.isfinite(corr) else None
