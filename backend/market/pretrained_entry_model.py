"""Pinned CPU-only Chronos-2 challenger; bounded quantile proxies, not live orders."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import numpy as np

MODEL_ID = "amazon/chronos-2"
MODEL_REVISION = "95a9710e2596287d08352589f42634fa5abdf0a7"
MODEL_UPLOAD_DATE = "2025-10-30"
QUANTILES = tuple(np.arange(1, 10) / 10)
CONTEXT_LENGTH = 2048
ARTIFACT_HASHES = {
    "config.json": "ef1143bfdc9c0376d9a056eefca46cb4b1ec3d0ffacd541ff56feb40fb708031",
    "model.safetensors": (
        "ddcda3c7508bf2528087723e98a20707cc04b7f370ae275a9fd88078ddba4f42"
    ),
}


@dataclass(frozen=True)
class EntryForecast:
    status: str
    mean_log_return: float = float("nan")
    second_moment_proxy: float = float("nan")
    waiting_advantage: float = float("nan")
    reason: str = ""
    calibrated_risk: bool = False
    endpoint: str = "regular-close-proxy"


# Chain completed raw session ratios without consulting later adjusted closes.
def causal_log_context(
    opens: list[np.ndarray],
    closes: list[np.ndarray],
    prior_closes: np.ndarray,
    completed_bar: int,
) -> np.ndarray:
    if not opens or len(opens) != len(closes) or len(opens) != len(prior_closes):
        raise ValueError("session arrays must be nonempty and aligned")
    if not isinstance(completed_bar, (int, np.integer)) or completed_bar not in range(
        25
    ):
        raise ValueError("decision requires a following regular execution open")
    accumulated: list[np.ndarray] = []
    anchor = 0.0
    for i, (session_open, session_close, prior) in enumerate(
        zip(opens, closes, prior_closes, strict=True)
    ):
        count = completed_bar + 1 if i == len(opens) - 1 else 26
        o = np.asarray(session_open, dtype=float)
        c = np.asarray(session_close, dtype=float)
        if o.shape != (26,) or c.shape != (26,):
            raise ValueError("only declared full regular-session grids are supported")
        observed = np.column_stack((o[:count], c[:count])).reshape(-1)
        if not np.isfinite(prior) or prior <= 0:
            raise ValueError("missing or invalid same-session raw prior close")
        if not np.all(np.isfinite(observed)) or np.any(observed <= 0):
            raise ValueError("observed prefix contains invalid prices")
        chained = anchor + np.log(observed / prior)
        accumulated.append(chained)
        anchor = float(chained[-1])
    context = np.concatenate(accumulated)[-CONTEXT_LENGTH:]
    return context - context[-1]


# Convert marginal log-price quantiles into explicitly approximate trading outputs.
def forecast_from_quantiles(
    values: np.ndarray, completed_bar: int, context: np.ndarray
) -> EntryForecast:
    if not isinstance(completed_bar, (int, np.integer)) or completed_bar not in range(
        25
    ):
        return EntryForecast("unavailable", reason="invalid decision bar")
    horizon = 2 * (25 - completed_bar + 260)
    q = np.asarray(values, dtype=float)
    history = np.asarray(context, dtype=float)
    if q.shape != (horizon, 9):
        return EntryForecast("unavailable", reason="invalid forecast clock or shape")
    if history.ndim != 1 or len(history) < 104 or not np.all(np.isfinite(history)):
        return EntryForecast("unavailable", reason="insufficient finite causal context")
    if not np.all(np.isfinite(q)) or np.any(np.diff(q, axis=1) < 0):
        return EntryForecast("unavailable", reason="invalid or crossing quantiles")
    entry, wait, terminal = q[0], q[4 if completed_bar == 24 else 2], q[-1]
    mean = float(np.mean(terminal) - np.mean(entry))
    wait_advantage = float(np.mean(entry) - np.mean(wait))
    marginal_risk = float((np.std(terminal) + np.std(entry)) ** 2)
    observed_risk = float(np.var(np.diff(history), ddof=1) * (horizon - 1))
    second = mean * mean + max(marginal_risk, observed_risk)
    if not np.all(np.isfinite([mean, second, wait_advantage])):
        return EntryForecast("unavailable", reason="nonfinite forecast moments")
    return EntryForecast("available", mean, second, wait_advantage)


# Refuse any local or downloaded bytes that differ from the registered public artifact.
def verify_artifacts(directory: str | Path) -> dict[str, str]:
    root = Path(directory)
    hashes = {
        name: sha256((root / name).read_bytes()).hexdigest() for name in ARTIFACT_HASHES
    }
    if hashes != ARTIFACT_HASHES:
        raise ValueError("weights/config do not match the pinned artifact")
    return hashes


class PretrainedEntryModel:
    # Keep inference independent from an optional pinned CPU pipeline loader.
    def __init__(self, predict_quantiles: Callable, provenance: dict | None = None):
        self.predict_quantiles = predict_quantiles
        self.provenance = dict(provenance or {})

    # Forecast only the supplied observed context and preserve explicit failure reasons.
    def forecast(self, context: np.ndarray, completed_bar: int) -> EntryForecast:
        x = np.asarray(context, dtype=np.float32)
        if not isinstance(
            completed_bar, (int, np.integer)
        ) or completed_bar not in range(25):
            return EntryForecast("unavailable", reason="invalid decision bar")
        if x.ndim != 1 or len(x) < 104 or not np.all(np.isfinite(x)):
            return EntryForecast(
                "unavailable", reason="insufficient finite causal context"
            )
        x = x[-CONTEXT_LENGTH:].copy()
        x -= x[-1]
        horizon = 2 * (25 - completed_bar + 260)
        try:
            values = self.predict_quantiles(x, horizon, QUANTILES)
        except (RuntimeError, ValueError, ImportError, OSError) as exc:
            return EntryForecast(
                "unavailable", reason=f"inference failed: {type(exc).__name__}"
            )
        return forecast_from_quantiles(values, completed_bar, x)

    # Load only publisher-pinned data weights into CPU without remote Python execution.
    @classmethod
    def load(
        cls, cache_dir: str | Path, local_directory: str | Path | None = None
    ) -> "PretrainedEntryModel":
        try:
            import torch
            from chronos import Chronos2Pipeline
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise RuntimeError(
                "optional chronos-forecasting CPU dependency is unavailable"
            ) from exc
        torch.set_num_threads(2)
        directory = (
            Path(local_directory)
            if local_directory is not None
            else Path(
                snapshot_download(
                    repo_id=MODEL_ID,
                    revision=MODEL_REVISION,
                    cache_dir=str(cache_dir),
                    allow_patterns=["config.json", "model.safetensors"],
                )
            )
        )
        hashes = verify_artifacts(directory)
        pipeline = Chronos2Pipeline.from_pretrained(
            str(directory),
            device_map="cpu",
            torch_dtype=torch.float32,
        )

        # Use the real tensor API while explicitly selecting the only target variate.
        def predict(context: np.ndarray, horizon: int, quantiles: tuple) -> np.ndarray:
            with torch.inference_mode():
                forecasts, _ = pipeline.predict_quantiles(
                    inputs=[torch.from_numpy(context)],
                    prediction_length=horizon,
                    quantile_levels=list(quantiles),
                    context_length=CONTEXT_LENGTH,
                    batch_size=1,
                    cross_learning=False,
                )
            return forecasts[0][0].cpu().numpy()

        return cls(
            predict,
            {
                "model_id": MODEL_ID,
                "revision": MODEL_REVISION,
                "artifact_upload_date": MODEL_UPLOAD_DATE,
                "artifact_hashes": hashes,
                "torch_version": torch.__version__,
                "device": "cpu",
                "threads": 2,
                "pretraining_observation_cutoff": "unknown",
                "risk": "bounded-quantile-proxy",
            },
        )


# Build the consecutive observed suffix without bridging a missing trading session.
def _context_for_day(cube, dates: np.ndarray, lookup: dict, day: int) -> tuple:
    indices = [lookup.get(date) for date in dates[max(0, day - 39) : day + 1]]
    missing = [i for i, index in enumerate(indices) if index is None]
    if missing:
        indices = indices[missing[-1] + 1 :]
    if len(indices) < 3:
        return None, "insufficient-consecutive-context"
    try:
        return causal_log_context(
            [cube.open[index] for index in indices],
            [cube.close[index] for index in indices],
            np.asarray([cube.prior_close[index] for index in indices]),
            9,
        ), ""
    except ValueError:
        return None, "invalid-causal-context"


# Verify shared identities, calendars and output ownership before expensive inference.
def _validate_history_inputs(panel, valid, output_path, source_identity) -> tuple:
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    names = tuple(panel.tickers)
    shape = (len(dates), 25, len(names))
    if np.asarray(valid).shape != shape:
        raise ValueError("validity must match the shared decision calendar and book")
    if np.asarray(valid).dtype != np.dtype(bool):
        raise ValueError("shared observation validity must be an explicit boolean mask")
    if not source_identity or any(not value for value in source_identity.values()):
        raise ValueError("original snapshot and cube source identities are required")
    if (
        len(dates) == 0
        or np.any(np.isnat(dates))
        or np.any(np.diff(dates).astype(int) <= 0)
    ):
        raise ValueError("panel dates must be unique and increasing")
    if Path(output_path).exists():
        raise FileExistsError("a frozen prediction artifact already exists")
    return dates, names, shape


# Score the fixed post-artifact holdout clock while retaining every unavailable row.
def historical_forecasts(
    panel,
    cubes: dict,
    valid: np.ndarray,
    output_path: str | Path,
    *,
    source_identity: dict,
    model: PretrainedEntryModel,
    progress: Callable | None = None,
) -> dict:
    dates, names, shape = _validate_history_inputs(
        panel, valid, output_path, source_identity
    )
    predictions = np.full((*shape, 3), np.nan, dtype=np.float32)
    reasons = np.full((len(dates), len(names)), "outside-fixed-cohort", dtype="U48")
    holdout = np.flatnonzero(
        (dates >= np.datetime64("2026-08-17")) & (dates <= np.datetime64("2026-09-30"))
    )
    started = time.monotonic()
    for stock, name in enumerate(names):
        if name in ("SPY", "QQQ"):
            reasons[holdout, stock] = "benchmark-reference"
            continue
        cube = cubes.get(name)
        if cube is None:
            reasons[holdout, stock] = "missing-cube"
            continue
        cube_dates = np.asarray(cube.dates, dtype="datetime64[D]")
        if np.any(np.isnat(cube_dates)) or np.any(np.diff(cube_dates).astype(int) <= 0):
            raise ValueError("cube dates must be unique and increasing")
        lookup = {date: row for row, date in enumerate(cube_dates)}
        for day in holdout:
            if not valid[day, 9, stock]:
                reasons[day, stock] = "shared-observation-unavailable"
                continue
            context, reason = _context_for_day(cube, dates, lookup, day)
            if context is None:
                reasons[day, stock] = reason
                continue
            forecast = model.forecast(context, 9)
            reasons[day, stock] = forecast.status + ":" + forecast.reason
            if forecast.status == "available":
                predictions[day, 9, stock] = (
                    forecast.mean_log_return,
                    forecast.second_moment_proxy,
                    forecast.waiting_advantage,
                )
        if progress is not None:
            progress({"ticker": name, "elapsed_seconds": time.monotonic() - started})
    requested = len(holdout) * sum(name not in ("SPY", "QQQ") for name in names)
    available = int(np.count_nonzero(np.all(np.isfinite(predictions[:, 9]), axis=-1)))
    metadata = {
        "method": "chronos2-pinned-bounded-quantile-challenger",
        "source_identity": source_identity,
        "model_provenance": model.provenance,
        "input_clock": 9,
        "holdout_start": "2026-08-17",
        "holdout_end": "2026-09-30",
        "requested": requested,
        "available": available,
        "unavailable": requested - available,
        "wall_seconds": time.monotonic() - started,
        "endpoint": "regular-close-proxy",
        "calibrated_risk": False,
        "pre_artifact_oos_claim": False,
        "forecast_sha256": sha256(predictions.tobytes()).hexdigest(),
    }
    with Path(output_path).open("xb") as stream:
        np.savez_compressed(
            stream,
            predictions=predictions,
            reasons=reasons,
            dates=dates,
            tickers=np.asarray(names),
            metadata=np.asarray(json.dumps(metadata)),
        )
    return {"predictions": predictions, "reasons": reasons, "metadata": metadata}
