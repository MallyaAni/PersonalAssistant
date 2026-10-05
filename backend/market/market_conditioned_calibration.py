"""One dated, past-only market-conditioned log-return calibration design.

This numerical component does not select a broker, simulate a portfolio or
claim calibrated probabilities. Funded and published-reader integration is
separate acceptance, required before this can affect any recommendation.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from backend.market import calendar
from backend.market import daily_arithmetic_bridge as reference

POLICY = "market-conditioned-holding/1-research"
PROTOCOL = "docs/research/market-conditioned-holding-plan-2026-10-05.md"
CONTEXT = ("spy_return_20", "spy_drawdown_252", "spy_volatility_20", "breadth_20")


# Refuse impossible market inputs without imposing a trading threshold.
def _context(values):
    values = np.asarray(values)
    if (
        values.ndim != 2
        or values.shape[1] != len(CONTEXT)
        or values.dtype.kind not in "fiu"
        or not np.isfinite(values).all()
        or np.any(values[:, 1] < -1)
        or np.any(values[:, 1] > 0)
        or np.any(values[:, 2] < 0)
        or np.any(values[:, 3] < 0)
        or np.any(values[:, 3] > 1)
    ):
        raise ValueError("Finite possible declared market context required")
    return values.astype(np.float64, copy=True)


# Keep learned coefficients, identified directions and provenance detached from callers.
@dataclass(frozen=True)
class MarketLogFit:
    center: np.ndarray
    scale: np.ndarray
    coefficients: np.ndarray
    directions: np.ndarray
    singular_values: np.ndarray
    observations: int
    defaults: int
    rank: int
    fit_date: str
    cutoff: str
    selected: np.ndarray
    dates_sha256: str
    endpoints_sha256: str
    forecasts_sha256: str
    outcomes_sha256: str
    context_sha256: str
    maximum_endpoint: str

    # Predict within identified training directions with leverage uncertainty.
    def predict(self, forecast, context):
        if (
            isinstance(forecast, (bool, np.bool_))
            or not isinstance(forecast, (int, float, np.integer, np.floating))
            or not np.isfinite(forecast)
            or forecast <= -1
        ):
            raise ValueError("Possible finite current forecast required")
        market = _context(np.asarray(context)[None])[0]
        raw = np.r_[np.log1p(forecast), market]
        active = self.scale > 0
        tolerance = 64 * np.finfo(float).eps
        if np.any(
            np.abs(raw[~active] - self.center[~active])
            > tolerance * np.maximum(1, np.abs(self.center[~active]))
        ):
            raise ValueError("Current context is outside identified training span")
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            z = np.zeros(len(raw))
            z[active] = (raw[active] - self.center[active]) / self.scale[active]
            query = np.r_[1.0, z]
            coordinates = self.directions @ query
            remainder = query - self.directions.T @ coordinates
        if not all(np.isfinite(v).all() for v in (query, coordinates, remainder)):
            raise ValueError("Unsupported market calibration arithmetic")
        if np.max(np.abs(remainder)) > (
            tolerance * len(query) * max(1, np.max(np.abs(query)))
        ):
            raise ValueError("Current context is outside identified training span")
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            mean = query @ self.coefficients
            leverage = np.sum((coordinates / self.singular_values) ** 2)
            adjustment = np.sqrt(
                self.observations / (self.observations - self.rank) * (1 + leverage)
            )
        if not np.isfinite([mean, adjustment]).all():
            raise ValueError("Unsupported market calibration arithmetic")
        return float(mean), float(adjustment)

    # Return fresh serializable evidence without exposing mutable model buffers.
    def receipt(self):
        root = Path(__file__).resolve().parents[2]
        return {
            "policy": POLICY,
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "protocol_sha256": hashlib.sha256(
                (root / PROTOCOL).read_bytes()
            ).hexdigest(),
            "context": list(CONTEXT),
            "fit_date": self.fit_date,
            "label_end_before": self.cutoff,
            "selected_indices": self.selected.tolist(),
            "observations": self.observations,
            "defaults": self.defaults,
            "rank": self.rank,
            "maximum_endpoint": self.maximum_endpoint,
            "row_hashes": {
                key: getattr(self, key + "_sha256")
                for key in ("dates", "endpoints", "forecasts", "outcomes", "context")
            },
            "coefficients": self.coefficients.tolist(),
            "center": self.center.tolist(),
            "scale": self.scale.tolist(),
            "directions": self.directions.tolist(),
            "singular_values": self.singular_values.tolist(),
            "confidence_guarantee": False,
            "adoption_eligible": False,
        }


# Select original mature dates inside the fixed month/window before fitting any values.
def fit_market_log(
    dates, endpoints, forecasts, outcomes, context, support, *, fit_date
):
    dates, endpoints, forecasts, outcomes, context, support = map(
        np.asarray, (dates, endpoints, forecasts, outcomes, context, support)
    )
    if (
        dates.ndim != 1
        or not len(dates)
        or dates.dtype != np.dtype("datetime64[D]")
        or endpoints.dtype != dates.dtype
        or endpoints.shape != dates.shape
        or np.isnat(dates).any()
        or np.any(dates[1:] <= dates[:-1])
        or forecasts.shape != dates.shape
        or outcomes.shape != dates.shape
        or any(v.dtype.kind not in "fiu" for v in (forecasts, outcomes, context))
        or context.shape != (len(dates), len(CONTEXT))
        or support.shape != dates.shape
        or support.dtype != np.dtype("bool")
        or not isinstance(fit_date, np.datetime64)
        or fit_date.dtype != dates.dtype
        or np.isnat(fit_date)
    ):
        raise ValueError("Explicit aligned daily calibration inputs required")
    years, exchange = calendar.reviewed_sessions()
    whole = np.arange(dates[0], dates[-1] + np.timedelta64(1, "D"))
    if (
        any(day.astype(object).year not in years for day in whole)
        or fit_date.astype(object).year not in years
        or fit_date > np.busday_offset(dates[-1], 1, busdaycal=exchange)
        or not np.array_equal(dates, whole[np.is_busday(whole, busdaycal=exchange)])
        or fit_date
        != np.busday_offset(
            fit_date.astype("datetime64[M]").astype("datetime64[D]"),
            0,
            roll="forward",
            busdaycal=exchange,
        )
    ):
        raise ValueError("Complete reviewed calendar and monthly opening required")
    first = int(np.searchsorted(dates, fit_date))
    cutoff = min(fit_date, reference.FREEZE)
    candidates = np.arange(max(0, first - reference.MAX_DAYS), first)
    expected = np.busday_offset(dates[candidates], 2, busdaycal=exchange)
    admitted = support[candidates] & (expected < cutoff)
    selected = candidates[admitted]
    if not np.array_equal(endpoints[selected], expected[admitted]):
        raise ValueError("Exact D+2 holding outcome endpoints required")
    if len(selected) < 252:
        raise ValueError("At least 252 mature original calibration dates required")
    raw, observed = forecasts[selected], outcomes[selected]
    market = _context(context[selected])
    if (
        not np.isfinite(raw).all()
        or not np.isfinite(observed).all()
        or np.any(raw <= -1)
        or np.any(observed < -1)
    ):
        raise ValueError(
            "Admitted calibration rows cannot contain missing or impossible values"
        )
    parameters = _regression(raw, observed, market)
    selected.flags.writeable = False
    hashes = [
        reference._hash(v)
        for v in (dates[selected], endpoints[selected], raw, observed, market)
    ]
    return MarketLogFit(
        *parameters,
        str(fit_date),
        str(cutoff),
        selected,
        *hashes,
        str(endpoints[selected].max()),
    )


# Solve the identified log-return design without silently clipping or regularizing it.
def _regression(raw, observed, market):
    default = observed == -1
    predictors = np.c_[np.log1p(raw[~default]), market[~default]]
    target = np.log1p(observed[~default])
    if len(target) < 3:
        raise ValueError("Insufficient non-default calibration observations")
    with np.errstate(over="ignore", invalid="ignore"):
        center = predictors.mean(axis=0)
        scale = np.max(np.abs(predictors - center), axis=0)
    if not np.isfinite(center).all() or not np.isfinite(scale).all():
        raise ValueError("Unsupported fitted market calibration arithmetic")
    constant = np.all(predictors == predictors[0], axis=0)
    scale[constant] = 0
    design = np.zeros((len(target), 1 + predictors.shape[1]))
    design[:, 0] = 1
    active = scale > 0
    design[:, 1 + np.flatnonzero(active)] = (
        predictors[:, active] - center[active]
    ) / scale[active]
    try:
        left, singular, directions = np.linalg.svd(design, full_matrices=False)
    except np.linalg.LinAlgError as exc:
        raise ValueError("Unsupported fitted market calibration arithmetic") from exc
    retained = singular > np.finfo(float).eps * max(design.shape) * singular[0]
    rank = int(retained.sum())
    if len(target) <= rank:
        raise ValueError("Positive residual degrees of freedom required")
    singular, directions = singular[retained], directions[retained]
    coefficients = directions.T @ ((left[:, retained].T @ target) / singular)
    if not all(
        np.isfinite(a).all()
        for a in (center, scale, coefficients, singular, directions)
    ):
        raise ValueError("Unsupported fitted market calibration arithmetic")
    arrays = (center, scale, coefficients, directions, singular)
    for value in arrays:
        value.flags.writeable = False
    return (*arrays, len(target), int(default.sum()), rank)
