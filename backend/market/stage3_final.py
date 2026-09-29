"""Stage 3's M3 frozen for use after the walk-forward: fit once, save, load, forecast.

`docs/research/laggard-shadow-plan-2026-09-29.md` registers what this does.
The frozen model is M3 on T-S1 exactly as `stage3_nn` trains it, fitted as
the walk-forward's *next* refit (`next_fold`): the fold whose test block
would begin after the dataset's last session. Every configuration of the
registered grid is trained with the first seed and scored on the validation
block with the registered selection score; the best is trained with the
remaining seeds; each network keeps its early-stopped weights.

It uses `stage3_nn`'s own task, scaling, training and prediction functions
rather than copies of them, so the frozen model cannot drift from the
walk-forward's. That module is the registration's code and is not edited
for this; the private names imported below are a deliberate dependency.

A saved model (`save_final`) holds only tensors and plain values:
- every seed's weights;
- the fit part's channel medians and IQRs;
- the daily branch's medians and IQRs;
- the configuration;
- the daily column names in order;
- a meta record.

`load_final` reads it with torch's weights-only loader. `predict_final`
forecasts any rows of a T-S1 dataset whose daily columns are the model's
own, from a sequence tensor, as the mean over the seeds. It refuses a
dataset whose columns differ, and returns NaN for a row without a window.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from backend.market import stage3_io as io
from backend.market import stage3_nn as nn3

FORMAT = "stage3-final/1"


@dataclass(frozen=True)
class FinalModel:
    """A frozen M3 fit: every seed's weights and the scaling they expect."""

    kind: str
    config: dict[str, Any]
    seeds: tuple[int, ...]
    state_dicts: tuple[dict[str, Any], ...]  # one per seed, torch tensors
    channel_median: np.ndarray  # (C,)
    channel_iqr: np.ndarray  # (C,)
    daily_median: np.ndarray  # (F,)
    daily_iqr: np.ndarray  # (F,)
    daily_columns: tuple[str, ...]  # the dataset's daily column names, in order
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FitResult:
    """A fitted frozen model and what its parity check needs."""

    model: FinalModel
    validation_rows: np.ndarray  # (V,) dataset rows of the validation block
    validation_forecast: np.ndarray  # (V,) the fit's own mean-over-seeds forecast


# The walk-forward's next fold for `n_sessions` sessions: the test block
# would begin after the last session, so the window is [0, n - gap), its
# last `validation` sessions validate, and the fit part ends `gap` sessions
# before them - `io.folds`'s arithmetic at test_start = n_sessions.
def next_fold(n_sessions: int, gap: int, validation: int) -> io.Fold:
    """Return the fold a refit after the last session trains on."""
    if gap < 0 or validation <= 0:
        raise ValueError("gap must be non-negative and validation positive")
    window_end = n_sessions - gap
    val_start = window_end - validation
    fit_end = val_start - gap
    if fit_end <= 0:
        raise ValueError(
            f"{n_sessions} sessions leave no fit part (gap {gap}, validation {validation})"
        )
    return io.Fold(n_sessions, n_sessions, window_end, fit_end, val_start)


# The daily column names a dataset's `daily_columns` select, in order.
def daily_names(data: io.Stage3Data) -> tuple[str, ...]:
    """Return the names of the dataset's daily columns."""
    return tuple(data.feature_names[i] for i in io.daily_columns(data.feature_names))


# Fit the frozen model on a T-S1 dataset and its sequence tensor: the
# registered grid on `next_fold`, the best configuration by validation
# score, every seed of it. Returns the model and the fit's own validation
# forecasts for the parity check.
def fit_final(
    data: io.Stage3Data,
    tensor: io.SeqTensor,
    settings: nn3.Settings | None = None,
    log: Callable[[str], None] | None = None,
) -> FitResult:
    """Return the frozen M3 fit of `data`."""
    nn3._require_torch()
    torch = nn3.torch
    settings = settings or nn3.Settings()
    io.validate(data)
    if data.kind != io.S1:
        raise ValueError(f"the frozen model answers T-S1, not {data.kind!r}")
    started = time.perf_counter()
    task = nn3._SeqTask(data, tensor, settings)
    device = torch.device(nn3.resolve_device(settings.device))
    sessions, index = io.session_index(data.dates)
    gap = nn3._pick(settings.gap, io.GAP[task.kind])
    fold = next_fold(len(sessions), gap, settings.validation)
    unit_session = index[task.units.first]
    fit, val, _ = nn3._split(task, unit_session, fold)
    if not len(fit) or not len(val):
        raise ValueError(f"{len(fit)} fit and {len(val)} validation units; the fit needs both")
    seeds = tuple(int(s) for s in settings.seeds)
    grid = task.grid()
    configs: list[dict[str, Any]] = []
    models: list[Any] = []
    forecasts: list[np.ndarray] = []
    with nn3.deterministic_torch():
        state = task.prepare(fold, sessions, fit, device)
        batch = task.plan(grid[0]).eval_batch
        for c, config in enumerate(grid):
            model, record = nn3._train(task, state, config, seeds[0], fit, val, device)
            forecast = nn3._predict(task, state, model, val, batch, device)
            record["score"] = nn3._score(task, data, val, forecast)
            configs.append({"config": dict(config), **record})
            models.append(model)
            forecasts.append(forecast)
            nn3._say(log, nn3._config_line(f"config {c + 1}/{len(grid)}", config, record))
        chosen = nn3._choose([r["score"] for r in configs])
        kept = [models[chosen]]
        per_seed = [forecasts[chosen]]
        seed_runs = [configs[chosen]]
        for seed in seeds[1:]:
            model, record = nn3._train(task, state, grid[chosen], seed, fit, val, device)
            kept.append(model)
            per_seed.append(nn3._predict(task, state, model, val, batch, device))
            seed_runs.append({"config": dict(grid[chosen]), **record})
            nn3._say(log, nn3._config_line("chosen", grid[chosen], record))
    daily_median, daily_iqr = nn3.robust_stats(task.daily[fit])
    rows = task.units.rows[val][:, 0]
    meta = {
        "format": FORMAT,
        "module": __name__,
        "plan": "docs/research/laggard-shadow-plan-2026-09-29.md",
        "registered": settings.registered(),
        "fold": {
            "sessions": len(sessions),
            "fit": [0, fold.fit_end],
            "validation": [fold.val_start, fold.window_end],
            "fit_end": str(sessions[fold.fit_end - 1]),
            "validation_dates": [str(sessions[fold.val_start]), str(sessions[fold.window_end - 1])],
            "last_session": str(sessions[-1]),
            "gap": gap,
        },
        "units": {"fit": len(fit), "validation": len(val)},
        "configs": configs,
        "chosen": chosen,
        "seed_runs": [
            {k: r[k] for k in ("seed", "epochs", "best_epoch", "val_loss", "seconds")}
            for r in seed_runs
        ],
        "device": str(device),
        "torch": torch.__version__,
        "inputs": task.counts,
        "seconds": time.perf_counter() - started,
    }
    model = FinalModel(
        kind=task.kind,
        config=dict(grid[chosen]),
        seeds=seeds,
        state_dicts=tuple(nn3._snapshot(m) for m in kept),
        channel_median=np.asarray(state.record["channel_median"], dtype=np.float64),
        channel_iqr=np.asarray(state.record["channel_iqr"], dtype=np.float64),
        daily_median=np.asarray(daily_median, dtype=np.float64),
        daily_iqr=np.asarray(daily_iqr, dtype=np.float64),
        daily_columns=daily_names(data),
        meta=nn3._json_ready(meta),
    )
    mean = np.mean(np.stack([f[:, 0] for f in per_seed]), axis=0)
    return FitResult(model, rows.astype(np.int64), mean)


# Write a frozen model with tensors and plain values only; returns the
# file's sha256, the model's id.
def save_final(path: Path, model: FinalModel) -> str:
    """Write `model` to `path` and return the file's sha256."""
    nn3._require_torch()
    torch = nn3.torch
    payload = {
        "format": FORMAT,
        "kind": model.kind,
        "config": {k: (float(v) if isinstance(v, float) else int(v)) for k, v in model.config.items()},
        "seeds": [int(s) for s in model.seeds],
        "state_dicts": [{k: v.detach().cpu() for k, v in sd.items()} for sd in model.state_dicts],
        "channel_median": torch.as_tensor(model.channel_median, dtype=torch.float64),
        "channel_iqr": torch.as_tensor(model.channel_iqr, dtype=torch.float64),
        "daily_median": torch.as_tensor(model.daily_median, dtype=torch.float64),
        "daily_iqr": torch.as_tensor(model.daily_iqr, dtype=torch.float64),
        "daily_columns": list(model.daily_columns),
        "meta_json": _dumps(model.meta),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, path)
    return sha256(path)


# The meta record as strict JSON text (the weights-only loader reads strings).
def _dumps(meta: dict[str, Any]) -> str:
    import json

    return json.dumps(io.clean_json(meta), sort_keys=True)


# A file's sha256, hex.
def sha256(path: Path) -> str:
    """Return the sha256 of the file at `path`."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Read a frozen model written by `save_final`, with the weights-only loader.
def load_final(path: Path) -> FinalModel:
    """Return the FinalModel stored at `path`."""
    import json

    nn3._require_torch()
    torch = nn3.torch
    payload = torch.load(Path(path), map_location="cpu", weights_only=True)
    if payload.get("format") != FORMAT:
        raise ValueError(f"{path}: format {payload.get('format')!r}, expected {FORMAT!r}")
    return FinalModel(
        kind=str(payload["kind"]),
        config=dict(payload["config"]),
        seeds=tuple(int(s) for s in payload["seeds"]),
        state_dicts=tuple(dict(sd) for sd in payload["state_dicts"]),
        channel_median=payload["channel_median"].numpy(),
        channel_iqr=payload["channel_iqr"].numpy(),
        daily_median=payload["daily_median"].numpy(),
        daily_iqr=payload["daily_iqr"].numpy(),
        daily_columns=tuple(str(c) for c in payload["daily_columns"]),
        meta=json.loads(payload["meta_json"]),
    )


# Forecast rows of a T-S1 dataset with a frozen model: the fit's windows,
# daily inputs and scaling, each seed's network in eval mode, the mean over
# seeds. A row without a window in the tensor gets NaN.
def predict_final(
    model: FinalModel,
    data: io.Stage3Data,
    tensor: io.SeqTensor,
    rows: Sequence[int] | np.ndarray,
    device: str = "cpu",
    batch: int = 512,
) -> np.ndarray:
    """Return the (len(rows),) mean-over-seeds forecasts of `rows`."""
    nn3._require_torch()
    torch = nn3.torch
    if data.kind != model.kind:
        raise ValueError(f"the model answers {model.kind!r}, the data is {data.kind!r}")
    names = daily_names(data)
    if names != model.daily_columns:
        raise ValueError("the dataset's daily columns are not the model's")
    rows = np.asarray(rows, dtype=np.int64)
    out = np.full(len(rows), np.nan)
    if not len(rows):
        return out
    task = nn3._SeqTask(data, tensor, nn3.Settings(device=device))
    units = task.units.of_row[rows]
    ok = (units >= 0) & task.usable[np.maximum(units, 0)]
    if not ok.any():
        return out
    target = torch.device(nn3.resolve_device(device))
    state = nn3._SeqState(
        median=torch.as_tensor(model.channel_median, dtype=torch.float32, device=target),
        scale=torch.as_tensor(model.channel_iqr, dtype=torch.float32, device=target),
        daily=nn3.daily_inputs(task.daily, model.daily_median, model.daily_iqr),
        targets=np.full(task.units.targets.shape, np.nan, dtype=np.float32),
        y_scale=1.0,
        record={},
    )
    chosen = units[ok]
    per_seed = []
    with nn3.deterministic_torch():
        for weights in model.state_dicts:
            network = task.build(model.config).to(target)
            network.load_state_dict(weights)
            per_seed.append(nn3._predict(task, state, network, chosen, batch, target)[:, 0])
    out[ok] = np.mean(np.stack(per_seed), axis=0)
    return out
