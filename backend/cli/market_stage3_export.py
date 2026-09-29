"""Export stage 3's datasets from the market store.

    python -m backend.cli.market_stage3_export --root data/market \\
        --out-dir data/market/research/stage3 \\
        --vol-forecasts docs/research/scorecards/vol_forecasts.npz \\
        --dd-forecasts docs/research/scorecards/drawdown_forecasts.npz

Writes `stage3_s1.npz`, `stage3_ti.npz`, `stage3_seq.npz` and
`stage3_ohlcv.npz` (the formats of `backend/market/stage3_io.py`) and a
`stage3_export.json` summary: rows, columns, each column's share of missing
values on 2016-2023, the label's quantiles, each file's sha256. Nothing is
trained and nothing trades; `docs/research/stage3-plan-2026-09-29.md` is the
registration these files implement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from backend.market import stage3_export as export
from backend.market import stage3_io as io
from backend.market import universe
from backend.market.store import MarketStore

KINDS = ("s1", "ti", "seq", "ohlcv")


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default="data/market")
    parser.add_argument("--out-dir", type=Path, default=None, help="default: <root>/research/stage3")
    parser.add_argument("--membership", type=Path, default=universe.MEMBERSHIP_HISTORY_PATH)
    parser.add_argument("--tickers", default="", help="comma-separated book names; default: the book")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--vol-forecasts", type=Path, default=None)
    parser.add_argument("--dd-forecasts", type=Path, default=None)
    parser.add_argument("--only", default=",".join(KINDS), help=f"subset of {','.join(KINDS)}")
    return parser


# The sha256 of a file, hex.
def sha256(path: Path) -> str:
    """Return the file's sha256."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Missing-value shares per column on the choosing window, the worst first.
def missing_report(data: io.Stage3Data, top: int = 25) -> dict[str, float]:
    """Return {column: NaN share on 2016-2023} for the `top` most-missing columns."""
    window = (data.dates >= np.datetime64("2016-01-01")) & (data.dates < np.datetime64("2024-01-01"))
    if not window.any():
        return {}
    step = max(1, int(window.sum()) // 200_000)
    sample = data.x[np.flatnonzero(window)[::step]]
    share = np.isnan(sample).mean(axis=0)
    order = np.argsort(-share)[:top]
    return {data.feature_names[i]: round(float(share[i]), 4) for i in order}


# Quantiles of a label, for the summary.
def label_summary(y: np.ndarray) -> dict[str, float | int]:
    """Return count, NaN count and quantiles of the label."""
    finite = y[np.isfinite(y)]
    out: dict[str, float | int] = {"rows": int(len(y)), "nan": int(len(y) - len(finite))}
    if len(finite):
        for q in (0.005, 0.05, 0.5, 0.95, 0.995):
            out[f"q{q}"] = round(float(np.quantile(finite, q)), 4)
        out["mean"] = round(float(finite.mean()), 4)
        out["std"] = round(float(finite.std()), 4)
    return out


# Load, build, write, summarize. `loader` replaces `stage3_export.from_store`
# (tests pass a synthetic world); `desk_run` is the desk the loader runs.
def run(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    loader: Callable[..., export.Inputs] | None = None,
    desk_run: Callable[[MarketStore], Any] | None = None,
) -> int:
    """Run the export; return the exit code."""
    if desk_run is None:
        from backend.cli.market_deep_intraday import default_desk

        desk_run = default_desk
    load = loader or export.from_store
    began = time.perf_counter()

    def say(text: str) -> None:
        print(f"[{time.perf_counter() - began:7.0f} s] {text}", file=out, flush=True)

    wanted = tuple(k.strip() for k in args.only.split(",") if k.strip())
    unknown = set(wanted) - set(KINDS)
    if unknown:
        print(f"unknown --only kinds: {sorted(unknown)}", file=out)
        return 2
    root = Path(args.root)
    store = MarketStore(root)
    out_dir = args.out_dir or root / "research" / "stage3"
    out_dir.mkdir(parents=True, exist_ok=True)
    book = sorted(universe.book_sides(universe.build_universe()))
    if args.tickers:
        chosen = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
        book = [t for t in book if t in chosen]
    inputs = load(
        store,
        tuple(book),
        args.membership,
        desk_run,
        workers=args.workers,
        vol_forecasts=args.vol_forecasts,
        dd_forecasts=args.dd_forecasts,
        log=say,
    )
    say(f"inputs: edgar names {inputs.meta.get('edgar_names', 0)}, tone names {inputs.meta.get('tone_names', 0)}")
    block, internals = export.build_daily(inputs)
    say(f"daily block: {block.values.shape}, {int(block.date_level.sum())} date-level columns")
    summary: dict = {
        "plan": io.PLAN,
        "format": io.FORMAT_VERSION,
        "daily_columns": list(block.names),
        "files": {},
    }
    if "s1" in wanted:
        data = export.s1_data(inputs, block)
        path = io.save_data(out_dir / "stage3_s1.npz", data)
        summary["files"]["s1"] = {
            "path": str(path), "sha256": sha256(path), "rows": len(data),
            "columns": len(data.feature_names), "sessions": int(len(np.unique(data.dates))),
            "label": label_summary(data.y), "relative_return": label_summary(data.extra["r"]),
            "missing": missing_report(data),
        }
        say(f"s1: {len(data):,} rows x {len(data.feature_names)} -> {path}")
        del data
    if "ti" in wanted:
        data = export.ti_data(inputs, block, internals, log=None)
        path = io.save_data(out_dir / "stage3_ti.npz", data)
        summary["files"]["ti"] = {
            "path": str(path), "sha256": sha256(path), "rows": len(data),
            "columns": len(data.feature_names), "intraday_columns": [n for n in data.feature_names if n.startswith(io.INTRADAY_PREFIX)],
            "name_sessions": int(data.meta["name_sessions"]), "label_bp": label_summary(data.y),
            "missing": missing_report(data),
        }
        say(f"ti: {len(data):,} rows x {len(data.feature_names)} -> {path}")
        del data
    if "seq" in wanted:
        tensor = export.seq_tensor(inputs, block, internals)
        path = io.save_seq(out_dir / "stage3_seq.npz", tensor)
        summary["files"]["seq"] = {
            "path": str(path), "sha256": sha256(path), "shape": list(tensor.seq.shape),
            "valid_cells": int(tensor.valid.sum()),
        }
        say(f"seq: {tensor.seq.shape} -> {path}")
        del tensor
    if "ohlcv" in wanted:
        bars = export.daily_bars(inputs)
        path = io.save_ohlcv(out_dir / "stage3_ohlcv.npz", bars)
        summary["files"]["ohlcv"] = {"path": str(path), "sha256": sha256(path), "shape": list(bars.close.shape)}
        say(f"ohlcv: {bars.close.shape} -> {path}")
    summary["seconds"] = round(time.perf_counter() - began, 1)
    summary["inputs"] = io.clean_json({k: v for k, v in inputs.meta.items() if k != "cube_lines"})
    target = out_dir / "stage3_export.json"
    target.write_text(json.dumps(io.clean_json(summary), indent=2, sort_keys=True))
    say(f"summary -> {target}")
    return 0


# Entry point.
def main(argv: list[str] | None = None) -> int:
    """Parse and run."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
