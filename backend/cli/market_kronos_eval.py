"""Kronos on the book: the evaluation adapters for K1, K2 and K3 on spark1.

    python -m backend.cli.market_kronos_eval k1 --root data/market \\
        --forecasts K1=forecasts/k1 [--forecasts K1c40=forecasts/k1c40] \\
        --out docs/research/scorecards/kronos/kronos_k1.json
    python -m backend.cli.market_kronos_eval k2 --root data/market \\
        --forecasts forecasts/k2 --offsets 20 \\
        --out docs/research/scorecards/kronos/kronos_k2.json
    python -m backend.cli.market_kronos_eval k3 --dataset stage1_dataset.npz \\
        --forecasts forecasts/k1 --out docs/research/scorecards/kronos/kronos_k3.json

`docs/research/kronos-plan-2026-09-30.md` registers the study;
`backend/market/kronos_eval.py` (K1, K3) and `backend/market/kronos_fill.py`
(K2) compute it. `k1` runs the desk once for the panel, the grades and
the graded score, restricts the cells to the point-in-time book, places
the RTX's per-name forecast files on the grid and measures them through
`harness.evaluate_scores` per window. `k2` runs the desk as the
adaptive-entry study does (`market_stage4_decisions.load_inputs`),
builds the fill grids from the K2 forecasts, runs the control executor
under `graded-equal-weight/5` from each of `--offsets` start offsets
(`--max-offsets` prices fewer, a smoke run), and judges the two
candidates. `k3` reads the stage-1 dataset and walks the ridge forward
with and without K1's features. Every payload carries the git revision
and the forecast files' sha256s. Nothing here trades.
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

from backend.agents.trading.desk import point_in_time, policy_v5
from backend.market import kronos_eval as ke
from backend.market import kronos_fill as kf
from backend.market import stage3_io as io
from backend.market import stage4_orders as so
from backend.market import universe
from backend.market.store import MarketStore


# The command-line parser: one subcommand per arm.
def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    k1 = sub.add_parser("k1", help="the daily forecast as a stance: rank IC per window")
    k1.add_argument("--root", default="data/market")
    k1.add_argument("--membership", type=Path, default=universe.MEMBERSHIP_HISTORY_PATH)
    k1.add_argument(
        "--forecasts",
        action="append",
        required=True,
        help="LABEL=DIR of per-name forecast files; repeatable",
    )
    k1.add_argument("--out", type=Path, required=True)
    k1.add_argument("--json", action="store_true")
    k2 = sub.add_parser("k2", help="the intraday path as a fill rule")
    k2.add_argument("--root", default="data/market")
    k2.add_argument("--membership", type=Path, default=universe.MEMBERSHIP_HISTORY_PATH)
    k2.add_argument(
        "--forecasts", type=Path, required=True, help="the K2 forecast directory"
    )
    k2.add_argument("--offsets", type=int, default=kf.OFFSETS)
    k2.add_argument("--max-offsets", type=int, default=None)
    k2.add_argument("--cost", type=float, default=so.COST_BPS)
    k2.add_argument("--workers", type=int, default=8)
    k2.add_argument("--out", type=Path, required=True)
    k2.add_argument("--json", action="store_true")
    k3 = sub.add_parser("k3", help="K1's marginal IC over the stage-1 ridge")
    k3.add_argument(
        "--dataset", type=Path, required=True, help="the stage-1 dataset npz"
    )
    k3.add_argument(
        "--forecasts", type=Path, required=True, help="the K1 forecast directory"
    )
    k3.add_argument("--out", type=Path, required=True)
    return parser


# The sha256 of a file, hex.
def sha256(path: Path) -> str:
    """Return the file's sha256."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# The record of a forecast directory: its files and their sha256s.
def forecast_record(directory: Path) -> dict[str, Any]:
    """Return {"directory", "files": {name: sha256}, "run": the RTX's run record}."""
    directory = Path(directory)
    files = {
        p.name: sha256(p)
        for p in sorted(
            list(directory.glob("*.parquet")) + list(directory.glob("*.csv"))
        )
    }
    run = directory / "_run.json"
    return {
        "directory": str(directory),
        "files": files,
        "run": json.loads(run.read_text()) if run.exists() else None,
    }


# The code revision, as the stage-4 command records it.
def revision() -> dict[str, Any] | None:
    """Return {"commit", "dirty"}, None when git cannot say."""
    from backend.cli.market_stage4_decisions import revision as rev

    return rev()


# LABEL=DIR pairs, refused when malformed.
def parse_forecast_sets(specs: list[str]) -> dict[str, Path]:
    """Return {label: directory}."""
    out: dict[str, Path] = {}
    for spec in specs:
        if "=" not in spec:
            raise SystemExit(f"--forecasts must be LABEL=DIR, got {spec!r}")
        label, path = spec.split("=", 1)
        out[label.strip()] = Path(path.strip())
    return out


# The desk report for K1: the live rule's report on the store.
def default_desk(store: MarketStore) -> Any:
    """Return the desk report."""
    from backend.cli.market_deep_intraday import default_desk as desk

    return desk(store)


# K1: the desk once, the cells, every forecast set on the grid, the harness.
def run_k1(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    desk_run: Callable[[MarketStore], Any] | None = None,
) -> int:
    """Run K1; return the exit code."""
    began = time.perf_counter()
    sets = parse_forecast_sets(args.forecasts)
    for label, directory in sets.items():
        if not directory.is_dir():
            print(f"forecast directory not found: {label}={directory}", file=out)
            return 1
    store = MarketStore(Path(args.root))
    report = (desk_run or default_desk)(store)
    panel = report.panel
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    member = point_in_time.eligibility(
        dates, tuple(panel.tickers), history_path=args.membership
    )
    cells = np.asarray(member, dtype=bool) & (np.asarray(report.graded.grades) >= 0)
    cells[:, panel.index(panel.benchmark)] = False
    print(
        f"[{time.perf_counter() - began:5.0f} s] desk: {len(dates)} sessions x {len(panel.tickers)} names; {int(cells.sum()):,} graded member cells",
        file=out,
        flush=True,
    )
    grids: dict[str, np.ndarray] = {}
    records: dict[str, Any] = {}
    for label, directory in sets.items():
        frame = ke.load_forecasts(directory)
        grids.update(ke.k1_grids(panel, frame, label))
        records[label] = forecast_record(directory)
        records[label]["rows"] = int(len(frame))
        print(
            f"[{time.perf_counter() - began:5.0f} s] {label}: {len(frame):,} forecast rows from {directory}",
            file=out,
            flush=True,
        )
    payload = ke.evaluate_k1(
        panel, cells, grids, np.asarray(report.scores, dtype=float)
    )
    payload["run"] = {
        "root": str(args.root),
        "revision": revision(),
        "membership": {
            "file": str(args.membership),
            "sha256": (
                sha256(args.membership) if Path(args.membership).exists() else None
            ),
        },
        "forecasts": records,
        "cells": int(cells.sum()),
        "seconds": round(time.perf_counter() - began, 1),
    }
    _write(payload, args.out, args.json, out)
    return 0


# K2: the desk and the cubes, the forecast grids, the offsets, the verdict.
def run_k2(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    loader: Callable[..., tuple[Any, dict[str, Any], dict[str, Any]]] | None = None,
) -> int:
    """Run K2; return the exit code."""
    began = time.perf_counter()

    def say(text: str) -> None:
        print(f"[{time.perf_counter() - began:7.0f} s] {text}", file=out, flush=True)

    if not Path(args.membership).exists():
        print(f"file not found: {args.membership}", file=out)
        return 1
    if not Path(args.forecasts).is_dir():
        print(f"forecast directory not found: {args.forecasts}", file=out)
        return 1
    if args.offsets < 1 or (args.max_offsets is not None and args.max_offsets < 1):
        print("--offsets and --max-offsets must be at least 1", file=out)
        return 2
    if loader is None:
        from backend.cli.market_stage4_decisions import load_inputs

        loader = load_inputs
    store = MarketStore(Path(args.root))
    report, cubes, _ = loader(store, args.workers, say)
    restricted, mask = point_in_time.point_in_time(report, args.membership)
    panel = restricted.panel
    frame = ke.load_forecasts(args.forecasts)
    low = (
        ke.score_grid(panel, frame, "k2_low_rel_open")
        if len(frame)
        else np.full((len(panel.dates), len(panel.tickers)), np.nan)
    )
    high = (
        ke.score_grid(panel, frame, "k2_high_rel_open")
        if len(frame)
        else np.full((len(panel.dates), len(panel.tickers)), np.nan)
    )
    say(f"forecasts: {len(frame):,} rows; {int(np.isfinite(low).sum()):,} on the grid")
    fills, next_bar, oracle, oracle_five, coverage = kf.fill_grids(
        panel, cubes, low, high
    )
    say(f"fills: {coverage['names_with_cube']} names with a cube")
    market = kf.build_market(
        panel, restricted.graded.grades, fills, next_bar, oracle, oracle_five
    )
    priced = args.offsets if args.max_offsets is None else args.max_offsets
    priced = min(args.offsets, priced)
    runs = so.run_offsets(
        restricted,
        mask,
        priced,
        args.cost,
        so.EXECUTED,
        say,
        allocator=policy_v5.allocator(mask),
    )
    payload = kf.evaluate(runs, market, registered=args.offsets)
    tickers = [t for t in panel.tickers if t != panel.benchmark]
    payload["run"] = {
        "root": str(args.root),
        "revision": revision(),
        "cost_bps": float(args.cost),
        "basis": so.EXECUTED,
        "policy": policy_v5.POLICY_VERSION,
        "inputs": {
            "membership": {
                "file": str(args.membership),
                "sha256": sha256(args.membership),
            },
            "forecasts": forecast_record(args.forecasts),
        },
        "panel": {
            "sessions": len(panel.dates),
            "names": len(tickers),
            "benchmark": panel.benchmark,
            "first": str(panel.dates[0]),
            "last": str(panel.dates[-1]),
        },
        "cubes": coverage,
        "seconds": round(time.perf_counter() - began, 1),
    }
    _write(payload, args.out, args.json, out, render_k2)
    return 0


# K3: the stage-1 dataset, the ridge with and without K1.
def run_k3(args: argparse.Namespace, out: TextIO = sys.stdout, walk=None) -> int:
    """Run K3; return the exit code."""
    from backend.market import deep_intraday as di

    began = time.perf_counter()
    if not Path(args.dataset).exists():
        print(f"file not found: {args.dataset}", file=out)
        return 1
    if not Path(args.forecasts).is_dir():
        print(f"forecast directory not found: {args.forecasts}", file=out)
        return 1
    ds, _ = di.load_dataset(args.dataset)
    frame = ke.load_forecasts(args.forecasts)
    print(
        f"[{time.perf_counter() - began:5.0f} s] dataset {len(ds):,} rows, {len(frame):,} forecast rows",
        file=out,
        flush=True,
    )
    payload = ke.evaluate_k3(
        ds, frame, walk=walk, log=lambda text: print(f"  {text}", file=out, flush=True)
    )
    payload.update({"study": ke.STUDY, "plan": ke.PLAN})
    payload["run"] = {
        "dataset": {"file": str(args.dataset), "sha256": sha256(args.dataset)},
        "forecasts": forecast_record(args.forecasts),
        "revision": revision(),
        "seconds": round(time.perf_counter() - began, 1),
    }
    _write(payload, args.out, False, out)
    return 0


# Write a payload (NaN-free JSON) and print its lines.
def _write(
    payload: dict[str, Any],
    target: Path,
    as_json: bool,
    out: TextIO,
    render: Callable[[dict[str, Any]], str] | None = None,
) -> None:
    """Write `payload` to `target` and print it."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(io.clean_json(payload), indent=2, allow_nan=False)
    target.write_text(text, encoding="utf-8")
    if as_json:
        print(text, file=out)
    elif render is not None:
        print(render(json.loads(text)), file=out)
    else:
        for line in payload.get("lines", []):
            print(line, file=out)
        if "verdict" in payload and isinstance(payload["verdict"], dict):
            print(
                f"VERDICT: {payload['verdict']['label']} - {payload['verdict']['reason']}",
                file=out,
            )
    print(f"wrote {target}", file=out)


# A number to `digits` decimals with its sign, "n/a" when missing.
def _num(x: Any, digits: int = 2) -> str:
    """Return `x` signed, "n/a" for None or NaN."""
    return "n/a" if x is None or x != x else f"{float(x):+.{digits}f}"


# The K2 payload as the lines people read.
def render_k2(payload: dict[str, Any]) -> str:
    """Return the verdict text of a K2 payload."""
    offsets = payload["offsets"]
    control = payload["control"]
    median = payload["orders"]["median_by_window"]
    head = (
        f"kronos K2 ({payload['plan']}) as of {payload['asof']}: {len(kf.CANDIDATES)} candidates on the {control['basis']} orders of "
        f"{control['executor']} under {control['policy']} against {control['fills']}; {offsets['priced']} of {offsets['registered']} offsets, "
        f"statistics at offset {offsets['median']}; model window {payload['windows'][kf.MODEL][0]} onwards (post-cutoff); Newey-West lag {payload['hac_lag']}"
    )
    orders = "; ".join(
        f"{w} {m['buys']} buys and {m['sells']} sells over {m['decision_sessions']} sessions"
        for w, m in median.items()
    )
    drift = "; ".join(
        f"{w} {_num(d['mu_bp'])} bp/session over {d['name_days']} A/A+ name-days"
        for w, d in payload["drift"].items()
    )
    lines = [
        head,
        f"orders at the median offset: {orders}",
        f"drift: {drift}",
        "",
        payload["verdict"]["text"],
    ]
    lines += [f"  {line}" for line in payload["verdict"]["lines"]]
    return "\n".join(lines)


# Entry point.
def main(argv: list[str] | None = None) -> int:
    """Parse and run."""
    args = build_parser().parse_args(argv)
    if args.command == "k1":
        return run_k1(args)
    if args.command == "k2":
        return run_k2(args)
    return run_k3(args)


if __name__ == "__main__":
    raise SystemExit(main())
