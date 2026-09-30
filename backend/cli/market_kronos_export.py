"""Export the Kronos study's inputs from the market store.

    python -m backend.cli.market_kronos_export --root data/market \\
        --out-dir data/market/research/kronos

Writes `daily.parquet` (the book's adjusted daily OHLCV), `bars15.parquet`
(the cubes' 26 regular bars a session on the adjusted basis),
`cells.parquet` (the graded, member (session, name) cells from 2018-01-02
on, with the next session's date) and `sessions.parquet` (the panel's
dates), plus `kronos_export.json`: rows per table, the date ranges, how
many cells have a full context, each file's sha256. `--format csv` writes
CSV instead (a machine without pyarrow). Nothing is forecast here;
`docs/research/kronos-plan-2026-09-30.md` is the registration these files
implement and `backend/market/kronos_export.py` builds the tables.
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
import pandas as pd

from backend.market import kronos_export as ke
from backend.market import universe
from backend.market.store import MarketStore

TABLES = ("daily", "bars15", "cells", "sessions")
FORMATS = ("parquet", "csv")


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", default="data/market")
    parser.add_argument(
        "--out-dir", type=Path, default=None, help="default: <root>/research/kronos"
    )
    parser.add_argument(
        "--membership", type=Path, default=universe.MEMBERSHIP_HISTORY_PATH
    )
    parser.add_argument(
        "--tickers", default="", help="comma-separated book names; default: the book"
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--since", default=str(ke.SINCE), help="first cell date (YYYY-MM-DD)"
    )
    parser.add_argument("--format", default="parquet", choices=FORMATS)
    return parser


# The sha256 of a file, hex.
def sha256(path: Path) -> str:
    """Return the file's sha256."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Write one table in the chosen format; return its path.
def write_table(frame: pd.DataFrame, out_dir: Path, name: str, fmt: str) -> Path:
    """Write `frame` as <out_dir>/<name>.<fmt> and return the path."""
    path = out_dir / f"{name}.{fmt}"
    if fmt == "parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)
    return path


# The date range of a table's `date` column, as strings.
def date_range(frame: pd.DataFrame) -> list[str | None]:
    """Return [first, last] of the table's dates, None when empty."""
    if not len(frame):
        return [None, None]
    dates = np.asarray(frame["date"], dtype="datetime64[D]")
    return [str(dates.min()), str(dates.max())]


# Load, build, write, summarize. `loader` replaces `kronos_export.from_store`
# (tests pass a synthetic world); `desk_run` is the desk the loader runs.
def run(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    loader: Callable[..., ke.Inputs] | None = None,
    desk_run: Callable[[MarketStore], Any] | None = None,
) -> int:
    """Run the export; return the exit code."""
    if desk_run is None:
        from backend.cli.market_deep_intraday import default_desk

        desk_run = default_desk
    load = loader or ke.from_store
    began = time.perf_counter()

    def say(text: str) -> None:
        print(f"[{time.perf_counter() - began:7.0f} s] {text}", file=out, flush=True)

    try:
        since = np.datetime64(args.since, "D").astype(object)
    except ValueError:
        print(f"--since must be YYYY-MM-DD, got {args.since!r}", file=out)
        return 2
    root = Path(args.root)
    store = MarketStore(root)
    out_dir = args.out_dir or root / "research" / "kronos"
    out_dir.mkdir(parents=True, exist_ok=True)
    book = sorted(universe.book_sides(universe.build_universe()))
    if args.tickers:
        chosen = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
        book = [t for t in book if t in chosen]
    inputs = load(
        store, tuple(book), args.membership, desk_run, workers=args.workers, log=say
    )
    tables = {
        "daily": ke.daily_table(inputs),
        "bars15": ke.bars_table(inputs),
        "cells": ke.cells_table(inputs, since),
        "sessions": ke.sessions_table(inputs),
    }
    summary: dict[str, Any] = {
        "plan": ke.PLAN,
        "format": ke.FORMAT_VERSION,
        "since": str(since),
        "contexts": {"daily": ke.DAILY_CONTEXT, "intraday": ke.INTRADAY_CONTEXT},
        "horizons": {"daily": ke.DAILY_HORIZON, "intraday": ke.INTRADAY_HORIZON},
        "book_names": len(book),
        "files": {},
    }
    for name in TABLES:
        frame = tables[name]
        path = write_table(frame, out_dir, name, args.format)
        summary["files"][name] = {
            "path": str(path),
            "sha256": sha256(path),
            "rows": int(len(frame)),
            "columns": list(frame.columns),
            "dates": date_range(frame),
            "names": int(frame["ticker"].nunique()) if "ticker" in frame else None,
        }
        say(f"{name}: {len(frame):,} rows -> {path}")
    summary["coverage"] = ke.context_coverage(
        tables["daily"], tables["bars15"], tables["cells"]
    )
    summary["inputs"] = {k: v for k, v in inputs.meta.items() if k != "cube_lines"}
    summary["seconds"] = round(time.perf_counter() - began, 1)
    target = out_dir / "kronos_export.json"
    target.write_text(json.dumps(summary, indent=2, sort_keys=True))
    say(f"summary -> {target}")
    return 0


# Entry point.
def main(argv: list[str] | None = None) -> int:
    """Parse and run."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
