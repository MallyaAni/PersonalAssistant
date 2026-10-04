"""Past-only stock error resolution for supplied authenticated OOS forecasts.

The caller authenticates numeric forecast/report/source files. These statistics
describe observed residuals; they are not coverage guarantees or paid costs.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from backend.market import calendar as exchange
from backend.market import daily_arithmetic_bridge as reference
from backend.market import direct_daily_arithmetic as direct
from backend.market import learned_entry_models as base
from backend.market import probabilistic_execution as probability

POLICY = "direct-error-band/1-research"
PROTOCOL = "docs/research/direct-error-band-plan-2026-10-03.md"
VOLATILITY_PROTOCOL = "docs/research/holding-volatility-correction-plan-2026-10-04.md"


# Return aligned error radii separately from their complete calibration receipts.
@dataclass(frozen=True)
class ErrorBands:
    radii: np.ndarray
    manifest: dict


# Validate the exact chronological and numeric forecast representation.
def _inputs(dates, symbols, forecasts, bridge):
    if not isinstance(bridge, reference.BridgeForecasts):
        raise ValueError("Validated BridgeForecasts required")
    dates, forecasts = np.asarray(dates), np.asarray(forecasts)
    names = tuple(symbols)
    if (
        dates.ndim != 1
        or not len(dates)
        or dates.dtype != np.dtype("datetime64[D]")
        or np.isnat(dates).any()
        or np.any(dates[1:] <= dates[:-1])
    ):
        raise ValueError("Exact chronological datetime64[D] dates required")
    if (
        not names
        or any(not isinstance(name, str) or not name for name in names)
        or len(set(names)) != len(names)
        or not {"SPY", "QQQ"}.issubset(names)
    ):
        raise ValueError("Unique symbols including SPY and QQQ required")
    shape = (len(dates), len(names))
    if forecasts.shape != shape or forecasts.dtype != np.dtype("float64"):
        raise ValueError("Exact aligned float64 direct forecasts required")
    if np.isinf(forecasts).any() or np.any(np.isfinite(forecasts) & (forecasts <= -1)):
        raise ValueError("Direct forecasts must be possible finite returns or missing")
    return dates, names, forecasts


# Bind the original bridge grids, outcomes and causal stock support.
def _bridge(dates, names, forecasts, bridge):
    shape = forecasts.shape
    parent = bridge.manifest
    if (
        parent.get("policy") != reference.POLICY
        or parent.get("symbols") != list(names)
        or parent.get("maximum_days") != reference.MAX_DAYS
        or parent.get("freeze") != str(reference.FREEZE)
        or parent.get("target") != "adjusted_open[t+2]/adjusted_open[t+1]-1"
        or parent.get("units") != "one_session_arithmetic_return"
        or parent.get("input_sha256", {}).get("dates") != reference._hash(dates)
        or parent.get("input_sha256", {}).get("symbols")
        != reference._hash(np.asarray(names))
    ):
        raise ValueError("Original bridge schema and input bytes mismatch")
    for field, digest in (
        ("calibrated", "calibrated_sha256"),
        ("past_mean", "past_mean_sha256"),
        ("labels", "label_sha256"),
        ("label_end_dates", "label_end_dates_sha256"),
        ("score_mask", "score_mask_sha256"),
    ):
        value = np.asarray(getattr(bridge, field))
        expected = (len(dates),) if field == "label_end_dates" else shape
        if value.shape != expected or reference._hash(value) != parent.get(digest):
            raise ValueError(f"Original bridge {field} bytes mismatch")
    if bridge.score_mask.dtype != np.dtype("bool") or bridge.labels.dtype != np.dtype(
        "float64"
    ):
        raise ValueError("Exact boolean support and float64 labels required")
    if np.isinf(bridge.labels).any() or np.any(
        np.isfinite(bridge.labels) & (bridge.labels <= -1)
    ):
        raise ValueError("Labels must be possible finite returns or missing")
    endpoints = np.full(len(dates), np.datetime64("NaT", "D"))
    endpoints[:-2] = dates[2:]
    if bridge.label_end_dates.dtype != endpoints.dtype or not np.array_equal(
        bridge.label_end_dates.view("i8"), endpoints.view("i8")
    ):
        raise ValueError("Exact one-session arithmetic outcome endpoints required")
    benchmark = np.array([name in ("SPY", "QQQ") for name in names])
    if np.any(bridge.score_mask[:, benchmark]) or np.any(
        np.isfinite(forecasts) & ~bridge.score_mask
    ):
        raise ValueError("Direct forecasts disagree with causal stock support")


# Authenticate direct manifest lineage before using its supplied residuals.
def _direct(dates, names, forecasts, direct_manifest, bridge):
    parent = bridge.manifest
    identity = direct_manifest.get("identity", {})
    if (
        direct_manifest.get("identity_sha256") != base._json_hash(identity)
        or identity.get("policy") != direct.POLICY
        or identity.get("symbols") != list(names)
        or identity.get("target") != parent["target"]
        or identity.get("config") != base.MODEL_CONFIG["boosting"]
        or identity.get("minimum_days") != reference.MIN_DAYS
        or identity.get("label_end") != 2
        or identity.get("holdout_end_before") != str(reference.FREEZE)
        or identity.get("maximum_days") != reference.MAX_DAYS
        or identity.get("bridge_manifest_sha256") != base._json_hash(parent)
    ):
        raise ValueError("Authenticated direct identity mismatch")
    source = identity.get("source_sha256", {})
    required = {
        "backend/market/direct_daily_arithmetic.py",
        "backend/market/learned_entry_models.py",
        "backend/market/daily_arithmetic_bridge.py",
        direct.PROTOCOL,
    }
    if set(source) != required or any(
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in source.values()
    ):
        raise ValueError("Explicit direct training source hashes required")
    for key, value in (
        ("dates_sha256", dates),
        ("labels_sha256", bridge.labels),
        ("label_end_dates_sha256", bridge.label_end_dates),
        ("score_mask_sha256", bridge.score_mask),
    ):
        if identity.get(key) != reference._hash(value):
            raise ValueError(f"Direct identity {key} mismatch")
    if direct_manifest.get("forecasts_sha256") != reference._hash(
        forecasts
    ) or direct_manifest.get("score_mask_sha256") != reference._hash(bridge.score_mask):
        raise ValueError("Direct forecast or support bytes mismatch")


# Refuse mismatched monthly prediction bytes or retrospective scoring clocks.
def _months(dates, forecasts, direct_manifest, bridge):
    parent = bridge.manifest
    months = dates.astype("datetime64[M]")
    expected_months = [str(month) for month in np.unique(months)]
    if [row.get("month") for row in parent["months"]] != expected_months or [
        row.get("month") for row in direct_manifest["months"]
    ] != expected_months:
        raise ValueError("Exact original monthly receipt schedule required")
    for receipt, month in zip(
        direct_manifest["months"], np.unique(months), strict=True
    ):
        scored = np.flatnonzero(months == month)
        if (
            receipt.get("fit_index") != int(scored[0])
            or receipt.get("fit_date") != str(dates[scored[0]])
            or receipt.get("label_end_before")
            != str(min(dates[scored[0]], reference.FREEZE))
            or receipt.get("prediction_sha256") != reference._hash(forecasts[scored])
            or (
                receipt.get("status") != "fitted"
                and np.isfinite(forecasts[scored]).any()
            )
        ):
            raise ValueError("Original direct monthly clock or forecast bytes mismatch")


# Ensure supplied outcomes and eligible decisions existed by the stated close.
def _publication(dates, bridge):
    endpoints = bridge.label_end_dates
    parent = bridge.manifest
    as_of = reference._as_of(parent["data_as_of"])
    for day in dates:
        close = datetime.combine(
            day.astype(object),
            exchange.session_close(day.astype(object)),
            exchange.NEW_YORK,
        )
        if close > as_of:
            index = int(np.searchsorted(dates, day))
            if bridge.score_mask[index].any():
                raise ValueError(
                    "Scoring support precedes completed session publication"
                )
        if (
            day > np.datetime64(as_of.date())
            and np.isfinite(bridge.labels[np.searchsorted(dates, day)]).any()
        ):
            raise ValueError("Future decision outcomes cannot be known")
    known = np.isfinite(bridge.labels).any(axis=1)
    for index in np.flatnonzero(known):
        if np.isnat(endpoints[index]):
            raise ValueError("Finite label has no outcome endpoint")
        close = datetime.combine(
            endpoints[index].astype(object),
            exchange.session_close(endpoints[index].astype(object)),
            exchange.NEW_YORK,
        )
        if close > as_of:
            raise ValueError("Finite label endpoint is not yet known")
    return as_of


# Check every supplied lineage and availability boundary before calibration.
def _validate(dates, symbols, forecasts, direct_manifest, bridge):
    dates, names, forecasts = _inputs(dates, symbols, forecasts, bridge)
    _bridge(dates, names, forecasts, bridge)
    _direct(dates, names, forecasts, direct_manifest, bridge)
    _months(dates, forecasts, direct_manifest, bridge)
    return dates, names, forecasts, _publication(dates, bridge)


# Compute the exact registered cluster statistic with overflow-aware scaling.
def _statistics(errors, clusters):
    unique, group = np.unique(clusters, return_inverse=True)
    n, g = len(errors), len(unique)
    empty = {
        "bias": None,
        "cluster_sums": None,
        "cluster_sums_scaled": None,
        "residual_scale": None,
        "standard_error": None,
        "radius": None,
    }
    if not np.isfinite(errors).all():
        return {
            **empty,
            "status": "nonfinite_residual",
            "nonfinite_residuals": int((~np.isfinite(errors)).sum()),
        }
    if n < 2 or g < 2:
        return {
            **empty,
            "status": "insufficient_observations" if n < 2 else "insufficient_clusters",
            "nonfinite_residuals": 0,
        }
    scale = float(np.max(np.abs(errors)))
    normalized = errors / scale if scale else np.zeros_like(errors)
    mean = float(np.mean(normalized))
    centered = normalized - mean
    sums = np.bincount(group, weights=centered, minlength=g)
    with np.errstate(over="ignore", invalid="ignore"):
        bias = float(mean * scale)
        se = float((np.linalg.norm(sums / n) * np.sqrt(g / (g - 1))) * scale)
        radius = float(abs(bias) + se)
        actual_sums = sums * scale
    if not np.isfinite([bias, se, radius]).all():
        return {**empty, "status": "nonfinite_statistic", "nonfinite_residuals": 0}
    return {
        "status": "available",
        "nonfinite_residuals": 0,
        "bias": bias,
        "cluster_sums": [
            float(value) if np.isfinite(value) else None for value in actual_sums
        ],
        "cluster_sums_scaled": sums.tolist(),
        "residual_scale": scale,
        "standard_error": se,
        "radius": radius,
    }


# Freeze each stock's past-only residual resolution for its entire scoring month.
def calibrate(dates, symbols, forecasts, direct_manifest, bridge):
    dates, names, forecasts, as_of = _validate(
        dates, symbols, forecasts, direct_manifest, bridge
    )
    root = Path(__file__).resolve().parents[2]
    identity = {
        "policy": POLICY,
        "maximum_days": reference.MAX_DAYS,
        "freeze": str(reference.FREEZE),
        "minimum_observations": 2,
        "minimum_clusters": 2,
        "multiplier": 1,
        "units": "one_session_arithmetic_return",
        "clustering": "forecast_calendar_month",
        "direct_manifest_sha256": base._json_hash(direct_manifest),
        "bridge_manifest_sha256": base._json_hash(bridge.manifest),
        "input_sha256": {
            "dates": reference._hash(dates),
            "symbols": reference._hash(np.asarray(names)),
            "forecasts": reference._hash(forecasts),
            "labels": reference._hash(bridge.labels),
            "label_end_dates": reference._hash(bridge.label_end_dates),
            "score_mask": reference._hash(bridge.score_mask),
        },
        "source_sha256": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path(__file__).resolve(),
                root / PROTOCOL,
                Path(reference.__file__).resolve(),
                Path(base.__file__).resolve(),
                Path(direct.__file__).resolve(),
                Path(exchange.__file__).resolve(),
            )
        },
        "runtime": {"numpy": np.__version__},
        "calculation_precision": "float64",
    }
    return freeze_rows(
        dates,
        names,
        forecasts,
        bridge.labels,
        bridge.label_end_dates,
        bridge.score_mask,
        as_of,
        identity,
    )


# Freeze supplied validated OOS residual rows using the registered unchanged formula.
def freeze_rows(
    dates, names, forecasts, labels, endpoints, score_mask, as_of, identity
):
    manifest = {
        "identity": identity,
        "identity_sha256": base._json_hash(identity),
        "months": [],
    }
    radii = np.full(forecasts.shape, np.nan, dtype=np.float64)
    months = dates.astype("datetime64[M]")
    for month in np.unique(months):
        scored = np.flatnonzero(months == month)
        first = int(scored[0])
        cutoff = min(dates[first], reference.FREEZE)
        days = np.arange(max(0, first - reference.MAX_DAYS), first, dtype=np.int64)
        days = days[~np.isnat(endpoints[days]) & (endpoints[days] < cutoff)]
        receipt = {
            "month": str(month),
            "fit_date": str(dates[first]),
            "fit_index": first,
            "label_end_before": str(cutoff),
            "stocks": [],
        }
        completed = (
            datetime.combine(
                dates[first].astype(object),
                exchange.session_close(dates[first].astype(object)),
                exchange.NEW_YORK,
            )
            <= as_of
        )
        for stock, name in enumerate(names):
            chosen = days[
                score_mask[days, stock]
                & np.isfinite(forecasts[days, stock])
                & np.isfinite(labels[days, stock])
            ]
            with np.errstate(over="ignore", invalid="ignore"):
                errors = labels[chosen, stock] - forecasts[chosen, stock]
            clusters = months[chosen]
            row = {
                "symbol": name,
                "observations": len(chosen),
                "clusters": len(np.unique(clusters)),
                "maximum_endpoint": str(endpoints[chosen].max())
                if len(chosen)
                else None,
                "cluster_months": [str(value) for value in np.unique(clusters)],
                "row_sha256": {
                    "decision_indices": reference._hash(chosen),
                    "forecasts": reference._hash(forecasts[chosen, stock]),
                    "labels": reference._hash(labels[chosen, stock]),
                    "residuals": reference._hash(errors),
                    "endpoints": reference._hash(endpoints[chosen]),
                    "clusters": reference._hash(clusters),
                },
            }
            row.update(_statistics(errors, clusters))
            if name in ("SPY", "QQQ"):
                row["status"] = "excluded_benchmark"
            elif not completed:
                row["status"] = "fit_clock_unavailable"
            elif row["status"] == "available":
                radii[scored, stock] = np.where(
                    score_mask[scored, stock], row["radius"], np.nan
                )
            receipt["stocks"].append(row)
        receipt["radii_sha256"] = reference._hash(radii[scored])
        manifest["months"].append(receipt)
    finite = np.flatnonzero(np.isfinite(radii).any(axis=1))
    manifest["first_score_date"] = str(dates[finite[0]]) if len(finite) else None
    manifest["radii_sha256"] = reference._hash(radii)
    manifest["counts"] = {
        "opportunities": int(score_mask.sum()),
        "available": int(np.isfinite(radii).sum()),
        "unavailable": int((score_mask & ~np.isfinite(radii)).sum()),
    }
    return ErrorBands(radii, manifest)


# Score a mature stock-return distribution without interpreting it as account profit.
def score_holding_distribution(values, weights, actual, cost_bps):
    values, weights = probability._sample(values, weights)
    if (
        np.any(values < -1)
        or isinstance(actual, (bool, np.bool_))
        or not isinstance(actual, (int, float, np.integer, np.floating))
        or not np.isfinite(actual)
        or actual < -1
        or isinstance(cost_bps, (bool, np.bool_))
        or not isinstance(cost_bps, (int, float, np.integer, np.floating))
        or not np.isfinite(cost_bps)
        or not 0 <= cost_bps < 10000
        or not np.isclose(weights.sum(), 1.0, rtol=0, atol=1e-12)
    ):
        raise ValueError(
            "Possible mature returns, unit probabilities and valid costs required"
        )
    weights = weights / weights.sum()
    cost = float(cost_bps) / 10000
    with np.errstate(over="ignore", invalid="ignore"):
        net = (1 + values) * ((1 - cost) / (1 + cost)) - 1
        realized = (1 + float(actual)) * ((1 - cost) / (1 + cost)) - 1
        order = np.argsort(net, kind="stable")
        x, w = net[order], weights[order]
        previous_mass = np.r_[0.0, np.cumsum(w)[:-1]]
        previous_value = np.r_[0.0, np.cumsum(w * x)[:-1]]
        half_distance = np.sum(w * (x * previous_mass - previous_value))
        crps = float(weights @ np.abs(net - realized) - half_distance)
        quantiles = probability.weighted_quantiles(net, weights)
        positive = float(weights[net > 0].sum())
        won = int(realized > 0)
        mean = float(weights @ net)
        result = {
            "probability_gain": positive,
            "realized_gain": won,
            "brier": (positive - won) ** 2,
            "crps": crps,
            "predicted_mean": mean,
            "realized_return": float(realized),
            "mean_error": mean - float(realized),
            "quantiles_10_50_90": quantiles.tolist(),
            "interval80_covered": int(quantiles[0] <= realized <= quantiles[-1]),
            "interval80_width": float(quantiles[-1] - quantiles[0]),
            "pit_left": float(weights[net < realized].sum()),
            "pit_right": float(weights[net <= realized].sum()),
        }
    scalars = [value for key, value in result.items() if key != "quantiles_10_50_90"]
    if not np.isfinite(scalars).all() or not np.isfinite(quantiles).all():
        raise ValueError("Holding diagnostic arithmetic exceeds finite range")
    return result


# Distinguish an unpublished D+2 outcome from a past missing original price label.
def _holding_outcome(reader, day, stock):
    endpoint = reader.endpoints[day]
    if np.isnat(endpoint):
        years, calendar = exchange.reviewed_sessions()
        first = reader.dates[-1] + np.timedelta64(1, "D")
        whole = np.arange(first, first + np.timedelta64(30, "D"))
        if any(value.astype(object).year not in years for value in whole):
            return "unknown_outcome_endpoint"
        next_sessions = whole[np.is_busday(whole, busdaycal=calendar)]
        offset = day + 2 - len(reader.dates)
        if not 0 <= offset < len(next_sessions):
            return "unknown_outcome_endpoint"
        endpoint = next_sessions[offset]
    close = datetime.combine(
        endpoint.astype(object),
        exchange.session_close(endpoint.astype(object)),
        exchange.NEW_YORK,
    )
    if close > reader.as_of:
        return "immature_outcome"
    return (
        "known_outcome"
        if np.isfinite(reader.labels[day, stock])
        else "missing_known_outcome"
    )


# Retain every stock/session and score identical mature model/reference cases.
def holding_diagnostic_rows(reader, days):
    from backend.market.direct_feature_arithmetic import HoldingScenarioReader

    if not isinstance(reader, (HoldingScenarioReader, VolatilityHoldingReader)):
        raise ValueError("Authenticated holding scenario reader required")
    days = np.asarray(days)
    if (
        days.ndim != 1
        or not len(days)
        or days.dtype.kind not in "iu"
        or np.any((days < 0) | (days >= len(reader.dates)))
        or np.any(days[1:] <= days[:-1])
    ):
        raise ValueError("Unique chronological declared decision indices required")
    for day in days:
        day = int(day)
        for stock, name in enumerate(reader.symbols):
            if name in ("SPY", "QQQ"):
                continue
            sample = reader.distribution(day, (name,))
            outcome = _holding_outcome(reader, day, stock)
            case = {
                "day": day,
                "stock": stock,
                "symbol": name,
                "prediction_status": sample.receipt["status"],
                "prediction_reason": sample.receipt.get("reason"),
                "outcome_status": outcome,
                "scores": None,
                "scenario_receipt_sha256": base._json_hash(sample.receipt),
                "bank": {
                    key: sample.receipt.get(key)
                    for key in (
                        "fit_date",
                        "label_end_before",
                        "joint_dates",
                        "maximum_endpoint",
                        "row_sha256",
                    )
                },
            }
            if sample.receipt["status"] == "available" and outcome == "known_outcome":
                indices = np.asarray(sample.receipt["decision_indices"], dtype=np.int64)
                observed = reader.labels[day, stock]
                reference_values = reader.labels[indices, stock]
                if not np.isfinite(reference_values).all() or not np.all(
                    reader.endpoints[indices]
                    < np.datetime64(sample.receipt["label_end_before"], "D")
                ):
                    raise ValueError(
                        "Strictly mature original reference labels required"
                    )
                case["scores"] = [
                    {
                        "cost_bps": cost,
                        "model": score_holding_distribution(
                            sample.scenarios[:, 0], sample.probabilities, observed, cost
                        ),
                        "reference": score_holding_distribution(
                            reference_values, sample.probabilities, observed, cost
                        ),
                    }
                    for cost in (0, 10, 25)
                ]
            yield case


# Scale dated log-gross errors to current stock volatility without changing their mean.
def scale_holding_volatility(current, past, outcomes, current_vol, past_vol):
    if any(
        np.asarray(value).dtype.kind not in "fiu"
        for value in (current, past, outcomes, current_vol, past_vol)
    ):
        raise ValueError("Numeric stock forecasts, outcomes and volatility required")
    current, past, outcomes, current_vol, past_vol = (
        np.asarray(value, dtype=np.float64)
        for value in (current, past, outcomes, current_vol, past_vol)
    )
    if (
        current.ndim != 1
        or not len(current)
        or past.ndim != 2
        or not len(past)
        or past.shape[1] != len(current)
        or outcomes.shape != past.shape
        or current_vol.shape != current.shape
        or past_vol.shape != past.shape
        or any(not np.isfinite(value).all() for value in (current, past, outcomes))
        or np.any(current <= -1)
        or np.any(past <= -1)
        or np.any(outcomes < -1)
    ):
        raise ValueError("Aligned possible stock forecasts and dated outcomes required")
    if any(
        not np.isfinite(value).all() or np.any(value <= 0)
        for value in (current_vol, past_vol)
    ):
        raise ValueError("Positive finite current and dated stock volatility required")
    with np.errstate(over="ignore", under="ignore", divide="ignore", invalid="ignore"):
        gross = (1 + outcomes) / (1 + past)
        original = (1 + current) * gross
        ratio = current_vol / past_vol
        log_error = np.log1p(outcomes) - np.log1p(past)
        log_scaled = log_error * ratio
    default = outcomes == -1
    if (
        not np.isfinite(original).all()
        or np.any((original == 0) & ~default)
        or not np.isfinite(ratio).all()
        or np.any(ratio <= 0)
        or not np.isfinite(log_scaled[~default]).all()
    ):
        raise ValueError("Volatility arithmetic exceeds supported finite range")
    result = np.empty(past.shape, dtype=np.float64)
    for stock in range(len(current)):
        if np.all(ratio[:, stock] == 1) or np.all(default[:, stock]):
            result[:, stock] = original[:, stock] - 1
            continue
        log_values = log_scaled[:, stock]
        with np.errstate(over="ignore", under="ignore", invalid="ignore"):
            stable = np.exp(log_values - np.max(log_values))
            maximum = original[:, stock].max()
            desired = maximum * np.mean(original[:, stock] / maximum)
            corrected = stable * (desired / stable.mean())
        if (
            not np.isfinite(corrected).all()
            or np.any((corrected == 0) & ~default[:, stock])
            or not np.isclose(corrected.mean(), desired, rtol=1e-12, atol=1e-15)
        ):
            raise ValueError("Volatility arithmetic exceeds supported finite range")
        result[:, stock] = corrected - 1
    if np.any((result == -1) & ~default):
        raise ValueError("Volatility arithmetic manufactures total loss")
    result.flags.writeable = False
    return result


# Condition dispersion on stock volatility while preserving original joint dates.
class VolatilityHoldingReader:
    # Bind immutable original inputs before extracting any dated volatility context.
    def __init__(self, risk, bridge, *, allow_saved_origin=False):
        from backend.market import direct_feature_arithmetic as feature

        if not isinstance(risk, feature.HoldingRiskForecasts):
            raise ValueError("Authenticated original holding risk artifact required")
        frozen = feature.HoldingRiskForecasts(
            risk.forecasts.copy(),
            risk.score_mask.copy(),
            deepcopy(risk.manifest),
            risk.dates.copy(),
            tuple(risk.symbols),
            feature._copy_feature(risk.parent),
            risk.features.copy(),
            risk.valid.copy(),
            risk.prices.copy(),
        )
        self._reader = feature.HoldingScenarioReader(
            frozen, bridge, allow_saved_origin=allow_saved_origin
        )
        for name in (
            "dates",
            "symbols",
            "as_of",
            "endpoints",
            "labels",
            "forecasts",
            "support",
            "months",
        ):
            setattr(self, name, getattr(self._reader, name))
        self.volatility = frozen.features[:, :, 4].astype(np.float64, copy=True)
        self.volatility.flags.writeable = False
        root = Path(__file__).resolve().parents[2]
        self.identity = {
            "policy": "joint-holding-volatility/1-research",
            "original_scenario_identity_sha256": base._json_hash(self._reader.identity),
            "volatility_feature": "volatility_20",
            "volatility_sha256": reference._hash(self.volatility),
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "protocol_sha256": hashlib.sha256(
                (root / VOLATILITY_PROTOCOL).read_bytes()
            ).hexdigest(),
            "arithmetic_mean_preserved": True,
            "confidence_guarantee": False,
            "adoption_eligible": False,
        }

    # Transform an admitted original request without inspecting its current outcome.
    def distribution(self, day, symbols):
        from backend.market import direct_feature_arithmetic as feature

        original = self._reader.distribution(day, symbols)
        receipt = deepcopy(original.receipt)
        receipt["original_scenario_receipt_sha256"] = base._json_hash(original.receipt)
        receipt["volatility_identity"] = deepcopy(self.identity)
        receipt["policy"] = self.identity["policy"]
        if receipt["status"] != "available":
            return feature.HoldingScenarios(None, None, original.symbols, receipt)
        receipt["original_scenarios_sha256"] = receipt.pop("scenarios_sha256")
        receipt.pop("probabilities_sha256")
        chosen = np.asarray(receipt["decision_indices"], dtype=np.int64)
        stocks = np.asarray([self.symbols.index(name) for name in original.symbols])
        current_vol = self.volatility[day, stocks]
        past_vol = self.volatility[np.ix_(chosen, stocks)]
        receipt["volatility_context_sha256"] = {
            "current": reference._hash(current_vol),
            "bank": reference._hash(past_vol),
        }
        if any(
            not np.isfinite(value).all() or np.any(value <= 0)
            for value in (current_vol, past_vol)
        ):
            receipt.update(
                status="unavailable", reason="unsupported_current_or_bank_volatility"
            )
            return feature.HoldingScenarios(None, None, original.symbols, receipt)
        try:
            scenarios = scale_holding_volatility(
                self.forecasts[day, stocks],
                self.forecasts[np.ix_(chosen, stocks)],
                self.labels[np.ix_(chosen, stocks)],
                current_vol,
                past_vol,
            )
        except ValueError as exc:
            receipt.update(
                status="unavailable",
                reason="unsupported_volatility_arithmetic",
                arithmetic_reason=str(exc),
            )
            return feature.HoldingScenarios(None, None, original.symbols, receipt)
        receipt.update(
            scenarios_sha256=reference._hash(scenarios),
            probabilities_sha256=reference._hash(original.probabilities),
            original_mean_sha256=reference._hash(original.scenarios.mean(axis=0)),
            corrected_mean_sha256=reference._hash(scenarios.mean(axis=0)),
        )
        return feature.HoldingScenarios(
            scenarios, original.probabilities, original.symbols, receipt
        )
