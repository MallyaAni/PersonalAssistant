"""Past-only execution residual distributions; estimates are not confidence guarantees.

The caller authenticates genuinely OOS forecasts and their price basis. This
module binds supplied bytes but cannot establish OOS provenance from arrays.
Date endpoints conservatively become known at exchange close with explicit D or
D,C,S shape. The caller authenticates actual observation and outcome clocks.
Costs are basis points and quantities are funded fractions of current NAV.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from backend.market import calendar as exchange
from backend.market.daily_arithmetic_bridge import _as_of, _hash

HORIZON = "one_decision_log_price_advantage"
POLICY = "probabilistic-execution/1-research"
MIN_DAYS = 252
MAX_DAYS = 756
FREEZE = np.datetime64("2026-08-17", "D")
PROTOCOL = "docs/research/probabilistic-execution-plan-2026-10-04.md"


# Store each stock/month's evidence once, with original row identities.
@dataclass(frozen=True)
class ResidualSample:
    residuals: np.ndarray
    weights: np.ndarray
    day_indices: np.ndarray
    clock_indices: np.ndarray


# Describe a shifted empirical forecast without duplicating its residual evidence.
@dataclass(frozen=True)
class Distribution:
    mean: float
    scale: float
    residuals: np.ndarray
    weights: np.ndarray
    horizon: str = HORIZON


# Preserve an explicit unavailable or funded decision and its expected utility.
@dataclass(frozen=True)
class Decision:
    state: str
    expected_log_utility: float | None = None
    reason: str = ""


# Return probabilities, quantiles and shared evidence for independent artifact replay.
@dataclass(frozen=True)
class Calibration:
    probability_positive: np.ndarray
    quantiles: np.ndarray
    means: np.ndarray
    scales: np.ndarray
    score_mask: np.ndarray
    causal_mask: np.ndarray
    dates: np.ndarray
    symbols: tuple[str, ...]
    samples: dict
    manifest: dict

    # Resolve a single causal forecast into its shared stock/month distribution.
    def distribution(self, day, clock, stock):
        if not self.score_mask[day, clock, stock]:
            return None
        month = str(self.dates[day].astype("datetime64[M]"))
        sample = self.samples.get(month, {}).get(self.symbols[stock])
        if sample is None:
            return None
        return Distribution(
            float(self.means[day, clock, stock]),
            float(self.scales[day, clock, stock]),
            sample.residuals,
            sample.weights,
        )


# Evaluate inverse weighted empirical CDFs without interpolating invented outcomes.
def weighted_quantiles(values, weights, levels=(0.1, 0.5, 0.9)):
    values, weights = _sample(values, weights)
    levels = np.asarray(levels, dtype=np.float64)
    if (
        levels.ndim != 1
        or not np.isfinite(levels).all()
        or np.any((levels < 0) | (levels > 1))
    ):
        raise ValueError("Finite probability levels from zero through one required")
    order = np.argsort(values, kind="stable")
    cumulative = np.cumsum(weights[order])
    positions = np.searchsorted(cumulative, levels * cumulative[-1], side="left")
    return values[order[np.minimum(positions, len(order) - 1)]]


# Refuse malformed empirical distributions instead of repairing sample weights.
def _sample(values, weights):
    values, weights = np.asarray(values), np.asarray(weights)
    if (
        values.ndim != 1
        or not len(values)
        or weights.shape != values.shape
        or values.dtype.kind not in "fiu"
        or weights.dtype.kind not in "fiu"
        or not np.isfinite(values).all()
        or not np.isfinite(weights).all()
        or np.any(weights <= 0)
    ):
        raise ValueError("Finite nonempty outcomes and positive weights required")
    values, weights = (
        values.astype(np.float64, copy=False),
        weights.astype(np.float64, copy=False),
    )
    with np.errstate(over="ignore"):
        total = weights.sum()
    if not np.isfinite(total) or total <= 0:
        raise ValueError("Finite positive total sample weight required")
    return values, weights


# Convert a New York completion instant to an unambiguous UTC numeric clock.
def _utc(instant):
    return np.datetime64(instant.astimezone(UTC).replace(tzinfo=None), "ns")


# Bind reviewed sessions and require both price proxies before the regular close.
def _clocks(dates, count):
    years, sessions = exchange.reviewed_sessions()
    if any(day.astype(object).year not in years for day in dates):
        raise ValueError("Reviewed exchange years required")
    expected = np.arange(dates[0], dates[-1] + np.timedelta64(1, "D"))
    expected = expected[np.is_busday(expected, busdaycal=sessions)]
    if not np.array_equal(dates, expected):
        raise ValueError("Complete regular exchange-session calendar required")
    observations = np.empty((len(dates), count), dtype="datetime64[ns]")
    supported = np.zeros((len(dates), count), dtype=bool)
    closes = np.empty(len(dates), dtype="datetime64[ns]")
    for index, value in enumerate(dates):
        day = value.astype(object)
        opening = datetime.combine(day, exchange.REGULAR_OPEN, exchange.NEW_YORK)
        closing = datetime.combine(day, exchange.session_close(day), exchange.NEW_YORK)
        closes[index] = _utc(closing)
        for clock in range(count):
            instant = opening + timedelta(minutes=15 * (clock + 1))
            observations[index, clock] = _utc(instant)
            supported[index, clock] = (
                instant + timedelta(minutes=15) < closing and clock < 23
            )
    return observations, supported, closes, sessions


# Validate supplied typed grids while keeping missing outcomes separate from support.
def _validate(dates, symbols, means, second, labels, valid, endpoints, data_as_of):
    dates = np.asarray(dates)
    symbols = tuple(symbols)
    if (
        dates.ndim != 1
        or not len(dates)
        or dates.dtype != np.dtype("datetime64[D]")
        or np.isnat(dates).any()
        or np.any(dates[1:] <= dates[:-1])
        or not symbols
        or len(set(symbols)) != len(symbols)
        or any(not isinstance(name, str) or not name for name in symbols)
    ):
        raise ValueError("Ordered day dates and unique nonempty symbols required")
    arrays = [np.asarray(value) for value in (means, second, labels)]
    shape = arrays[0].shape
    if (
        len(shape) != 3
        or shape[0] != len(dates)
        or shape[2] != len(symbols)
        or not 1 <= shape[1] <= 25
    ):
        raise ValueError("Aligned D,C,S forecasts with one through 25 clocks required")
    if any(
        value.shape != shape or value.dtype.kind not in "fiu" or np.isinf(value).any()
        for value in arrays
    ):
        raise ValueError("Aligned numeric finite-or-missing arrays required")
    valid = np.asarray(valid)
    if valid.shape != shape or valid.dtype.kind != "b":
        raise ValueError("Aligned explicit boolean causal validity required")
    observed, supported, closes, sessions = _clocks(dates, shape[1])
    endpoint_days, completion = _endpoints(
        endpoints, shape, observed, supported, sessions
    )
    as_of = _as_of(data_as_of)
    return (
        dates.copy(),
        symbols,
        *[value.astype(np.float64, copy=True) for value in arrays],
        valid.copy(),
        endpoint_days,
        completion,
        observed,
        supported,
        _utc(as_of),
        sessions,
    )


# Interpret explicit endpoints without inventing original availability clocks.
def _endpoints(endpoints, shape, observed, supported, sessions):
    endpoints = np.asarray(endpoints)
    if endpoints.shape not in (shape, (shape[0],)) or endpoints.dtype != np.dtype(
        "datetime64[D]"
    ):
        raise ValueError("Explicit D or D,C,S day endpoints required")
    endpoint_grid = (
        np.broadcast_to(endpoints[:, None, None], shape)
        if endpoints.ndim == 1
        else endpoints
    )
    unique, inverse = np.unique(endpoint_grid, return_inverse=True)
    mapped = np.full(len(unique), np.datetime64("NaT", "ns"))
    for index, value in enumerate(unique):
        if np.isnat(value):
            continue
        day = value.astype(object)
        years, _ = exchange.reviewed_sessions()
        if day.year not in years or not np.is_busday(value, busdaycal=sessions):
            raise ValueError("Outcome dates must be reviewed exchange sessions")
        mapped[index] = _utc(
            datetime.combine(day, exchange.session_close(day), exchange.NEW_YORK)
        )
    completion = mapped[inverse].reshape(shape)
    endpoint_days = endpoint_grid
    known = ~np.isnat(completion)
    if np.any(known & supported[:, :, None] & (completion < observed[:, :, None])):
        raise ValueError("Outcome completion cannot precede its observation")
    return endpoint_days, completion


# Preserve protocol, source, clock convention and every supplied typed input identity.
def _identity(
    dates, symbols, means, second, labels, valid, endpoints, data_as_of, horizon
):
    root = Path(__file__).resolve().parents[2]
    paths = [
        Path(__file__),
        root / PROTOCOL,
        Path(exchange.__file__),
        root / "backend/market/daily_arithmetic_bridge.py",
        exchange.HISTORICAL_SESSIONS_PATH,
        exchange.HOLIDAYS_PATH,
        exchange.EARLY_CLOSES_PATH,
    ]
    return {
        "policy": POLICY,
        "horizon": horizon,
        "numpy": np.__version__,
        "minimum_days": MIN_DAYS,
        "maximum_days": MAX_DAYS,
        "freeze": str(FREEZE),
        "clock": "regular_open_plus_15_minutes_times_clock_plus_one",
        "supported_clocks": list(range(23)),
        "excluded_symbols": ["SPY", "QQQ"],
        "date_endpoints_known": "scheduled_exchange_close",
        "data_as_of": _as_of(data_as_of).isoformat(),
        "inputs": {
            name: _hash(value)
            for name, value in zip(
                (
                    "dates",
                    "symbols",
                    "means",
                    "second_moments",
                    "labels",
                    "valid",
                    "outcome_end_dates",
                ),
                (dates, np.asarray(symbols), means, second, labels, valid, endpoints),
                strict=True,
            )
        },
        "sources": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths
        },
        "caller_authenticates_oos_and_price_basis": True,
    }


# Calibrate stock distributions exclusively from mature prior OOS errors.
def calibrate(
    dates,
    symbols,
    means,
    second_moments,
    labels,
    valid,
    outcome_end_dates,
    *,
    data_as_of,
    horizon,
):
    if horizon != HORIZON:
        raise ValueError("Matching one-decision execution horizon required")
    identity = _identity(
        dates,
        symbols,
        means,
        second_moments,
        labels,
        valid,
        outcome_end_dates,
        data_as_of,
        horizon,
    )
    (
        dates,
        names,
        mu,
        second,
        outcomes,
        causal,
        ends,
        completion,
        observed,
        supported,
        as_of,
        sessions,
    ) = _validate(
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
        variance = second - mu * mu
    moment_valid = (
        np.isfinite(mu) & np.isfinite(variance) & (second >= 0) & (variance > 0)
    )
    scales = np.full(mu.shape, np.nan)
    scales[moment_valid] = np.sqrt(variance[moment_valid])
    causal_support = (
        causal
        & supported[:, :, None]
        & (observed[:, :, None] <= as_of)
        & ~np.isin(names, ("SPY", "QQQ"))[None, None, :]
    )
    score = causal_support & moment_valid
    probability = np.full(mu.shape, np.nan)
    quantiles = np.full((*mu.shape, 3), np.nan)
    samples, receipts = {}, []
    months = dates.astype("datetime64[M]")
    for month in np.unique(months):
        name = str(month)
        first = np.busday_offset(
            month.astype("datetime64[D]"), 0, roll="forward", busdaycal=sessions
        )
        stop = int(np.searchsorted(dates, first))
        lower = max(0, stop - MAX_DAYS)
        cutoff = min(first, FREEZE)
        train_days = (np.arange(len(dates)) >= lower) & (np.arange(len(dates)) < stop)
        mature = (ends < cutoff) & (completion <= as_of) & ~np.isnat(completion)
        train = score & np.isfinite(outcomes) & mature & train_days[:, None, None]
        samples[name], stock_receipts = {}, []
        for stock, symbol in enumerate(names):
            day, clock = np.nonzero(train[:, :, stock])
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                residual = (
                    outcomes[day, clock, stock] - mu[day, clock, stock]
                ) / scales[day, clock, stock]
            finite = np.isfinite(residual)
            day, clock, residual = day[finite], clock[finite], residual[finite]
            unique, counts = np.unique(day, return_counts=True)
            weights = (
                1.0 / counts[np.searchsorted(unique, day)]
                if len(day)
                else np.array([], dtype=np.float64)
            )
            receipt = {
                "symbol": symbol,
                "status": "available"
                if len(unique) >= MIN_DAYS
                else "insufficient_mature_sessions",
                "training_days": int(len(unique)),
                "training_rows": int(len(day)),
                "nonfinite_residual_rows": int((~finite).sum()),
                "maximum_endpoint": str(ends[day, clock, stock].max())
                if len(day)
                else None,
                "hashes": {
                    key: _hash(value)
                    for key, value in zip(
                        ("day_indices", "clock_indices", "residuals", "weights"),
                        (day, clock, residual, weights),
                        strict=True,
                    )
                },
            }
            stock_receipts.append(receipt)
            if symbol in ("SPY", "QQQ"):
                receipt["status"] = "excluded_benchmark"
                continue
            if len(unique) < MIN_DAYS:
                continue
            sample = ResidualSample(residual, weights, day, clock)
            samples[name][symbol] = sample
            order = np.argsort(residual, kind="stable")
            ordered = residual[order]
            cumulative = np.concatenate(([0.0], np.cumsum(weights[order])))
            residual_quantiles = weighted_quantiles(residual, weights)
            target_days, target_clocks = np.nonzero(
                score[:, :, stock] & (months == month)[:, None]
            )
            thresholds = (
                -mu[target_days, target_clocks, stock]
                / scales[target_days, target_clocks, stock]
            )
            positions = np.searchsorted(ordered, thresholds, side="right")
            probability[target_days, target_clocks, stock] = (
                cumulative[-1] - cumulative[positions]
            ) / cumulative[-1]
            with np.errstate(over="ignore", invalid="ignore"):
                predicted_quantiles = (
                    mu[target_days, target_clocks, stock, None]
                    + scales[target_days, target_clocks, stock, None]
                    * residual_quantiles
                )
            finite_quantiles = np.isfinite(predicted_quantiles).all(axis=1)
            quantiles[
                target_days[finite_quantiles], target_clocks[finite_quantiles], stock
            ] = predicted_quantiles[finite_quantiles]
            probability[
                target_days[~finite_quantiles], target_clocks[~finite_quantiles], stock
            ] = np.nan
            receipt["nonfinite_quantile_rows"] = int((~finite_quantiles).sum())
        receipts.append(
            {
                "month": name,
                "fit_date": str(first),
                "cutoff_exclusive": str(cutoff),
                "lookback_first_index": lower,
                "stocks": stock_receipts,
            }
        )
    available = score & np.isfinite(probability) & np.isfinite(quantiles).all(axis=-1)
    manifest = {
        "identity": identity,
        "months": receipts,
        "causal_opportunities": int(causal_support.sum()),
        "available": int(available.sum()),
        "unavailable": int((causal_support & ~available).sum()),
        "invalid_moment_rows": int((causal_support & ~moment_valid).sum()),
        "arrays": {
            name: _hash(value)
            for name, value in (
                ("probability_positive", probability),
                ("quantiles", quantiles),
                ("score_mask", available),
                ("causal_mask", causal_support),
            )
        },
        "confidence_guarantee": False,
    }
    return Calibration(
        probability,
        quantiles,
        mu,
        scales,
        available,
        causal_support,
        dates,
        names,
        samples,
        manifest,
    )


# Compare full empirical fixed-quantity waiting gains using actual funded NAV exposure.
def decision(distribution, side, fundedfraction, cost_bps, *, horizon):
    if side not in ("buy", "sell") or horizon != HORIZON:
        raise ValueError("Buy/sell and matching execution horizon required")
    if distribution is None:
        return Decision("unavailable", reason="missing calibrated distribution")
    if not isinstance(distribution, Distribution) or distribution.horizon != horizon:
        raise ValueError("Distribution horizon or schema mismatch")
    numeric = (distribution.mean, distribution.scale, fundedfraction, cost_bps)
    if any(isinstance(value, (bool, np.bool_)) for value in numeric):
        return Decision("unavailable", reason="invalid numeric contract")
    try:
        mean, scale, weight, cost = map(float, numeric)
        residuals, weights = _sample(distribution.residuals, distribution.weights)
    except (TypeError, ValueError, OverflowError):
        return Decision("unavailable", reason="invalid empirical or numeric contract")
    if (
        not np.isfinite([mean, scale, weight, cost]).all()
        or scale < 0
        or not 0 <= weight <= 1
        or not 0 <= cost < 1e4
    ):
        return Decision("unavailable", reason="invalid moments, funding or cost")
    if weight == 0:
        return Decision("no_trade", reason="no funded quantity")
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        values = mean + scale * residuals
        factor = weight * (1 + cost / 1e4 if side == "buy" else 1 - cost / 1e4)
        gain = (-factor if side == "buy" else factor) * np.expm1(-values)
        utility = np.log1p(gain)
    if (
        not np.isfinite(values).all()
        or not np.isfinite(utility).all()
        or np.any(gain <= -1)
    ):
        return Decision("unavailable", reason="unsupported hypothetical wealth")
    expected = float(np.dot(weights / weights.sum(), utility))
    if not np.isfinite(expected):
        return Decision("unavailable", reason="nonfinite expected utility")
    return Decision("wait" if expected > 0 else "execute", expected)
