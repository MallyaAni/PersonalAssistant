"""Stage 4's model adapters: M1, M2 and M3 trained on the timing target.

`docs/research/stage4-plan-2026-09-29.md` ("Rows and the timing target",
"Models") registers what is trained here. Every model is a stage-3 model,
reused from `stage3_trees` and `stage3_nn` without editing them (they are
the stage-3 registration's code); what changes is only what the plan
changes: the target, its scaling, the selection metric, the gap and the
cadence.

**Rows and labels.** Every row of the stage-3 T-S1 export
(`stage3_s1.npz`: one row per graded name-day), in its order. The label is
`g_buy` or `g_sell` in bp, from the stage-4 labels file
(`market_stage4_labels.load`). `timing_data` refuses labels whose (date,
ticker) keys are not the export's, row for row, and `check_labels_source`
refuses a labels file made from another export file. One model is trained
per family per side. A NaN label is forecast and never trained on.

**The walk-forward** (`folds_for`). `stage3_io.folds` with the first test
block at session index 500, validation on the last 252 sessions of each
training window, a gap of 11 sessions at both the fit/validation and the
training/test boundaries, and test blocks of 63 sessions (M1) or 252 (M2,
M3). Runs are deterministic, and every seed's forecast is kept.

**M1, LightGBM** (`run_lgbm`). Stage 3's M1 on a view of the rows as a
``ti`` dataset (`tree_data`: one row per name-day, slot 0, the daily
columns), walked fold by fold with `stage3_trees._run_fold`: the grid, the
fixed settings, early stopping and five seeds as stage 3's M1; L2 on the
label winsorized at the fit rows' 0.5% and 99.5% quantiles; the
configuration chosen by pooled Spearman on the validation block (T-I's
metric). The plan's bagging fraction, 0.7, is applied by `Bagged`, a
stand-in for the lightgbm module handed to `_run_fold`, because
`stage3_trees` reads the fraction by the dataset's kind (0.3 for ``ti``).

**M2, the JKX I20 CNN** (`run_cnn`, `TimingChartTask`). Stage 3's image,
network, Adam at 1e-5, batch 128, patience 2 (at most 100 epochs) and five
networks averaged, with the plan's stated deviation: one regression output
(`JKXRegressor`) instead of the two-class head, MSE on the label
winsorized at the fit rows' quantiles and divided by their standard
deviation, forecasts scaled back to bp. No grid.

**M3, the sequence model** (`run_seq`, `TimingSeqTask`). Stage 3's T-S1
network (sixty sessions of 27 steps, attention pooling, the daily branch),
`SEQ_GRID` under `SEQ_FIXED`, the target standardized and winsorized as
T-I's (`stage3_nn.scaled_targets`' T-I branch), forecasts scaled back to
bp. Seed 0 of every configuration is scored on the validation block by
pooled Spearman; the best configuration is trained with seeds 0-4, and
every network keeps its early-stopped weights.

The networks walk forward in `walk_nets`: `stage3_nn`'s fold procedure
(`_split`, `_train`, `_predict`, `_choose`) with the selection score
replaced by pooled Spearman (`pooled_score`), the stage-4 gap and cadence,
and the stage-4 meta.

**Every forecast** is a `stage3_io.Stage3Forecast` whose keys are the T-S1
rows (kind ``s1``, slot 0): `yhat` the mean of the seeds in bp,
`yhat_seeds`, `yhat_configs` for M1 and M3 (each configuration's first-seed
test forecast, for the PBO diagnostic), `fold`, and a meta record of the
side, the family, every protocol setting and `registered`, which is true
only when every protocol setting is the plan's (the device and thread
count are execution details recorded beside them).

**Decisions the plan left open or reuse forced** (recorded in the meta and
proposed as Addendum 1):

* M1's bagging fraction 0.7 reaches LightGBM through `Bagged`; the rest of
  each M1 fold is stage 3's T-I path unchanged. M1's outer loop is
  `stage3_trees.walk_forward`'s, restated here only to hand `Bagged` to
  `_run_fold` and to write the stage-4 meta; with a fraction of 0.3 it
  reproduces `stage3_trees.walk_forward` bit for bit (a test pins this).
* M1 reads the export's daily (``d_``) columns; on the registered export
  that is all 208 columns, so the selection changes nothing there.
* The networks' fold loop is `stage3_nn._fold`'s with the score function
  as the only change; given stage 3's score it reproduces
  `stage3_nn.run_seq` bit for bit (a test pins this).
* M2 and M3 scale the target with `stage3_nn.scaled_targets`' T-I branch:
  winsorized at the 0.5%/99.5% quantiles (numpy's linear interpolation) of
  the fit units' finite labels - the labelled fit rows that have an input
  (an image or a window) - and divided by the standard deviation (ddof 0)
  of those winsorized labels, without centering. The validation loss uses
  the same transform; the selection score reads the raw labels in bp.
* M2's regression layer is Linear(46,080 -> 1), Xavier-uniform weights and
  a zero bias as stage 3 initializes its layers. It replaces the two-class
  layer after stage 3's constructor has run, so each seed draws stage 3's
  layers first, then the new one. Its loss is stage 3's masked MSE
  (`stage3_nn._SeqTask.loss`). With one configuration its validation score
  chooses nothing, and it is recorded by pooled Spearman like the others.
* The forecasts' `kind` is ``s1`` for all three families, because their
  keys are the T-S1 rows. The file's `plan` key is `stage3_io`'s own
  (`save_forecast` writes it); the stage-4 plan is under `stage4_plan`.
* A run cut short by `max_folds` is not registered (stage 3's M1 wrote such
  a run as registered with `complete` false).
* A walk-forward with no test block, or `max_folds` below 1, is an error
  for every family.
* The stage-3 relative return `extra["r"]` is dropped from the stage-4
  datasets, so no stage-3 label can reach a stage-4 model by mistake.
  Labels of +-inf are refused; only NaN means unlabelled.
"""

from __future__ import annotations

import dataclasses
import os
import platform
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

import numpy as np

from backend.market import stage3_io as io
from backend.market import stage3_nn as nn3
from backend.market import stage3_trees as trees

MODULE = "backend.market.stage4_models"
PLAN = "docs/research/stage4-plan-2026-09-29.md"
SIDES = ("buy", "sell")
# The three families, as stage3_io names them.
FAMILIES = (io.LGBM, io.CNN_I20, io.SEQ)
MODELS = {io.LGBM: "M1", io.CNN_I20: "M2", io.SEQ: "M3"}
# The walk-forward: purge 6 (t+1..t+5, then the fill) plus a 5-session
# embargo, and the test-block length per family.
GAP = 11
REFIT = {io.LGBM: 63, io.CNN_I20: 252, io.SEQ: 252}
# M1's bagging fraction, as the plan fixes it.
LGBM_BAGGING = 0.7
# The registered export, `stage3_s1.npz`, by the start of its sha256.
REGISTERED_EXPORT = "7fa24f7e"
# The selection metric of every family: pooled Spearman (T-I's).
METRIC = "pooled_spearman"
# Extras of the export that are stage-3 labels and never reach a model here.
DROPPED_EXTRAS = ("r",)
TARGET_SCALING = (
    "the label in bp, winsorized at the fit units' 0.5%/99.5% quantiles and"
    " divided by the std (ddof 0) of those winsorized labels, not centred"
    " (stage3_nn.scaled_targets, T-I branch); forecasts x that std = bp"
)


# ---------------------------------------------------------------------------
# Rows and labels (numpy only)
# ---------------------------------------------------------------------------


# Refuse labels whose (date, ticker) keys are not the export's, row for row.
def check_keys(data: io.Stage3Data, dates: np.ndarray, tickers: np.ndarray) -> None:
    """Raise ValueError unless the label keys are the export's rows, in order."""
    dates = np.asarray(dates, dtype="datetime64[D]")
    tickers = np.asarray(tickers).astype(str)
    if len(dates) != len(data) or len(tickers) != len(data):
        raise ValueError(
            f"the labels hold {len(dates)} dates and {len(tickers)} tickers;"
            f" the export has {len(data)} rows"
        )
    own_dates = np.asarray(data.dates, dtype="datetime64[D]")
    own_tickers = np.asarray(data.tickers).astype(str)
    wrong = (dates != own_dates) | (tickers != own_tickers)
    if wrong.any():
        first = int(np.flatnonzero(wrong)[0])
        raise ValueError(
            f"{int(wrong.sum())} label rows are not the export's rows; the first is row"
            f" {first}: labels ({dates[first]}, {tickers[first]}), export"
            f" ({own_dates[first]}, {own_tickers[first]})"
        )


# Refuse a labels file that was not made from this export file: its meta
# must carry the sha256 of the export the labels command read.
def check_labels_source(labels_meta: Mapping[str, Any], s1_sha256: str) -> None:
    """Raise ValueError unless the labels were made from the export with `s1_sha256`."""
    made_from = labels_meta.get("s1_sha256")
    if made_from != s1_sha256:
        raise ValueError(
            f"the labels were made from the export with sha256 {made_from!r},"
            f" not this one ({s1_sha256})"
        )


# The stage-4 dataset of one side: the export's rows, columns and keys with
# y = that side's timing label in bp (NaN where unpriced). The export's
# stage-3 label extras are dropped; the side is recorded in the meta, which
# the runners require.
def timing_data(
    data: io.Stage3Data,
    dates: np.ndarray,
    tickers: np.ndarray,
    g_buy: np.ndarray,
    g_sell: np.ndarray,
    side: str,
) -> io.Stage3Data:
    """Return the T-S1 rows with y = g_buy or g_sell (bp)."""
    if data.kind != io.S1:
        raise ValueError(f"stage 4 trains on the T-S1 rows, not {data.kind!r} rows")
    if side not in SIDES:
        raise ValueError(f"side must be one of {SIDES}, not {side!r}")
    check_keys(data, dates, tickers)
    label = np.asarray(g_buy if side == "buy" else g_sell, dtype=np.float64)
    if label.shape != (len(data),):
        raise ValueError(
            f"the {side} labels are {label.shape}; expected ({len(data)},)"
        )
    if np.isinf(label).any():
        raise ValueError(f"{int(np.isinf(label).sum())} {side} labels are infinite")
    y = label.astype(np.float32)
    extra = {k: v for k, v in data.extra.items() if k not in DROPPED_EXTRAS}
    stage4 = {
        "plan": PLAN,
        "side": side,
        "target": f"g_{side}",
        "units": "bp",
        "rows": len(data),
        "labelled": int(np.count_nonzero(np.isfinite(y))),
    }
    out = io.Stage3Data(
        kind=io.S1,
        dates=np.asarray(data.dates, dtype="datetime64[D]"),
        tickers=np.asarray(data.tickers),
        slot=np.asarray(data.slot, dtype=np.int8),
        x=data.x,
        feature_names=tuple(data.feature_names),
        y=y,
        extra=extra,
        meta={"stage4": stage4},
    )
    io.validate(out)
    return out


# M1's view of a stage-4 dataset: the same rows and label as a ``ti``
# dataset (one row per name-day, slot 0), so stage3_trees winsorizes the
# label at the fit rows' quantiles and chooses by pooled Spearman; the
# columns are the daily block (all of them, on the registered export).
def tree_data(data: io.Stage3Data) -> io.Stage3Data:
    """Return the ``ti`` view of the rows over the daily columns."""
    columns = io.daily_columns(data.feature_names)
    if not len(columns):
        raise ValueError(f"the data has no {io.DAILY_PREFIX!r} daily column")
    every = len(columns) == data.x.shape[1]
    view = dataclasses.replace(
        data,
        kind=io.TI,
        x=data.x if every else np.ascontiguousarray(data.x[:, columns]),
        feature_names=tuple(data.feature_names[i] for i in columns),
    )
    io.validate(view)
    return view


# The stage-4 record a dataset built by `timing_data` carries; a runner
# refuses any other dataset, so a stage-3 label can never be trained here.
def _stage4_record(data: io.Stage3Data) -> dict[str, Any]:
    record = data.meta.get("stage4")
    if not isinstance(record, Mapping) or record.get("side") not in SIDES:
        raise ValueError(
            "the dataset is not a stage-4 timing dataset (build it with timing_data)"
        )
    return dict(record)


# The walk-forward of a family over `n_sessions` sessions: stage3_io.folds
# with the stage-4 cadence and gap unless a smoke run overrides them.
def folds_for(
    family: str,
    n_sessions: int,
    *,
    min_train: int = io.MIN_TRAIN,
    validation: int = io.VALIDATION,
    refit: int | None = None,
    gap: int | None = None,
) -> list[io.Fold]:
    """Return the folds a family walks over `n_sessions` sessions."""
    if family not in FAMILIES:
        raise ValueError(f"family must be one of {FAMILIES}, not {family!r}")
    return io.folds(
        n_sessions,
        REFIT[family] if refit is None else int(refit),
        GAP if gap is None else int(gap),
        min_train,
        validation,
    )


# ---------------------------------------------------------------------------
# The protocol and whether a run is the registered one (numpy only)
# ---------------------------------------------------------------------------


# M1's settings for a stage-4 run: the given ones (stage 3's registered M1
# by default) with the stage-4 cadence and gap wherever they are left open.
def lgbm_settings(settings: trees.Settings | None = None) -> trees.Settings:
    """Return the M1 settings with refit and gap resolved."""
    settings = trees.Settings() if settings is None else settings
    return dataclasses.replace(
        settings,
        refit=REFIT[io.LGBM] if settings.refit is None else int(settings.refit),
        gap=GAP if settings.gap is None else int(settings.gap),
    )


# M1's protocol as plain values: stage 3's description of the settings
# (cadence and gap resolved), the bagging fraction, the fold cut, the label
# winsorization and the selection metric. The thread count is not part of it.
def lgbm_protocol(
    settings: trees.Settings | None = None,
    bagging: float = LGBM_BAGGING,
    max_folds: int | None = None,
) -> dict[str, Any]:
    """Return the M1 protocol a run uses."""
    return {
        **lgbm_settings(settings).describe(io.TI),
        "bagging_fraction": float(bagging),
        "max_folds": None if max_folds is None else int(max_folds),
        "winsor_quantiles": list(io.WINSOR),
        "metric": METRIC,
    }


# Whether an M1 run is the registered one: every protocol value the plan's.
def lgbm_registered(
    settings: trees.Settings | None = None,
    bagging: float = LGBM_BAGGING,
    max_folds: int | None = None,
) -> bool:
    """Return True when the M1 protocol is the plan's."""
    return lgbm_protocol(settings, bagging, max_folds) == lgbm_protocol()


# A network family's protocol as plain values: the grid, seeds, walk-forward
# and training settings stage3_nn resolves for it (its registered values
# where the settings leave them open), with the stage-4 cadence and gap. The
# device is not part of it.
def net_protocol(family: str, settings: nn3.Settings | None = None) -> dict[str, Any]:
    """Return the protocol of an M2 or M3 run."""
    settings = nn3.Settings() if settings is None else settings
    if family == io.SEQ:
        fixed: Mapping[str, Any] = io.SEQ_FIXED
        grid: tuple[Mapping[str, Any], ...] = io.SEQ_GRID
    elif family == io.CNN_I20:
        fixed = io.CNN_FIXED
        grid = ({"lr": float(io.CNN_FIXED["lr"])},)
    else:
        raise ValueError(
            f"a network family is {io.CNN_I20} or {io.SEQ}, not {family!r}"
        )
    grid = grid if settings.grid is None else tuple(settings.grid)

    # A setting, or the registered value where it is left open.
    def pick(value: Any, default: Any) -> int:
        return int(default) if value is None else int(value)

    return {
        "grid": [dict(config) for config in grid],
        "seeds": [int(seed) for seed in settings.seeds],
        "min_train": int(settings.min_train),
        "validation": int(settings.validation),
        "refit": pick(settings.refit, REFIT[family]),
        "gap": pick(settings.gap, GAP),
        "max_epochs": pick(settings.max_epochs, fixed["max_epochs"]),
        "patience": pick(settings.patience, fixed["patience"]),
        "batch": pick(settings.batch, fixed["batch"]),
        "max_folds": None if settings.max_folds is None else int(settings.max_folds),
        "metric": METRIC,
    }


# Whether a network run is the registered one: every protocol value the plan's.
def net_registered(family: str, settings: nn3.Settings | None = None) -> bool:
    """Return True when the network protocol is the plan's."""
    return net_protocol(family, settings) == net_protocol(family)


# ---------------------------------------------------------------------------
# M1: LightGBM
# ---------------------------------------------------------------------------


class Bagged:
    """The lightgbm module, with the plan's bagging fraction in every training call.

    stage3_trees sets `bagging_fraction` from the dataset's kind (0.3 for
    ``ti``). Handed to `stage3_trees._run_fold` in place of lightgbm, this
    replaces that one parameter in each `train` call's copy of the
    parameters and passes everything else (Dataset, early_stopping, the
    version) straight through.
    """

    # Wrap the lightgbm module `lgb`; every model trains with `fraction`.
    def __init__(self, lgb: Any, fraction: float) -> None:
        self._lgb = lgb
        self.fraction = float(fraction)

    # lightgbm.train with the bagging fraction replaced (the caller's
    # parameters are not modified).
    def train(self, params: Mapping[str, Any], *args: Any, **kwargs: Any) -> Any:
        """Train as lightgbm.train does, at this bagging fraction."""
        return self._lgb.train(
            {**params, "bagging_fraction": self.fraction}, *args, **kwargs
        )

    # Everything else is lightgbm's own.
    def __getattr__(self, name: str) -> Any:
        return getattr(self._lgb, name)


# Walk M1 forward over a stage-4 dataset (see the module docstring):
# `settings` defaults to the registered protocol with the stage-4 cadence
# and gap; `bagging` is the plan's 0.7 (a test passes stage 3's 0.3 to
# check parity); `max_folds` cuts the run (it is then not registered); `log`
# receives a header line and one line per fold.
def run_lgbm(
    data: io.Stage3Data,
    settings: trees.Settings | None = None,
    *,
    bagging: float = LGBM_BAGGING,
    max_folds: int | None = None,
    log: Callable[[str], None] | None = None,
) -> io.Stage3Forecast:
    """Return M1's out-of-sample forecast (bp) of every row."""
    stage4 = _stage4_record(data)
    began = time.perf_counter()
    settings = lgbm_settings(settings)
    settings.check()
    view = tree_data(data)
    lgb = trees._lightgbm()
    sessions, index = io.session_index(view.dates)
    plan = folds_for(
        io.LGBM,
        len(sessions),
        min_train=settings.min_train,
        validation=settings.validation,
        refit=settings.refit,
        gap=settings.gap,
    )
    run = trees._limit(plan, max_folds, len(sessions), settings.min_train)
    finite = np.isfinite(view.y)
    out = trees._Outputs.empty(len(view), len(settings.seeds), len(settings.grid))
    protocol = lgbm_protocol(settings, bagging, max_folds)
    registered = lgbm_registered(settings, bagging, max_folds)
    _say(log, _lgbm_header(stage4, settings, bagging, len(plan), len(run), registered))
    bagged = Bagged(lgb, bagging)
    records: list[dict[str, Any]] = []
    for number, fold in enumerate(run):
        record, _ = trees._run_fold(
            bagged,
            view,
            number,
            trees.fold_rows(fold, index, finite),
            settings,
            out,
            False,
        )
        record.update(trees._fold_dates(fold, sessions))
        records.append(record)
        _say(log, trees.progress_line(record, len(run)))
    yhat = out.seeds.mean(axis=1)
    meta = {
        "module": MODULE,
        "stage4_plan": PLAN,
        "model": MODELS[io.LGBM],
        "family": io.LGBM,
        "kind": io.S1,
        **_target_meta(stage4),
        "registered": registered,
        "settings": protocol,
        "num_threads": int(settings.num_threads),
        "lightgbm": str(lgb.__version__),
        "fixed_params": dict(io.LGBM_FIXED),
        "bagging_fraction": float(bagging),
        "dataset_params": dict(trees.DATASET_PARAMS),
        "label_scaling": "winsorized at the fit rows' WINSOR quantiles"
        " (stage3_trees, T-I)",
        "selection": "pooled Spearman on the validation block's raw labels",
        "folds_total": len(plan),
        "folds_run": len(run),
        "complete": len(run) == len(plan),
        "folds": records,
        "rows": len(view),
        "labelled_rows": int(np.count_nonzero(finite)),
        "sessions": len(sessions),
        "forecast_rows": int(np.count_nonzero(np.isfinite(yhat))),
        "first_forecast": str(sessions[run[0].test_start]),
        "last_forecast": str(sessions[run[-1].test_end - 1]),
        "feature_names": list(view.feature_names),
        "numpy": np.__version__,
        "python": platform.python_version(),
        "machine": platform.machine(),
        "seconds": time.perf_counter() - began,
    }
    return io.Stage3Forecast(
        kind=io.S1,
        family=io.LGBM,
        dates=data.dates,
        tickers=data.tickers,
        slot=data.slot,
        yhat=yhat,
        yhat_seeds=out.seeds,
        yhat_configs=out.configs,
        fold=out.fold,
        meta=io.clean_json(meta),
    )


# The line announcing an M1 run: the side, the folds, the protocol, the
# threads, and whether it is the registered one.
def _lgbm_header(
    stage4: Mapping[str, Any],
    settings: trees.Settings,
    bagging: float,
    planned: int,
    running: int,
    registered: bool,
) -> str:
    return (
        f"M1 LightGBM on {stage4['target']}: {running} of {planned} folds (test blocks"
        f" of {settings.refit} sessions, gap {settings.gap}); {len(settings.grid)}"
        f" configurations with seed {settings.seeds[0]} chosen by pooled Spearman, the"
        f" chosen one refit with {len(settings.seeds)} seeds; bagging {bagging};"
        f" {settings.num_threads} threads;"
        f" {'registered' if registered else 'NOT the registered'} settings"
    )


# The side, target and units of a stage-4 record, as a forecast's meta keys.
def _target_meta(stage4: Mapping[str, Any]) -> dict[str, Any]:
    return {key: stage4.get(key) for key in ("side", "target", "units")}


# Call the progress callback when there is one.
def _say(log: Callable[[str], None] | None, text: str) -> None:
    if log is not None:
        log(text)


# ---------------------------------------------------------------------------
# M2 and M3: the networks
# ---------------------------------------------------------------------------


class JKXRegressor(nn3.JKXNet):
    """Stage 3's JKX chart CNN with one regression output instead of two classes."""

    # Build stage 3's network for `family`, then replace its last layer by
    # Linear(flattened -> 1), Xavier-uniform weights and a zero bias as
    # stage 3 initializes its layers.
    def __init__(self, family: str) -> None:
        from torch import nn

        super().__init__(family)
        head = nn.Linear(self.flattened, 1)
        nn.init.xavier_uniform_(head.weight)
        nn.init.zeros_(head.bias)
        self.classify[2] = head


@dataclass(frozen=True)
class _TimingChartState:
    """One fold's target scaling for M2, from its fit part."""

    targets: np.ndarray  # (U, 1) float32 training targets, NaN unknown
    y_scale: float  # bp per training unit
    record: dict[str, Any]


class TimingChartTask(nn3._ChartTask):
    """M2 on the timing target: stage 3's I20 images and network, one output."""

    family = io.CNN_I20

    # Render every row's I20 image once, as stage 3 does, and take the row's
    # timing label (bp) as its target instead of the above-median class.
    # Rows without a complete image are never trained on and get no
    # forecast; they are counted.
    def __init__(
        self, data: io.Stage3Data, bars: io.DailyOHLCV, settings: nn3.Settings
    ) -> None:
        if data.kind != io.S1:
            raise ValueError(f"M2 reads the T-S1 rows, not {data.kind!r} rows")
        self.settings = settings
        self.images, has_image, counts = nn3.chart_images(
            bars, data.dates, data.tickers, self.family
        )
        labels = np.asarray(data.y, dtype=np.float64)
        rows = np.arange(len(data))
        self.units = nn3.Units(
            first=rows, rows=rows[:, None], targets=labels[:, None], of_row=rows
        )
        self.usable = has_image
        self.labelled = np.isfinite(labels)
        self.counts = {
            **counts,
            "rows_without_window": int((~has_image).sum()),
            "rows_unlabelled": int((~self.labelled).sum()),
        }

    # The fold's target scaling from its fit units (T-I's, as M3's).
    def prepare(
        self, fold: io.Fold, sessions: np.ndarray, fit: np.ndarray, device: Any
    ) -> Any:
        """Return the fold's state: the scaled targets and the bp per unit."""
        targets, record = nn3.scaled_targets(io.TI, self.units.targets, fit)
        return _TimingChartState(
            targets=np.asarray(targets, dtype=np.float32),
            y_scale=float(record["y_scale"]),
            record=record,
        )

    # A batch: stage 3's images as (B, 1, H, W) pixels in [0, 1], and the
    # scaled targets.
    def batch(self, state: Any, idx: np.ndarray, device: Any) -> tuple[Any, Any]:
        """Return ((images,), scaled targets) for rows `idx`."""
        import torch

        images = torch.from_numpy(self.images[idx]).to(device).float() / nn3.PIXEL
        targets = torch.from_numpy(state.targets[idx]).to(device)
        return (images[:, None],), targets

    # Squared error summed over the finite targets and their count: stage
    # 3's masked MSE, the loss M3 trains with.
    def loss(self, raw: Any, targets: Any) -> tuple[Any, Any]:
        """Return (sum of squared errors, count of finite targets)."""
        return nn3._SeqTask.loss(cast(Any, self), raw, targets)

    # Outputs back in bp.
    def forecast(self, state: Any, raw: Any) -> Any:
        """Return the (B, 1) forecasts in bp."""
        return raw * state.y_scale

    # Stage 3's I20 network with the one-output head.
    def build(self, config: Mapping[str, Any]) -> Any:
        """Return an untrained JKXRegressor."""
        return JKXRegressor(self.family)

    # Stage 3's record of the network, with the plan's deviation stated.
    def architecture(self) -> dict[str, Any]:
        """Return the M2 architecture record."""
        record = super().architecture()
        record.update(
            head="Flatten, Dropout 0.5, Linear(flattened -> 1)",
            head_init="Xavier-uniform weight, zero bias; replaces the two-class layer"
            " after stage 3's constructor",
            loss="masked MSE on the scaled target (stage3_nn._SeqTask.loss)",
            target=TARGET_SCALING,
            deviation="one regression output instead of the two-class head"
            " (the stage-4 plan's stated deviation)",
        )
        return record


class TimingSeqTask(nn3._SeqTask):
    """M3 on the timing target: stage 3's T-S1 network with T-I's target scaling."""

    # Index the T-S1 rows' sixty-session windows exactly as stage 3 does.
    def __init__(
        self, data: io.Stage3Data, tensor: io.SeqTensor, settings: nn3.Settings
    ) -> None:
        if data.kind != io.S1:
            raise ValueError(f"M3 reads the T-S1 rows, not {data.kind!r} rows")
        super().__init__(data, tensor, settings)

    # The fold's scaling: stage 3's channel and daily robust z from the fit
    # part, and the target winsorized and standardized from the fit units
    # as T-I's (stage 3 takes a T-S1 label as it is).
    def prepare(
        self, fold: io.Fold, sessions: np.ndarray, fit: np.ndarray, device: Any
    ) -> Any:
        """Return the fold's state with T-I-style targets."""
        state = super().prepare(fold, sessions, fit, device)
        targets, record = nn3.scaled_targets(io.TI, self.units.targets, fit)
        return dataclasses.replace(
            state,
            targets=np.asarray(targets, dtype=np.float32),
            y_scale=float(record["y_scale"]),
            record={**state.record, **record},
        )

    # Stage 3's T-S1 record, with the target and its scaling stated.
    def architecture(self) -> dict[str, Any]:
        """Return the M3 architecture record."""
        record = super().architecture()
        record["target"] = TARGET_SCALING
        return record


# The stage-4 selection score: pooled Spearman (stage3_io.selection_score
# for ``ti``) between the forecasts of some units and their rows' raw
# labels, as stage3_nn._score takes it with the question's own metric.
def pooled_score(
    task: Any, data: io.Stage3Data, units: np.ndarray, forecast: np.ndarray
) -> float:
    """Return the pooled Spearman of the units' forecasts with their labels."""
    rows = task.units.rows[units]
    keep = rows >= 0
    target = rows[keep]
    return io.selection_score(
        io.TI,
        forecast[keep],
        np.asarray(data.y, dtype=np.float64)[target],
        data.dates[target],
    )


# One fold of a network family, as stage3_nn._fold runs it: every
# configuration with the first seed, scored on the validation block by
# `score`; the best (ties to the earlier, NaN never) trained with the
# remaining seeds; each network's test forecasts go to `out`. Returns the
# fold's record.
def _net_fold(
    task: Any,
    data: io.Stage3Data,
    fold: io.Fold,
    position: tuple[int, int],
    sessions: np.ndarray,
    unit_session: np.ndarray,
    seeds: tuple[int, ...],
    device: Any,
    out: Any,
    log: Callable[[str], None] | None,
    score: Callable[..., float],
) -> dict[str, Any]:
    started = time.perf_counter()
    number, folds_n = position
    grid = task.grid()
    fit, val, test = nn3._split(task, unit_session, fold)
    if not len(fit) or not len(val):
        raise ValueError(
            f"fold {number}: {len(fit)} fit and {len(val)} validation units; "
            "the walk-forward needs both"
        )
    state = task.prepare(fold, sessions, fit, device)
    eval_batch = task.plan(grid[0]).eval_batch
    tag = f"  fold {number + 1}/{folds_n}"
    configs: list[dict[str, Any]] = []
    per_config: list[np.ndarray] = []
    for c, config in enumerate(grid):
        model, record = nn3._train(task, state, config, seeds[0], fit, val, device)
        forecast = nn3._predict(task, state, model, val, eval_batch, device)
        record["score"] = score(task, data, val, forecast)
        per_config.append(nn3._predict(task, state, model, test, eval_batch, device))
        configs.append({"config": dict(config), **record})
        _say(log, nn3._config_line(f"{tag} config {c + 1}/{len(grid)}", config, record))
    chosen = nn3._choose([r["score"] for r in configs])
    per_seed = [per_config[chosen]]
    seed_runs = [configs[chosen]]
    for seed in seeds[1:]:
        model, record = nn3._train(task, state, grid[chosen], seed, fit, val, device)
        per_seed.append(nn3._predict(task, state, model, test, eval_batch, device))
        seed_runs.append({"config": dict(grid[chosen]), **record})
        _say(log, nn3._config_line(f"{tag} chosen", grid[chosen], record))
    out.write(task.units.rows[test], number, per_seed, per_config)
    rows = task.units.rows
    record = {
        "fold": number,
        "sessions": {
            "fit": [0, fold.fit_end],
            "validation": [fold.val_start, fold.window_end],
            "test": [fold.test_start, fold.test_end],
        },
        "dates": {
            "fit_end": str(sessions[fold.fit_end - 1]),
            "validation": [
                str(sessions[fold.val_start]),
                str(sessions[fold.window_end - 1]),
            ],
            "test": [str(sessions[fold.test_start]), str(sessions[fold.test_end - 1])],
        },
        "units": {"fit": len(fit), "validation": len(val), "test": len(test)},
        "rows": {
            "fit": int(np.isfinite(task.units.targets[fit]).sum()),
            "validation": int(np.isfinite(task.units.targets[val]).sum()),
            "test": int((rows[test] >= 0).sum()),
        },
        "scaling": state.record,
        "configs": configs,
        "chosen": chosen,
        "chosen_config": dict(grid[chosen]),
        "seeds": [
            {k: r[k] for k in ("seed", "epochs", "best_epoch", "val_loss", "seconds")}
            for r in seed_runs
        ],
        "seconds": time.perf_counter() - started,
    }
    shown = configs[chosen]["score"]
    _say(
        log,
        f"fold {number + 1}/{folds_n}: test {record['dates']['test'][0]}.."
        f"{record['dates']['test'][1]} ({record['rows']['test']:,} rows), fit"
        f" {len(fit):,} / validation {len(val):,} units; chose #{chosen + 1}"
        f" {nn3._describe(grid[chosen])} (score {shown:+.4f}), {len(seeds)} seeds,"
        f" {record['seconds']:.0f} s",
    )
    return record


# Walk a network task forward over its folds and assemble the forecast.
# `score` chooses each fold's configuration (pooled Spearman unless a test
# passes stage 3's own); the cadence and gap are the stage-4 ones unless
# the settings override them.
def walk_nets(
    task: Any,
    data: io.Stage3Data,
    settings: nn3.Settings,
    log: Callable[[str], None] | None = None,
    score: Callable[..., float] | None = None,
) -> io.Stage3Forecast:
    """Return the task's out-of-sample forecast of every row."""
    nn3._require_torch()
    import torch

    metric = METRIC if score is None else getattr(score, "__name__", "custom")
    score = pooled_score if score is None else score
    started = time.perf_counter()
    device = torch.device(nn3.resolve_device(settings.device))
    sessions, index = io.session_index(data.dates)
    protocol = net_protocol(task.family, settings)
    grid = task.grid()
    plan_record = task.plan(grid[0])
    used = {
        "grid": [dict(config) for config in grid],
        "max_epochs": plan_record.max_epochs,
        "patience": plan_record.patience,
        "batch": plan_record.batch,
    }
    if any(protocol[key] != value for key, value in used.items()):
        raise ValueError(f"the task trains with {used}, not the protocol {protocol}")
    planned = folds_for(
        task.family,
        len(sessions),
        min_train=settings.min_train,
        validation=settings.validation,
        refit=protocol["refit"],
        gap=protocol["gap"],
    )
    walk = trees._limit(planned, settings.max_folds, len(sessions), settings.min_train)
    seeds = tuple(int(s) for s in settings.seeds)
    rows_n = len(data)
    out = nn3._Outputs(
        seeds=np.full((rows_n, len(seeds)), np.nan),
        configs=np.full((rows_n, len(grid)), np.nan) if task.keeps_configs else None,
        fold=np.full(rows_n, -1, dtype=np.int64),
    )
    unit_session = index[task.units.first]
    stage4 = dict(data.meta.get("stage4", {}))
    registered = net_registered(task.family, settings)
    _say(
        log,
        f"{MODELS.get(task.family, task.family)} {task.family} on"
        f" {stage4.get('target', 'y')}: {len(walk)} of {len(planned)} folds (test"
        f" blocks of {protocol['refit']} sessions, gap {protocol['gap']});"
        f" {len(grid)} configurations with seed {seeds[0]} chosen by {metric}, the"
        f" chosen one with {len(seeds)} seeds; device {device};"
        f" {'registered' if registered else 'NOT the registered'} settings",
    )
    records = []
    with nn3.deterministic_torch():
        for number, fold in enumerate(walk):
            records.append(
                _net_fold(
                    task,
                    data,
                    fold,
                    (number, len(walk)),
                    sessions,
                    unit_session,
                    seeds,
                    device,
                    out,
                    log,
                    score,
                )
            )
    yhat = out.seeds.mean(axis=1)
    meta = {
        "module": MODULE,
        "stage4_plan": PLAN,
        "model": MODELS.get(task.family, task.family),
        "family": task.family,
        "kind": task.kind,
        **_target_meta(stage4),
        "registered": registered,
        "settings": {
            **protocol,
            "metric": metric,
            "folds_planned": len(planned),
            "folds_run": len(walk),
            "device": str(device),
        },
        "target_scaling": TARGET_SCALING,
        "selection": f"{metric} on the validation block's raw labels",
        "architecture": task.architecture(),
        "inputs": task.counts,
        "determinism": {
            "use_deterministic_algorithms": True,
            "cudnn_benchmark": False,
            "cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
            "torch": torch.__version__,
            "threads": torch.get_num_threads(),
        },
        "folds": records,
        "rows": rows_n,
        "labelled_rows": int(np.count_nonzero(np.isfinite(data.y))),
        "rows_forecast": int(np.isfinite(yhat).sum()),
        "first_forecast": str(sessions[walk[0].test_start]),
        "last_forecast": str(sessions[walk[-1].test_end - 1]),
        "seconds": time.perf_counter() - started,
    }
    return io.Stage3Forecast(
        kind=io.S1,
        family=task.family,
        dates=np.asarray(data.dates, dtype="datetime64[D]"),
        tickers=np.asarray(data.tickers),
        slot=np.asarray(data.slot, dtype=np.int8),
        yhat=yhat.astype(np.float32),
        yhat_seeds=out.seeds.astype(np.float32),
        yhat_configs=None if out.configs is None else out.configs.astype(np.float32),
        fold=out.fold,
        meta=io.clean_json(meta),
    )


# M2 on a stage-4 dataset: the I20 chart CNN with one regression output,
# walked forward with images drawn from `bars`.
def run_cnn(
    data: io.Stage3Data,
    bars: io.DailyOHLCV,
    settings: nn3.Settings | None = None,
    log: Callable[[str], None] | None = None,
) -> io.Stage3Forecast:
    """Return M2's out-of-sample forecast (bp) of every row."""
    _stage4_record(data)
    nn3._require_torch()
    settings = nn3.Settings() if settings is None else settings
    io.validate(data)
    return walk_nets(TimingChartTask(data, bars, settings), data, settings, log)


# M3 on a stage-4 dataset: the T-S1 sequence model with T-I's target
# scaling, walked forward with windows from `tensor`.
def run_seq(
    data: io.Stage3Data,
    tensor: io.SeqTensor,
    settings: nn3.Settings | None = None,
    log: Callable[[str], None] | None = None,
) -> io.Stage3Forecast:
    """Return M3's out-of-sample forecast (bp) of every row."""
    _stage4_record(data)
    nn3._require_torch()
    settings = nn3.Settings() if settings is None else settings
    io.validate(data)
    return walk_nets(TimingSeqTask(data, tensor, settings), data, settings, log)
