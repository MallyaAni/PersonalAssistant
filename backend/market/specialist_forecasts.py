"""Joint pretrained stock/context/SPY forecasts, isolated from live decisions.

Use explicitly supplied context evidence and unchanged univariate artifacts.
This is a new retrospective research protocol, not a revision of their scores.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, time
from typing import Any

import numpy as np

from backend.market import open_source_forecasts as base

PROTOCOL = "specialist-joint-forecast/1"
MODELS = ("chronos2", "timesfm3")
CONTEXT_KINDS = ("sector_proxy", "peer_group", "broad_market_proxy")


# Require dated, declared context evidence and identical completed-session grids.
def group(
    payload: dict, symbol: str, decision: str, evidence: dict | None
) -> tuple[list[str], list[list[dict]], list[str]]:
    if not isinstance(evidence, dict):
        raise ValueError("missing_context_evidence")
    proxies = evidence.get("symbols")
    if (
        not isinstance(proxies, list)
        or not proxies
        or not all(isinstance(p, str) and p for p in proxies)
        or len(set(proxies)) != len(proxies)
        or not any(p != symbol for p in proxies)
    ):
        raise ValueError("invalid_context_members")
    if evidence.get("kind") not in CONTEXT_KINDS or not evidence.get("source"):
        raise ValueError("missing_context_kind_or_source")
    if evidence.get("availability_mode") not in ("recorded", "assumed_research_map"):
        raise ValueError("missing_context_availability_mode")
    cutoff = datetime.combine(date.fromisoformat(decision), time(16), base.NY)
    if (
        not evidence.get("available_at")
        or base.aware(evidence["available_at"]) > cutoff
    ):
        raise ValueError("context_evidence_not_available")
    members = list(dict.fromkeys([symbol, *proxies, "SPY"]))
    if len(members) > 32:
        raise ValueError("context_exceeds_native_joint_group_limit")
    contexts, future = [], []
    for member in members:
        rows, dates = base.context(payload, member, decision)
        if future and dates != future:
            raise ValueError("unsynchronized_future_calendar")
        contexts.append(rows)
        future = dates
    return members, contexts, future


class JointForecaster:
    """Call the reviewed native multivariate interface using the existing loader."""

    # Keep licensing, immutable weights and CPU loading identical to the baseline.
    def __init__(self, name: str, *, research_only: bool = False):
        if name not in MODELS:
            raise ValueError("unsupported_joint_model")
        self.loader = base.Forecaster(name, research_only=research_only)
        self.spec = self.loader.spec
        self.cache: dict[str, np.ndarray] = {}
        self.shapes: dict[str, list[int]] = {}
        self.shape_cache: dict[str, dict[str, list[int]]] = {}

    # Expose actual loaded package/source identities for the joint artifact.
    @property
    def runtime(self) -> dict:
        return self.loader.runtime

    # Forecast all related channels jointly without future prices or covariates.
    def predict(self, contexts: list[list[dict]], future: list[str]) -> np.ndarray:
        key = base.digest(
            {
                "contexts": contexts,
                "future": future,
                "checkpoint": asdict(self.spec),
                "protocol": PROTOCOL,
            }
        )
        if key in self.cache:
            self.shapes = self.shape_cache[key]
            return self.cache[key].copy()
        if self.loader.model is None:
            self.loader.load()
        import torch

        closes = np.array(
            [[r["close"] for r in rows] for rows in contexts], dtype=np.float32
        )
        if closes.shape != (len(contexts), base.CONTEXT) or len(future) != base.HORIZON:
            raise ValueError("invalid_joint_input_shape")
        torch.manual_seed(0)
        torch.use_deterministic_algorithms(True)
        with torch.inference_mode():
            if self.spec.name == "chronos2":
                quantiles, _ = self.loader.model.predict_quantiles(
                    [torch.tensor(closes)],
                    prediction_length=base.HORIZON,
                    quantile_levels=[0.5],
                    cross_learning=False,
                )
                raw = quantiles[0].detach().cpu().numpy()
                if raw.shape != (len(contexts), base.HORIZON, 1):
                    raise ValueError("invalid_chronos_joint_output_shape")
                result = raw[..., 0]
            else:
                outputs = list(
                    self.loader.model.predict_batch(
                        [closes],
                        horizon=base.HORIZON,
                        return_quantiles=True,
                        use_symmetric_averaging=False,
                        univariate=False,
                    )
                )
                if len(outputs) != 1:
                    raise ValueError("invalid_timesfm_joint_batch")
                raw = np.asarray(outputs[0].quantiles)
                if raw.shape != (len(contexts), base.HORIZON, 9):
                    raise ValueError("invalid_timesfm_joint_output_shape")
                result = raw[..., 4]
        result = np.asarray(result, dtype=float)
        if not np.isfinite(result).all() or (result <= 0).any():
            raise ValueError("invalid_joint_forecast_prices")
        self.shapes = {
            "input": list(closes.shape),
            "native_output": list(raw.shape),
            "median_output": list(result.shape),
        }
        self.cache[key] = result.copy()
        self.shape_cache[key] = self.shapes
        return result


# Freeze native joint inference settings independently of observed outcomes.
def profile(name: str) -> dict:
    if name not in MODELS:
        raise ValueError("unsupported_joint_model")
    return {
        "protocol": PROTOCOL,
        "model": name,
        "context": base.CONTEXT,
        "horizon": base.HORIZON,
        "point_forecast": "median",
        "seed": 0,
        "cross_learning": False if name == "chronos2" else None,
        "univariate": False if name == "timesfm3" else None,
        "symmetric_averaging": False if name == "timesfm3" else None,
        "future_covariates": False,
    }


# Validate baseline identities before comparing against their preserved forecasts.
def baseline_index(payload: dict, artifact: dict, name: str, input_sha256: str) -> dict:
    spec = base.CHECKPOINTS[name]
    if (
        artifact.get("protocol") != base.PROTOCOL
        or artifact.get("checkpoint") != asdict(spec)
        or artifact.get("source_revision") != payload.get("source_revision")
        or not input_sha256
        or artifact.get("input_sha256") != input_sha256
    ):
        raise ValueError("univariate_artifact_identity_mismatch")
    indexed = {}
    for record in artifact["records"]:
        key = (record["symbol"], record["decision"])
        if key in indexed or record.get("model") != name:
            raise ValueError("duplicate_or_wrong_univariate_opportunity")
        indexed[key] = record
    return indexed


# Validate a complete independent baseline forecast for this exact causal prefix.
def paired_baseline(
    indexed: dict, symbol: str, decision: str, rows: list[dict]
) -> dict:
    record = indexed.get((symbol, decision))
    if not record or record.get("status") != "forecast":
        raise ValueError("univariate_baseline_unavailable")
    if record.get("context_hash") != base.digest(rows):
        raise ValueError("univariate_context_mismatch")
    values = np.asarray(record.get("forecast"), dtype=float)
    excess = record.get("predicted_excess_return")
    if (
        values.shape != (base.HORIZON,)
        or not np.isfinite(values).all()
        or (values <= 0).any()
        or not isinstance(excess, (int, float))
        or not np.isfinite(excess)
    ):
        raise ValueError("invalid_univariate_baseline")
    return record


# Retain every joint opportunity, paired input and inference failure explicitly.
def run(
    payload: dict,
    name: str,
    symbols: list[str],
    contexts: dict[str, dict],
    baseline: dict,
    *,
    input_sha256: str,
    research_only: bool = False,
    forecaster: JointForecaster | None = None,
) -> dict:
    if name == "timesfm3" and not research_only:
        raise ValueError("TimesFM3 requires explicit noncommercial research mode")
    if len(symbols) != len(set(symbols)) or not symbols:
        raise ValueError("requested symbols must be unique and nonempty")
    engine = forecaster or JointForecaster(name, research_only=research_only)
    if engine.spec != base.CHECKPOINTS[name]:
        raise ValueError("joint_engine_checkpoint_mismatch")
    indexed = baseline_index(payload, baseline, name, input_sha256)
    records: list[dict[str, Any]] = []
    for decision in payload["decisions"]:
        for symbol in symbols:
            record: dict[str, Any] = {
                "model": name,
                "symbol": symbol,
                "decision": decision,
                "status": "unavailable",
            }
            records.append(record)
            if decision < engine.spec.available_on:
                record["reason"] = "checkpoint_not_available"
                continue
            try:
                members, rows, future = group(
                    payload, symbol, decision, contexts.get(symbol)
                )
                original = paired_baseline(indexed, symbol, decision, rows[0])
            except ValueError as error:
                record["reason"] = str(error)
                continue
            record.update(
                members=members,
                context_evidence=contexts[symbol],
                context_hash=base.digest(rows),
                horizon_session=future[-1],
                last_known_at=rows[0][-1]["available_at"],
                univariate_predicted_excess_return=original["predicted_excess_return"],
                univariate_forecast=original["forecast"],
            )
            try:
                predictions = engine.predict(rows, future)
                if predictions.shape != (len(members), base.HORIZON):
                    raise ValueError("invalid_joint_output_shape")
                target_return = predictions[0, -1] / rows[0][-1]["close"] - 1
                spy = members.index("SPY")
                spy_return = predictions[spy, -1] / rows[spy][-1]["close"] - 1
                record.update(
                    status="forecast",
                    native_shapes=getattr(engine, "shapes", {}),
                    forecast=predictions[0].tolist(),
                    channel_forecasts={
                        m: predictions[i].tolist() for i, m in enumerate(members)
                    },
                    predicted_return=float(target_return),
                    predicted_excess_return=float(target_return - spy_return),
                )
            except (ImportError, OSError, RuntimeError, ValueError) as error:
                record.update(status="model_error", reason=type(error).__name__)
    return {
        "protocol": PROTOCOL,
        "symbols": symbols,
        "decisions": payload["decisions"],
        "profile": profile(name),
        "profile_digest": base.digest(profile(name)),
        "checkpoint": asdict(engine.spec),
        "records": records,
        "input_sha256": input_sha256,
        "source_revision": payload.get("source_revision"),
        "baseline_digest": base.digest(baseline),
        "context_evidence_digest": base.digest(contexts),
        "runtime": engine.runtime,
        "native_shapes": getattr(engine, "shapes", {}),
        "availability_mode": payload.get("availability_mode"),
        "data_mode": payload.get("data_mode"),
        "device": "cpu",
        "seed": 0,
        "training_cutoff": "not_verified",
        "production_eligible": False,
        "license_allows_production": name != "timesfm3",
        "interpretation": "post_checkpoint_retrospective_joint_context_diagnostic",
    }


# Authenticate joint forecast content before the funded evaluator consumes it.
def validate_artifact(
    payload: dict, artifact: dict, contexts: dict, baseline: dict
) -> dict:
    name = artifact.get("checkpoint", {}).get("name")
    if name not in MODELS:
        raise ValueError("unsupported_joint_checkpoint")
    expected = profile(name)
    if (
        artifact.get("protocol") != PROTOCOL
        or artifact.get("checkpoint") != asdict(base.CHECKPOINTS[name])
        or artifact.get("profile") != expected
        or artifact.get("profile_digest") != base.digest(expected)
        or artifact.get("context_evidence_digest") != base.digest(contexts)
        or artifact.get("baseline_digest") != base.digest(baseline)
        or artifact.get("decisions") != payload.get("decisions")
        or artifact.get("source_revision") != payload.get("source_revision")
        or artifact.get("availability_mode") != payload.get("availability_mode")
        or artifact.get("data_mode") != payload.get("data_mode")
        or artifact.get("device") != "cpu"
        or artifact.get("seed") != 0
    ):
        raise ValueError("joint_artifact_identity_mismatch")
    indexed_baseline = baseline_index(
        payload, baseline, name, artifact.get("input_sha256")
    )
    symbols = artifact.get("symbols")
    if (
        not isinstance(symbols, list)
        or not symbols
        or len(set(symbols)) != len(symbols)
    ):
        raise ValueError("invalid_joint_cohort")
    has_forecast = any(
        r.get("status") == "forecast" for r in artifact.get("records", [])
    )
    if (has_forecast and not artifact.get("runtime")) or artifact.get(
        "production_eligible"
    ) is not False:
        raise ValueError("missing_joint_runtime_or_invalid_production_gate")
    expected_keys = {(d, s) for d in payload["decisions"] for s in symbols}
    indexed = {}
    for record in artifact.get("records", []):
        key = (record.get("decision"), record.get("symbol"))
        if key in indexed or key not in expected_keys or record.get("model") != name:
            raise ValueError("duplicate_or_unknown_joint_opportunity")
        indexed[key] = record
        _validate_record(payload, record, contexts, indexed_baseline, name)
    if set(indexed) != expected_keys:
        raise ValueError("missing_joint_opportunities")
    return indexed


# Distinguish unavailable inputs from a retained native inference failure.
def _validated_inputs(
    payload: dict, record: dict, contexts: dict, baseline: dict, name: str
) -> tuple | None:
    symbol, decision = record["symbol"], record["decision"]
    status = record.get("status")
    if status not in ("forecast", "unavailable", "model_error"):
        raise ValueError("invalid_joint_status")
    if decision < base.CHECKPOINTS[name].available_on:
        if (
            status != "unavailable"
            or record.get("reason") != "checkpoint_not_available"
        ):
            raise ValueError("forecast_before_checkpoint")
        return None
    try:
        members, rows, future = group(payload, symbol, decision, contexts.get(symbol))
        original = paired_baseline(baseline, symbol, decision, rows[0])
    except ValueError as error:
        if status != "unavailable" or record.get("reason") != str(error):
            raise ValueError("joint_unavailability_evidence_mismatch") from error
        return None
    if status == "unavailable":
        raise ValueError("joint_opportunity_falsely_unavailable")
    return members, rows, future, original


# Reconstruct each causal group and check every forecast's prices and relative units.
def _validate_record(
    payload: dict, record: dict, contexts: dict, baseline: dict, name: str
) -> None:
    inputs = _validated_inputs(payload, record, contexts, baseline, name)
    if inputs is None:
        return
    members, rows, future, original = inputs
    symbol = record["symbol"]
    status = record["status"]
    if (
        record.get("members") != members
        or record.get("context_hash") != base.digest(rows)
        or record.get("context_evidence") != contexts[symbol]
        or record.get("horizon_session") != future[-1]
        or record.get("last_known_at") != rows[0][-1]["available_at"]
        or record.get("univariate_forecast") != original["forecast"]
        or record.get("univariate_predicted_excess_return")
        != original["predicted_excess_return"]
    ):
        raise ValueError("joint_record_context_mismatch")
    if status == "model_error":
        if not isinstance(record.get("reason"), str) or not record["reason"]:
            raise ValueError("invalid_joint_model_error")
        return
    channels = record.get("channel_forecasts", {})
    if set(channels) != set(members):
        raise ValueError("joint_channel_identity_mismatch")
    values = np.array([channels[m] for m in members], dtype=float)
    if (
        values.shape != (len(members), base.HORIZON)
        or not np.isfinite(values).all()
        or (values <= 0).any()
    ):
        raise ValueError("invalid_joint_forecast_values")
    target = float(values[0, -1] / rows[0][-1]["close"] - 1)
    spy = members.index("SPY")
    excess = float(target - (values[spy, -1] / rows[spy][-1]["close"] - 1))
    native = [len(members), base.HORIZON, 1 if name == "chronos2" else 9]
    expected_shapes = {
        "input": [len(members), base.CONTEXT],
        "native_output": native,
        "median_output": [len(members), base.HORIZON],
    }
    if (
        record.get("forecast") != channels[symbol]
        or record.get("native_shapes") != expected_shapes
        or record.get("predicted_return") != target
        or record.get("predicted_excess_return") != excess
    ):
        raise ValueError("joint_forecast_units_or_shape_mismatch")
