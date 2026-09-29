"""Stage 3, M1: LightGBM walked forward on one question's dataset.

    # On the RTX desktop (i9-10900K, 20 threads), from the Spark's export;
    # T-S1 first, as the plan orders the work:
    python -m backend.cli.market_stage3_trees --data stage3_s1.npz \
        --out stage3_s1_lgbm.npz --importance \
        --diagnostics stage3_s1_lgbm_diagnostics.json
    python -m backend.cli.market_stage3_trees --data stage3_ti.npz \
        --out stage3_ti_lgbm.npz --importance \
        --diagnostics stage3_ti_lgbm_diagnostics.json

Reads a `stage3_io.Stage3Data` file (``ti`` or ``s1``), walks M1 forward
exactly as the pre-registration fixes it (`stage3_trees.walk_forward`: the
eight-configuration grid chosen on each fold's nested validation block,
the chosen configuration refit on the training window with five seeds),
prints one line per fold, and writes the forecast with
`stage3_io.save_forecast` for the decision tests. `--threads` is
LightGBM's num_threads (the plan's 20; the same data on the same threads
gives the same forecast). `--max-folds N` stops after the first N folds,
and the forecast records that the run is partial. `--importance` adds the
permutation importance on every fold's validation block: the top 30 are
printed and the full ranking is kept in the forecast's meta.
`--diagnostics <json>` writes the out-of-sample score by calendar year and
window, and every column's univariate IC on 2016-2019 and 2020-2023.

The plan is `docs/research/stage3-plan-2026-09-29.md`; every number the
run uses is read from `backend/market/stage3_io.py`. Nothing here trades.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from backend.market import stage3_io as io
from backend.market import stage3_trees

# Columns of the permutation importance printed (the plan's top 30).
TOP_IMPORTANCE = 30


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Build the parser for the M1 walk-forward."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--data", required=True, help="a Stage3Data .npz (stage3_io.save_data)"
    )
    parser.add_argument(
        "--out",
        required=True,
        help="the forecast .npz to write (stage3_io.save_forecast)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=stage3_trees.DEFAULT_THREADS,
        help=f"LightGBM num_threads (the plan's {stage3_trees.DEFAULT_THREADS})",
    )
    parser.add_argument(
        "--max-folds",
        type=int,
        default=None,
        help="stop after the first N folds (a partial run, recorded as such)",
    )
    parser.add_argument(
        "--importance",
        action="store_true",
        help="permutation importance on every fold's validation block",
    )
    parser.add_argument(
        "--diagnostics",
        default=None,
        help="write the out-of-sample and univariate-IC diagnostics to this JSON file",
    )
    return parser


# Load, walk forward, write, report. `settings` replaces the registered
# protocol for tests only (the command line always runs the registered
# one); `--threads` applies either way.
def run(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    settings: stage3_trees.Settings | None = None,
) -> int:
    """Run M1 for the parsed arguments; return the exit code."""

    # One line of progress, written as it happens.
    def say(text: str) -> None:
        print(text, file=out, flush=True)

    began = time.perf_counter()
    data_path = Path(args.data)
    data = io.load_data(data_path)
    say(_describe(data, data_path))
    settings = dataclasses.replace(
        settings or stage3_trees.Settings(), num_threads=int(args.threads)
    )
    forecast = stage3_trees.walk_forward(
        data,
        settings,
        max_folds=args.max_folds,
        importance=bool(args.importance),
        source=data_path,
        log=say,
    )
    written = io.save_forecast(Path(args.out), forecast)
    meta = forecast.meta
    say(
        f"wrote {written}: {meta['forecast_rows']:,} of {meta['rows']:,} rows forecast"
        f" ({meta['first_forecast']}..{meta['last_forecast']}),"
        f" {meta['folds_run']} of {meta['folds_total']} folds"
        f"{'' if meta['complete'] else ' (PARTIAL)'},"
        f" {'registered' if meta['registered'] else 'NOT the registered'} settings,"
        f" {time.perf_counter() - began:.0f} s"
    )
    if meta.get("importance"):
        for line in importance_lines(meta["importance"], meta["folds_run"]):
            say(line)
    if args.diagnostics:
        report = stage3_trees.diagnostics(data, forecast)
        target = Path(args.diagnostics)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
        )
        for line in diagnostics_lines(report):
            say(line)
        say(f"wrote {target}")
    return 0


# The dataset in one line: its question, rows, sessions, columns, labels.
def _describe(data: io.Stage3Data, path: Path) -> str:
    sessions, _ = io.session_index(data.dates)
    labelled = int(np.count_nonzero(np.isfinite(data.y)))
    span = f"{sessions[0]}..{sessions[-1]}" if len(sessions) else "no sessions"
    return (
        f"dataset {path}: kind {data.kind}, {len(data):,} rows, {len(sessions):,}"
        f" sessions {span}, {len(data.feature_names)} columns,"
        f" {labelled:,} labelled rows"
    )


# The permutation importance's top columns as printed lines.
def importance_lines(ranking: list[dict[str, Any]], folds: int) -> list[str]:
    """Return the header and one line per top column."""
    lines = [
        f"permutation importance: the drop in the validation score when a column is"
        f" shuffled, mean over {folds} folds (top {TOP_IMPORTANCE} of {len(ranking)})"
    ]
    for entry in ranking[:TOP_IMPORTANCE]:
        lines.append(
            f"  {entry['rank']:>3}  {entry['feature']:<40}"
            f" {_signed(entry['drop'], 5):>10}  sd {_signed(entry['std'], 5, False):>8}"
            f"  ({entry['folds']} folds)"
        )
    return lines


# The diagnostics' out-of-sample lines: the score by calendar year and on
# the choosing and later windows.
def diagnostics_lines(report: dict[str, Any]) -> list[str]:
    """Return the printed summary of a diagnostics report."""
    lines = ["out-of-sample selection score (the ensemble):"]
    for year, entry in report["oos"]["by_year"].items():
        lines.append(
            f"  {year}: {_signed(entry['score'], 4)} ({entry['pairs']:,} pairs,"
            f" {entry['sessions']} sessions)"
        )
    for name, entry in report["oos"]["windows"].items():
        ensemble = entry["ensemble"]
        seeds = ", ".join(_signed(seed["score"], 4) for seed in entry["seeds"])
        lines.append(
            f"  {name} window: {_signed(ensemble['score'], 4)}"
            f" ({ensemble['pairs']:,} pairs); per seed {seeds or '-'}"
        )
    return lines


# A number with its sign (or without), or a dash for a missing one.
def _signed(value: float | None, digits: int, sign: bool = True) -> str:
    if value is None or value != value:
        return "-"
    return f"{value:+.{digits}f}" if sign else f"{value:.{digits}f}"


# Entry point.
def main(argv: list[str] | None = None) -> int:
    """Parse the arguments and run."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
