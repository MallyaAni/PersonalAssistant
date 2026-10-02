"""Research-only causal risk sizing and monthly matured-outcome specialist weights."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

NY = ZoneInfo("America/New_York")
CAP = 0.25
RIDGE = 1e-4


# Parse explicit publication instants without assuming a timezone or a date's close.
def timestamp(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("An explicit timezone is required")
    return result.astimezone(NY)


# Bind a frozen monthly fit to its exact admitted training rows and specification.
def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


# Classify trend and volatility from completed market observations through row t only.
def causal_regime(dates, spy_close, t):
    dates = np.asarray(dates)
    prices = np.asarray(spy_close, dtype=float)
    if (
        dates.ndim != 1
        or prices.shape != dates.shape
        or dates.dtype != np.dtype("datetime64[D]")
        or np.isnat(dates).any()
        or np.any(dates[1:] <= dates[:-1])
        or isinstance(t, bool)
        or not isinstance(t, (int, np.integer))
        or not 0 <= t < len(dates)
    ):
        raise ValueError("Ordered daily observations and a valid row are required")
    info = {"information_through": str(dates[t]), "key": None}
    if t < 272:
        return {
            **info,
            "status": "unavailable",
            "reason": "insufficient_regime_history",
        }
    prefix = prices[t - 272 : t + 1]
    if not np.isfinite(prefix).all() or np.any(prefix <= 0):
        return {**info, "status": "unavailable", "reason": "missing_regime_prices"}
    log_returns = np.diff(np.log(prefix))
    # Prior volatility estimates end before t, so the comparison never includes itself.
    prior = [float(np.mean(log_returns[j : j + 20] ** 2)) for j in range(252)]
    vol = float(np.mean(log_returns[-20:] ** 2))
    median = float(np.median(prior))
    trend = float(prefix[-1] / prefix[-61] - 1)
    if abs(trend) <= 1e-12 or abs(vol - median) <= 1e-15:
        return {
            **info,
            "status": "ambiguous",
            "reason": "regime_boundary",
            "trend60_return": trend,
            "variance20": vol,
            "prior252_median": median,
        }
    key = ("up" if trend > 0 else "down") + ("_high" if vol > median else "_low")
    return {
        **info,
        "status": "available",
        "key": key,
        "trend60_return": trend,
        "variance20": vol,
        "prior252_median": median,
    }


# Preserve incumbent intent explicitly when a dated risk forecast cannot be used.
def risk_fallback(base, reason):
    return {
        "status": "unavailable",
        "reason": reason,
        "weights": base.tolist(),
        "exposure_matched_control": base.tolist(),
        "gross_multiplier": 1.0,
        "adoption_eligible": False,
    }


# Validate completed dated covariance history independently of forecast availability.
def dated_returns(returns, return_dates, selected, decision):
    values = np.asarray(returns, dtype=float)
    if values.ndim != 2 or values.shape[1] != len(selected):
        raise ValueError("Return columns must match incumbent weights")
    if return_dates is None:
        return None, "missing_return_dates"
    dates = np.asarray(return_dates)
    if (
        dates.shape != (len(values),)
        or dates.dtype != np.dtype("datetime64[D]")
        or np.isnat(dates).any()
        or np.any(dates[1:] <= dates[:-1])
    ):
        raise ValueError("Ordered dated return observations are required")
    completed = dates <= np.datetime64(decision.date())
    if decision.hour < 16:
        completed &= dates < np.datetime64(decision.date())
    values = values[completed][-252:, selected]
    if len(values) != 252 or not np.isfinite(values).all() or np.any(values <= -1):
        return None, "missing_trailing_covariance"
    if decision.hour >= 16 and (
        not completed.any() or dates[completed][-1] != np.datetime64(decision.date())
    ):
        return None, "stale_trailing_covariance"
    return values, None


# Require each held name's forecast to be published and inside its active horizon.
def risk_variances(risk_records, selected, decision):
    if len(risk_records) != len(selected):
        raise ValueError("Risk records must match incumbent weights")
    forecasts = []
    for record in np.asarray(risk_records, dtype=object)[selected]:
        if record is None or record.get("status") != "forecast":
            return None, "missing_ttm_forecast"
        if record.get("target") != "mean_squared_log_return":
            raise ValueError("TTM squared log-return variance target is required")
        predicted_at = timestamp(record["prediction_at"])
        known_at = timestamp(record["known_at"])
        horizon_end = timestamp(record["horizon_end"])
        if known_at < predicted_at or horizon_end <= predicted_at:
            raise ValueError("Risk forecast chronology is invalid")
        if known_at > decision or predicted_at > decision:
            return None, "risk_forecast_not_available"
        if horizon_end <= decision:
            return None, "risk_forecast_expired"
        variance = record["predicted_risk"]
        if (
            isinstance(variance, bool)
            or not isinstance(variance, (int, float))
            or not np.isfinite(variance)
            or variance < 0
        ):
            raise ValueError("Finite nonnegative risk forecast is required")
        forecasts.append(float(variance))
    return np.asarray(forecasts), None


# Adjust incumbent composition with covariance and TTM while conserving funded gross.
def risk_sizing(
    base_weights,
    returns,
    risk_records,
    decision_at,
    *,
    reduce_gross=False,
    return_dates=None,
    covariance_only=False,
):
    from backend.market.open_source_portfolio import dependencies

    base = np.asarray(base_weights, dtype=float)
    if (
        base.ndim != 1
        or not np.isfinite(base).all()
        or np.any(base < 0)
        or np.any(base > CAP + 1e-12)
        or base.sum() > 1 + 1e-12
        or not isinstance(reduce_gross, bool)
        or not isinstance(covariance_only, bool)
    ):
        raise ValueError("Long-only capped incumbent weights are required")
    if covariance_only and reduce_gross:
        raise ValueError("Covariance-only control must preserve gross")
    decision = timestamp(decision_at)
    selected = base > 0
    if not selected.any():
        return {**risk_fallback(base, "empty_incumbent"), "status": "empty"}
    values, reason = dated_returns(returns, return_dates, selected, decision)
    if reason:
        return risk_fallback(base, reason)
    forecasts = None
    if not covariance_only:
        forecasts, reason = risk_variances(risk_records, selected, decision)
        if reason:
            return risk_fallback(base, reason)
    cp, estimator, prior = dependencies()
    from skfolio.exceptions import NonPositiveVarianceError

    log_returns = np.log1p(values)
    try:
        covariance = (
            prior(covariance_estimator=estimator())
            .fit(log_returns)
            .return_distribution_.covariance
        )
    except NonPositiveVarianceError:
        # Flat or numerically negligible risk supplies no supported sizing adjustment.
        return risk_fallback(base, "degenerate_covariance")
    trailing = np.mean(log_returns[-20:] ** 2, axis=0)
    variance = np.diag(covariance) if covariance_only else np.asarray(forecasts)
    # Keep estimated correlations; replace marginal risk by the dated forecast target.
    scale = np.sqrt(variance / np.maximum(np.diag(covariance), 1e-16))
    forecast_covariance = covariance * np.outer(scale, scale)
    own = base[selected]
    forecast_risk = float(own @ forecast_covariance @ own)
    baseline_scale = np.sqrt(trailing / np.maximum(np.diag(covariance), 1e-16))
    baseline_covariance = covariance * np.outer(baseline_scale, baseline_scale)
    baseline_risk = max(0.0, float(own @ baseline_covariance @ own))
    multiplier = (
        min(1.0, np.sqrt(baseline_risk / forecast_risk))
        if reduce_gross and forecast_risk > 0
        else 1.0
    )
    gross = float(base.sum() * multiplier)
    anchored = own * multiplier
    weights = cp.Variable(len(own))
    normalized = forecast_covariance / max(float(np.trace(forecast_covariance)), 1e-16)
    problem = cp.Problem(
        cp.Minimize(
            cp.quad_form(weights, normalized) + cp.sum_squares(weights - anchored)
        ),
        [weights >= 0, weights <= CAP, cp.sum(weights) == gross],
    )
    problem.solve(solver="CLARABEL", tol_gap_abs=1e-10, tol_feas=1e-10)
    if problem.status != cp.OPTIMAL:
        raise RuntimeError("Risk sizing did not establish an optimal solution")
    fitted = np.asarray(weights.value, dtype=float)
    if (
        not np.isfinite(fitted).all()
        or np.any(fitted < -1e-8)
        or np.any(fitted > CAP + 1e-8)
        or abs(fitted.sum() - gross) > 1e-8
    ):
        raise RuntimeError("Risk sizing violated gross or cap constraints")
    out = np.zeros_like(base)
    out[selected] = np.clip(fitted, 0, CAP)
    return {
        "status": "sized",
        "weights": out.tolist(),
        "exposure_matched_control": (base * multiplier).tolist(),
        "gross_multiplier": float(multiplier),
        "forecast_variance": forecast_risk,
        "trailing20_variance": baseline_risk,
        "gross": gross,
        "risk_budget_enabled": reduce_gross,
        "adoption_eligible": False,
        "covariance_only": covariance_only,
    }


# Fit monthly convex residual-utility weights from matured pre-month evidence.
class MonthlySelector:
    # Freeze expert order and a declared minimum sample requirement before outcomes.
    def __init__(self, experts, min_samples=20):
        self.experts = tuple(experts)
        if (
            not self.experts
            or len(set(self.experts)) != len(self.experts)
            or any(not isinstance(x, str) or not x for x in self.experts)
        ):
            raise ValueError("Unique nonempty expert names are required")
        if type(min_samples) is not int or min_samples < 20:
            raise ValueError("At least twenty training observations are required")
        self.min_samples = min_samples
        self.fits = {}

    # Freeze month/regime weights while preserving the incumbent residual.
    def select(self, decision_at, regime, outcome_rows):
        decision = timestamp(decision_at)
        if isinstance(regime, dict):
            if regime.get("information_through", "9999") > decision.date().isoformat():
                raise ValueError("Regime features exceed decision date")
            regime = regime.get("key") if regime.get("status") == "available" else None
        month_start = decision.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        cutoff = month_start - timedelta(microseconds=1)
        key = (month_start.isoformat(), regime)
        if regime not in ("up_high", "up_low", "down_high", "down_low"):
            return self._fallback(
                month_start, cutoff, regime, "regime_unavailable", 0, 0
            )
        if key not in self.fits:
            rows, purged = self._admit(outcome_rows, cutoff, month_start, regime)
            months = {timestamp(row["prediction_at"]).strftime("%Y-%m") for row in rows}
            if len(rows) < self.min_samples or len(months) < 3:
                result = self._fallback(
                    month_start,
                    cutoff,
                    regime,
                    "insufficient_matured_regime_history",
                    len(rows),
                    purged,
                )
            else:
                result = self._fit(rows, month_start, cutoff, regime, purged)
            result["training_months"] = sorted(months)
            result["requested_training_opportunities"] = len(outcome_rows)
            self.fits[key] = copy.deepcopy(result)
        return copy.deepcopy(self.fits[key])

    # Purge overlapping labels and late publications regardless of supplied order.
    def _admit(self, outcome_rows, cutoff, month_start, regime):
        rows, purged, seen = [], 0, set()
        for row in outcome_rows:
            prediction = timestamp(row["prediction_at"])
            known = timestamp(row["known_at"])
            end = timestamp(row["label_end"])
            available = timestamp(row["label_available_at"])
            identity = prediction.isoformat()
            if identity in seen:
                raise ValueError("Duplicate prediction opportunity")
            seen.add(identity)
            if known < prediction or end <= prediction or available < end:
                raise ValueError("Outcome publication chronology is invalid")
            if (
                prediction > cutoff
                or known > cutoff
                or end >= month_start
                or available > cutoff
            ):
                purged += 1
                continue
            if row["regime"] != regime:
                continue
            utilities = row["utilities"]
            if set(utilities) != set(self.experts):
                purged += 1
                continue
            if any(
                isinstance(v, bool)
                or not isinstance(v, (int, float))
                or not np.isfinite(v)
                for v in utilities.values()
            ):
                raise ValueError(
                    "Finite complete incremental expert utilities are required"
                )
            rows.append(
                {**row, "utilities": {x: float(utilities[x]) for x in self.experts}}
            )
        rows.sort(key=lambda row: timestamp(row["prediction_at"]))
        return rows, purged

    # Preserve every opportunity and explain zero specialist allocation.
    def _fallback(self, month_start, cutoff, regime, reason, count, purged):
        return {
            "status": "incumbent_fallback",
            "reason": reason,
            "weights": dict.fromkeys(self.experts, 0.0),
            "incumbent_weight": 1.0,
            "month": month_start.strftime("%Y-%m"),
            "fit_cutoff": cutoff.isoformat(),
            "regime": regime,
            "training_count": count,
            "purged_count": purged,
            "adoption_eligible": False,
        }

    # Fit concave residual utility with a second-moment/ridge simplex penalty.
    def _fit(self, rows, month_start, cutoff, regime, purged):
        import cvxpy as cp

        utilities = np.array(
            [[row["utilities"][x] for x in self.experts] for row in rows]
        )
        moment = utilities.T @ utilities / len(rows) + RIDGE * np.eye(len(self.experts))
        weights = cp.Variable(len(self.experts))
        problem = cp.Problem(
            cp.Maximize(
                utilities.mean(axis=0) @ weights - 0.5 * cp.quad_form(weights, moment)
            ),
            [weights >= 0, cp.sum(weights) <= 1],
        )
        problem.solve(solver="CLARABEL", tol_gap_abs=1e-10, tol_feas=1e-10)
        if problem.status != cp.OPTIMAL:
            raise RuntimeError("Monthly selector did not establish an optimal solution")
        fitted = np.asarray(weights.value, dtype=float)
        if (
            not np.isfinite(fitted).all()
            or np.any(fitted < -1e-8)
            or fitted.sum() > 1 + 1e-8
        ):
            raise RuntimeError("Monthly selector violated convex weight constraints")
        fitted = np.maximum(0, fitted)
        fitted /= max(1.0, float(fitted.sum()))
        return {
            "status": "fitted",
            "weights": dict(zip(self.experts, fitted.tolist(), strict=True)),
            "incumbent_weight": float(1 - fitted.sum()),
            "month": month_start.strftime("%Y-%m"),
            "fit_cutoff": cutoff.isoformat(),
            "regime": regime,
            "training_count": len(rows),
            "purged_count": purged,
            "training_sha256": digest(rows),
            "ridge": RIDGE,
            "adoption_eligible": False,
        }
