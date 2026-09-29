"""Train one of stage 4's models on the timing target and write its forecast.

    # M1 on the RTX desktop's CPU (20 threads), one run per side:
    python -m backend.cli.market_stage4_models --family lgbm --side buy \\
        --s1 stage3_s1.npz --labels stage4_labels.npz --out stage4_lgbm_buy.npz
    # M2 and M3 on the RTX 5080:
    python -m backend.cli.market_stage4_models --family cnn_i20 --side buy \\
        --s1 stage3_s1.npz --labels stage4_labels.npz --ohlcv stage3_ohlcv.npz \\
        --out stage4_cnn_i20_buy.npz --device cuda
    python -m backend.cli.market_stage4_models --family seq --side sell \\
        --s1 stage3_s1.npz --labels stage4_labels.npz --seq stage3_seq.npz \\
        --out stage4_seq_sell.npz --device cuda

`docs/research/stage4-plan-2026-09-29.md` registers the models, and
`backend/market/stage4_models.py` implements them on top of stage 3's
trainers. The label is `g_buy` or `g_sell` (bp) from the labels file that
`market_stage4_labels` wrote. That file must have been made from this very
export (its meta carries the export's sha256) and must hold the export's
rows in order; anything else is refused before any training.

The run is the registered protocol. A smoke run may shrink it with
`--max-folds`, `--max-epochs`, `--grid-first`, `--seeds`, `--min-train`,
`--validation`, `--refit`, `--gap`, `--max-rounds`, `--patience` or
`--batch`; each value is recorded in the forecast's meta, whose
`registered` is false whenever any differs from the plan's. `--device` is
where the networks train (auto is cuda when torch sees one); LightGBM
always trains on the CPU with `--threads` threads (20 by default, the
plan's). One progress line is printed per fold, and for the networks one
per trained network. The forecast (`stage3_io.save_forecast`) records the
side, the family, the protocol, the input files' sha256 and the command
line. Nothing here trades.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from backend.cli import market_stage4_labels as labels_cli
from backend.cli.market_stage3_nn import file_record
from backend.market import stage3_io as io
from backend.market import stage3_nn as nn3
from backend.market import stage3_trees as trees
from backend.market import stage4_models as models

# Options that only some families read, and the families that read them.
ONLY_FOR = {
    "max_epochs": (io.CNN_I20, io.SEQ),
    "batch": (io.CNN_I20, io.SEQ),
    "max_rounds": (io.LGBM,),
    "grid_first": (io.LGBM, io.SEQ),
    "seq": (io.SEQ,),
    "ohlcv": (io.CNN_I20,),
}
# The registered grid each family's --grid-first cuts.
GRIDS = {io.LGBM: io.LGBM_GRID, io.SEQ: io.SEQ_GRID}


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Build the parser for training a stage-4 model."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--family", required=True, choices=models.FAMILIES)
    parser.add_argument("--side", required=True, choices=models.SIDES)
    parser.add_argument(
        "--s1", required=True, type=Path, help="the stage-3 T-S1 export (stage3_s1.npz)"
    )
    parser.add_argument(
        "--labels",
        required=True,
        type=Path,
        help="the stage-4 labels (market_stage4_labels)",
    )
    parser.add_argument("--seq", type=Path, help="the SeqTensor .npz (family seq)")
    parser.add_argument(
        "--ohlcv", type=Path, help="the DailyOHLCV .npz (family cnn_i20)"
    )
    parser.add_argument(
        "--out", required=True, type=Path, help="the forecast .npz to write"
    )
    parser.add_argument(
        "--device",
        default="auto",
        choices=("auto", "cpu", "cuda"),
        help="where the networks train; auto is cuda when torch sees one"
        " (lgbm uses the CPU)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=None,
        help=f"LightGBM's num_threads (default {trees.DEFAULT_THREADS}, the plan's);"
        " torch's CPU threads for the networks (default torch's)",
    )
    smoke = parser.add_argument_group(
        "smoke runs",
        "any value other than the plan's makes the forecast's meta registered: false",
    )
    smoke.add_argument("--max-folds", type=int, help="run only the first N folds")
    smoke.add_argument(
        "--max-epochs", type=int, help="cap every network's epochs (cnn_i20, seq)"
    )
    smoke.add_argument(
        "--grid-first", type=int, help="use the registered grid's first N (lgbm, seq)"
    )
    smoke.add_argument(
        "--seeds", help="comma-separated seeds, the first choosing the configuration"
    )
    smoke.add_argument(
        "--min-train", type=int, help="the first test block's session index"
    )
    smoke.add_argument(
        "--validation", type=int, help="sessions in each validation block"
    )
    smoke.add_argument("--refit", type=int, help="sessions per test block")
    smoke.add_argument("--gap", type=int, help="the purge-plus-embargo gap in sessions")
    smoke.add_argument("--max-rounds", type=int, help="LightGBM's round cap (lgbm)")
    smoke.add_argument(
        "--patience", type=int, help="early-stopping patience: rounds (lgbm) or epochs"
    )
    smoke.add_argument("--batch", type=int, help="the training batch (cnn_i20, seq)")
    return parser


# Comma-separated seeds as a tuple: at least one, integers, none repeated.
def parse_seeds(text: str) -> tuple[int, ...]:
    """Return the seeds of `text`, or raise ValueError."""
    seeds = tuple(int(part) for part in text.split(",") if part.strip())
    if not seeds:
        raise ValueError("--seeds needs at least one seed")
    if len(set(seeds)) != len(seeds):
        raise ValueError(f"--seeds repeats a seed: {text}")
    return seeds


# Refuse arguments that cannot describe a run: a family's missing input, an
# input or option the family does not read, a count below its minimum.
def check_arguments(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Exit through the parser when the arguments cannot describe a run."""
    if args.family == io.SEQ and args.seq is None:
        parser.error("--family seq needs --seq (the SeqTensor)")
    if args.family == io.CNN_I20 and args.ohlcv is None:
        parser.error("--family cnn_i20 needs --ohlcv (the DailyOHLCV)")
    for name, families in ONLY_FOR.items():
        if getattr(args, name) is not None and args.family not in families:
            flag = f"--{name.replace('_', '-')}"
            parser.error(f"{flag} is for --family {' or '.join(families)} only")
    _check_counts(parser, args)


# Refuse a count below its minimum, a grid cut longer than the grid, and a
# seed list that is empty or repeats a seed.
def _check_counts(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    for name in (
        "threads",
        "max_folds",
        "max_epochs",
        "grid_first",
        "min_train",
        "validation",
        "refit",
        "max_rounds",
        "patience",
        "batch",
    ):
        value = getattr(args, name)
        if value is not None and value < 1:
            parser.error(f"--{name.replace('_', '-')} must be at least 1")
    if args.gap is not None and args.gap < 0:
        parser.error("--gap must not be negative")
    if args.grid_first is not None and args.grid_first > len(GRIDS[args.family]):
        parser.error(
            f"--grid-first is at most {len(GRIDS[args.family])} for {args.family}"
        )
    if args.seeds is not None:
        try:
            parse_seeds(args.seeds)
        except ValueError as error:
            parser.error(str(error))


# The export and the labels as one side's stage-4 dataset, after the checks
# that the labels were made from this export and hold its rows in order.
# Returns the dataset and the provenance the forecast records.
def load_inputs(
    s1_path: Path, labels_path: Path, side: str
) -> tuple[io.Stage3Data, dict[str, Any]]:
    """Return (the timing dataset, its provenance); raise ValueError on a mismatch."""
    export = io.load_data(s1_path)
    dates, tickers, g_buy, g_sell, labels_meta = labels_cli.load(labels_path)
    s1_sha256 = trees.file_sha256(s1_path)
    models.check_labels_source(labels_meta, s1_sha256)
    data = models.timing_data(export, dates, tickers, g_buy, g_sell, side)
    provenance = {
        "s1_sha256": s1_sha256,
        "labels_sha256": trees.file_sha256(labels_path),
        "export_registered": s1_sha256.startswith(models.REGISTERED_EXPORT),
        "labels_meta": labels_meta,
    }
    return data, provenance


# M1's settings from the arguments: the registration, with any smoke
# option applied and the thread count.
def lgbm_settings(args: argparse.Namespace) -> trees.Settings:
    """Return the trees.Settings M1 runs with."""
    changes: dict[str, Any] = {
        "num_threads": trees.DEFAULT_THREADS if args.threads is None else args.threads
    }
    if args.grid_first is not None:
        changes["grid"] = tuple(io.LGBM_GRID[: args.grid_first])
    if args.seeds is not None:
        changes["seeds"] = parse_seeds(args.seeds)
    for name in ("min_train", "validation", "refit", "gap", "max_rounds", "patience"):
        if getattr(args, name) is not None:
            changes[name] = getattr(args, name)
    return trees.Settings(**changes)


# The networks' settings from the arguments: the registration, with any
# smoke option applied and the device.
def net_settings(args: argparse.Namespace) -> nn3.Settings:
    """Return the stage3_nn.Settings M2 or M3 runs with."""
    changes: dict[str, Any] = {"device": args.device}
    if args.grid_first is not None:
        changes["grid"] = tuple(io.SEQ_GRID[: args.grid_first])
    if args.seeds is not None:
        changes["seeds"] = parse_seeds(args.seeds)
    for name in (
        "min_train",
        "validation",
        "refit",
        "gap",
        "max_epochs",
        "patience",
        "batch",
        "max_folds",
    ):
        if getattr(args, name) is not None:
            changes[name] = getattr(args, name)
    return nn3.Settings(**changes)


# The dataset and its inputs in one line.
def _describe(
    args: argparse.Namespace, data: io.Stage3Data, provenance: dict[str, Any]
) -> str:
    sessions, _ = io.session_index(data.dates)
    labelled = int(np.count_nonzero(np.isfinite(data.y)))
    export = "" if provenance["export_registered"] else ", NOT the registered export"
    return (
        f"stage 4 {args.family} ({models.MODELS[args.family]}) on g_{args.side}:"
        f" {len(data):,} rows, {labelled:,} labelled, {len(sessions):,} sessions"
        f" {sessions[0]}..{sessions[-1]}; labels {args.labels}"
        f" ({provenance['labels_sha256'][:8]}) from {args.s1}"
        f" ({provenance['s1_sha256'][:8]}{export})"
    )


# Load and check the inputs, train the family, and write the forecast;
# `argv` is the command line as given, recorded in the forecast's meta.
def run(args: argparse.Namespace, argv: list[str], out: TextIO | None = None) -> int:
    """Train and write the forecast; return the exit code."""
    out = sys.stdout if out is None else out

    # One line of progress, written as it happens.
    def say(text: str) -> None:
        print(text, file=out, flush=True)

    started = time.perf_counter()
    try:
        data, provenance = load_inputs(args.s1, args.labels, args.side)
    except ValueError as error:
        raise SystemExit(f"refused: {error}") from error
    say(_describe(args, data, provenance))
    if args.family == io.LGBM:
        forecast = models.run_lgbm(
            data, lgbm_settings(args), max_folds=args.max_folds, log=say
        )
    else:
        if args.threads is not None:
            nn3._require_torch()
            import torch

            torch.set_num_threads(args.threads)
        settings = net_settings(args)
        if args.family == io.CNN_I20:
            forecast = models.run_cnn(
                data, io.load_ohlcv(args.ohlcv), settings, log=say
            )
        else:
            forecast = models.run_seq(data, io.load_seq(args.seq), settings, log=say)
    inputs = [args.s1, args.labels] + [
        p for p in (args.seq, args.ohlcv) if p is not None
    ]
    meta = {
        **forecast.meta,
        **provenance,
        "input_files": [file_record(Path(p)) for p in inputs],
        "command": list(argv),
    }
    path = io.save_forecast(args.out, dataclasses.replace(forecast, meta=meta))
    shown = forecast.meta
    forecast_rows = int(np.isfinite(forecast.yhat).sum())
    say(
        f"wrote {path}: {len(forecast.yhat):,} rows, {forecast_rows:,}"
        f" forecast ({shown['first_forecast']}..{shown['last_forecast']}),"
        f" {len(shown['folds'])} folds,"
        f" {'registered' if shown['registered'] else 'NOT the registered'} settings,"
        f" {time.perf_counter() - started:.0f} s"
    )
    return 0


# Entry point.
def main(argv: list[str] | None = None, out: TextIO | None = None) -> int:
    """Parse the arguments and run."""
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    check_arguments(parser, args)
    return run(args, argv, out)


if __name__ == "__main__":
    sys.exit(main())
