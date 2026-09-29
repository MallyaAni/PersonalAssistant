"""Train one of stage 3's networks from the exported files and write its forecast.

The networks are the sequence model (M3) and the Jiang-Kelly-Xiu chart CNN
(M2), each walked forward as the pre-registration fixes.

    # M3 on "now or the close" and on "which names to hold".
    python -m backend.cli.market_stage3_nn --family seq --kind ti \
        --data stage3_ti.npz --seq stage3_seq.npz --out stage3_seq_ti.npz
    python -m backend.cli.market_stage3_nn --family seq --kind s1 \
        --data stage3_s1.npz --seq stage3_seq.npz --out stage3_seq_s1.npz
    # M2, both image sizes, T-S1 only.
    python -m backend.cli.market_stage3_nn --family cnn_i20 --kind s1 \
        --data stage3_s1.npz --ohlcv stage3_ohlcv.npz --out stage3_cnn_i20.npz

`--device` is auto (cuda when torch sees one), cpu or cuda. The run is the
registered protocol (`backend/market/stage3_nn.py`, `stage3_io`); a smoke run
may cut it short with `--max-folds N` (the first N folds) and `--max-epochs N`
(both recorded in the forecast's meta, whose `registered` is then false).
One progress line is printed per trained network and per fold. The forecast
(`stage3_io.save_forecast`) carries the input files' sha256, so the numbers
can be traced to the exact export. The plan is
`docs/research/stage3-plan-2026-09-29.md`; nothing here trades.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from backend.market import stage3_io as io
from backend.market import stage3_nn

FAMILIES = tuple(stage3_nn.QUESTIONS)


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Build the parser for training stage 3's networks."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--family", required=True, choices=FAMILIES)
    parser.add_argument("--kind", required=True, choices=io.KINDS)
    parser.add_argument("--data", required=True, type=Path, help="Stage3Data .npz")
    parser.add_argument("--seq", type=Path, help="SeqTensor .npz (family seq)")
    parser.add_argument("--ohlcv", type=Path, help="DailyOHLCV .npz (the CNNs)")
    parser.add_argument("--out", required=True, type=Path, help="forecast .npz")
    parser.add_argument(
        "--device",
        default="auto",
        choices=("auto", "cpu", "cuda"),
        help="where the networks train; auto is cuda when torch sees one",
    )
    parser.add_argument(
        "--max-folds",
        type=int,
        default=None,
        help="run only the first N folds (smoke runs; recorded in the meta)",
    )
    parser.add_argument(
        "--max-epochs",
        type=int,
        default=None,
        help="cap every network's epochs (smoke runs only; recorded in the meta)",
    )
    return parser


# Refuse a family that does not answer the question, or a missing input file.
def check_arguments(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Exit through the parser when the arguments cannot describe a run."""
    if args.kind not in stage3_nn.QUESTIONS[args.family]:
        parser.error(f"--family {args.family} does not answer --kind {args.kind}")
    if args.family == io.SEQ and args.seq is None:
        parser.error("--family seq needs --seq (the SeqTensor)")
    if args.family != io.SEQ and args.ohlcv is None:
        parser.error(f"--family {args.family} needs --ohlcv (the DailyOHLCV)")
    for flag in ("max_folds", "max_epochs"):
        value = getattr(args, flag)
        if value is not None and value < 1:
            parser.error(f"--{flag.replace('_', '-')} must be at least 1")


# The sha256 and size of an input file, so the forecast names its export.
def file_record(path: Path) -> dict[str, Any]:
    """Return {"path", "bytes", "sha256"} of the file at `path`."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


# Load the inputs, train the family, and write the forecast; `argv` is the
# command line as given, recorded in the forecast's meta.
def run(args: argparse.Namespace, argv: list[str]) -> int:
    """Train and write the forecast; return the exit code."""
    started = time.perf_counter()
    data = io.load_data(args.data)
    if data.kind != args.kind:
        raise SystemExit(f"{args.data} holds {data.kind!r} rows, not {args.kind!r}")
    seq = io.load_seq(args.seq) if args.family == io.SEQ else None
    ohlcv = io.load_ohlcv(args.ohlcv) if args.family != io.SEQ else None
    settings = stage3_nn.Settings(
        device=args.device, max_folds=args.max_folds, max_epochs=args.max_epochs
    )
    print(
        f"stage 3 {args.family} on {args.kind}: {len(data):,} rows,"
        f" {len(np.unique(data.dates)):,} sessions, device {args.device}",
        flush=True,
    )
    forecast = stage3_nn.run(
        args.family,
        data,
        seq=seq,
        ohlcv=ohlcv,
        settings=settings,
        log=lambda line: print(line, flush=True),
    )
    inputs = [args.data, args.seq if seq is not None else args.ohlcv]
    meta = {
        **forecast.meta,
        "input_files": [file_record(Path(p)) for p in inputs],
        "command": list(argv),
    }
    path = io.save_forecast(args.out, replace(forecast, meta=meta))
    scored = int(np.isfinite(forecast.yhat).sum())
    print(
        f"wrote {path}: {len(forecast.yhat):,} rows, {scored:,} forecast,"
        f" {len(forecast.meta['folds'])} folds, {time.perf_counter() - started:.0f} s",
        flush=True,
    )
    return 0


# Entry point.
def main(argv: list[str] | None = None) -> int:
    """Parse the arguments and run."""
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    check_arguments(parser, args)
    return run(args, argv)


if __name__ == "__main__":
    sys.exit(main())
