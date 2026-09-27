"""Deep sequence models, stage 2: sixty sessions of bars, the market's bars
beside the name's, the desk's evidence as inputs, targets the decision
would act on.

    # On the Spark, from the store: build the dataset and write it.
    python -m backend.cli.market_deep_stage2 --root data/market \
        --export research/deep_stage2.npz --models none --workers 8
    # On the RTX, from the file: train and score.
    python -m backend.cli.market_deep_stage2 --dataset deep_stage2.npz \
        --models ridge,cnn,patchtst,patchtst-pretrained --device cuda \
        --out deep_stage2.json

Loads one session cube per book name and per benchmark from the raw-basis
SIP store (`market_session_anatomy.load_cubes`, in a process pool with
`--workers` above one), builds the point-in-time membership mask from the
dated history, runs the desk once for the grades, stances, band z, regime
and the daily adjusted-close panel the 20-session targets are read from,
assembles the dataset (`deep_stage2.dataset`), walks each requested model
forward on every requested target at once (one network, one head per
target), prints one table row per (window, model, target) and the verdict
the plan fixes, and writes `<root>/desk/<--out>` (default
`deep_stage2.json`). `--export <npz>` writes the assembled dataset
(sequence as float16) so the GPU machine trains from `--dataset <npz>`
without the store; `--models none` with `--export` exits after writing.
`--benchmarks` names the market channels wanted (default SPY,QQQ,SMH);
the ones the store holds are used and the payload says which.

The protocol and the kill criteria are the pre-registration
`docs/research/deep-stage2-plan-2026-09-27.md`, implemented in
`backend/market/deep_stage2.py`. The choosing window is 2016-2023;
2024-2026 is reported, never tuned on. Nothing here trades.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from backend.cli.market_deep_intraday import _parse_names, default_desk, parse_out
from backend.cli.market_intraday_sip import select_tickers
from backend.cli.market_session_anatomy import (
    DEFAULT_WORKERS,
    load_cubes,
    membership_mask,
)
from backend.market import deep_intraday, deep_stage2, session_anatomy, universe
from backend.market.deep_stage2 import Dataset2
from backend.market.store import MarketStore

FILE = "deep_stage2.json"
# The packages a model needs beyond numpy.
REQUIRES = {model: ("torch",) for model in deep_stage2.TORCH_MODELS}


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Build the parser for the stage-2 study."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market", help="market store root")
    parser.add_argument(
        "--tickers", default="", help="comma-separated; default: the book"
    )
    parser.add_argument(
        "--benchmarks",
        default=",".join(deep_stage2.BENCHMARKS),
        help="comma-separated market channels wanted, in order (the store's are used)",
    )
    parser.add_argument(
        "--membership",
        type=Path,
        default=universe.MEMBERSHIP_HISTORY_PATH,
        help="dated membership history CSV for the point-in-time mask",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="processes building cubes in parallel (1 = in this process)",
    )
    parser.add_argument(
        "--models",
        default=",".join(deep_stage2.MODELS),
        help=f"comma-separated subset of {','.join(deep_stage2.MODELS)}, or none",
    )
    parser.add_argument(
        "--targets",
        default=",".join(deep_stage2.TARGETS),
        help=f"comma-separated subset of {','.join(deep_stage2.TARGETS)}",
    )
    parser.add_argument(
        "--device",
        default="auto",
        choices=deep_intraday.DEVICES,
        help="where the torch models train; auto is cuda when available",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=deep_stage2.K_SESSIONS,
        help=f"sessions of bars per row (the plan's {deep_stage2.K_SESSIONS})",
    )
    parser.add_argument(
        "--out",
        default=FILE,
        help=f"basename of the payload under <root>/desk/ (default {FILE})",
    )
    parser.add_argument(
        "--export",
        default=None,
        help="write the assembled dataset to this npz; with --models none, exit after",
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="train on a dataset written by --export (no store, no cubes, no desk)",
    )
    parser.add_argument("--json", action="store_true", help="print the payload as JSON")
    return parser


# The requested models, validated; "none" is empty.
def parse_models(spec: str) -> tuple[str, ...]:
    """Return the model names in `spec`, in order, each once."""
    if spec.strip().lower() == "none":
        return ()
    return _parse_names(spec, deep_stage2.MODELS, "--models")


# The requested targets, validated.
def parse_targets(spec: str) -> tuple[str, ...]:
    """Return the target names in `spec`, in order, each once."""
    return _parse_names(spec, deep_stage2.TARGETS, "--targets")


# The requested benchmarks, upper-cased, each once, in order.
def parse_benchmarks(spec: str) -> tuple[str, ...]:
    """Return the benchmark tickers in `spec`."""
    return tuple(dict.fromkeys(b.strip().upper() for b in spec.split(",") if b.strip()))


# A signed number, or a dash.
def _f(value: float | None, digits: int = 2, sign: bool = True) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return "-"
    return f"{value:+.{digits}f}" if sign else f"{value:.{digits}f}"


# One table row of the results.
def _row(r: dict[str, Any]) -> str:
    ic = r["ic"] or {}
    portfolio = r["portfolio"] or {}
    a_only = r["portfolio_a"] or {}
    auc = r["auc"] or {}
    decision = r["decision"] or {}
    vol = r["vol_r2"] or {}
    return (
        f"  {r['window']:<10}{r['model']:<20}{r['target']:<12}{r['rows']:>8}"
        f"{_f(ic.get('mean'), 4):>9}{_f(ic.get('t')):>7}"
        f"{_f(portfolio.get('mean_bp'), 1):>9}{_f(portfolio.get('t')):>7}"
        f"{_f(a_only.get('mean_bp'), 1):>9}{_f(a_only.get('t')):>7}"
        f"{_f(auc.get('auc'), 3, False):>7}"
        f"{_f(decision.get('mean_bp'), 1):>9}{_f(decision.get('t')):>7}"
        f"{_f(decision.get('gross_bp'), 1):>9}"
        f"{_f(vol.get('r2'), 4):>9}"
    )


# The payload as readable text: the dataset lines, the table, the verdict.
def render(payload: dict[str, Any]) -> str:
    """Return the study as text."""
    ds = payload["dataset"]
    lines = [
        f"deep stage 2 (study v{payload['version']}; choosing window"
        f" {payload['choosing_window']}; trials {payload['trials']} run of"
        f" {payload.get('trials_total', payload['trials'])};"
        f" device {payload.get('device', '-')})",
        f"  dataset: {ds['rows']:,} rows, {ds['names']} names,"
        f" {ds['sessions']:,} sessions {ds['first']}..{ds['last']};"
        f" {payload['constants']['k_sessions']} sessions x"
        f" {payload['constants']['slots']} bars x"
        f" {len(payload['constants']['channels'])} channels"
        f" ({', '.join(ds['benchmarks']) or 'no benchmarks'};"
        f" {ds['benchmark_fill']:,} benchmark rows zero-filled),"
        f" {len(payload['constants']['scalars'])} scalars; per window "
        + ", ".join(f"{k} {v:,}" for k, v in ds["rows_per_window"].items())
        + f"; A/A+ rows {ds['graded_rows']:,}; downgrade rows"
        f" {ds['downgrade_rows']:,} ({ds['downgrade_positives']:,} positive);"
        f" rows with a 20-session horizon {ds['horizon_rows']:,}",
    ]
    for name, count in payload.get("parameters", {}).items():
        lines.append(f"  {name} parameters: {count:,}")
    seen: set[str] = set()
    for key, fits in payload.get("fits", {}).items():
        model = key.split("/")[0]
        if fits and model not in seen:
            seen.add(model)
            seconds = sum(f["seconds"] for f in fits)
            lines.append(
                f"  {model}: {len(fits)} fits, {seconds:.0f} s in all,"
                f" first test {fits[0]['test_start']}"
            )
    lines.append(
        f"  {'window':<10}{'model':<20}{'target':<12}{'rows':>8}{'IC':>9}{'IC t':>7}"
        f"{'top bp/d':>9}{'t':>7}{'A bp/d':>9}{'t':>7}{'AUC':>7}"
        f"{'dec bp/s':>9}{'t':>7}{'gross':>9}{'vol R2':>9}"
    )
    for r in payload["results"]:
        lines.append(_row(r))
    c = payload["constants"]
    lines.append(
        f"  (IC: daily Spearman of the forecast against the realized value;"
        f" top: stage 1's top-{c['top_quantile']:.0%} portfolio at"
        f" {c['cost_bps']:.0f} bp minus equal weight; dec: the A/A+ book with the"
        f" worst {c['drop_quantile']:.0%} by forecast dropped minus the book,"
        f" bp per session over {c['horizon']}"
        f" sessions, net of {c['cost_bps']:.0f} bp on the extra turnover; t is"
        f" Newey-West at lag {c['hac_lag']})"
    )
    for line in payload.get("verdict_detail", []):
        lines.append(f"  {line}")
    lines.append(f"verdict: {payload['verdict']}")
    return "\n".join(lines)


# Walk every requested model forward on the requested targets on
# `device`; a model whose package cannot be imported is skipped with a
# note. Returns (forecasts keyed by (model, target), notes).
def forecast_all(
    ds: Dataset2,
    models: tuple[str, ...],
    say: Callable[[str], None],
    targets: tuple[str, ...] = deep_stage2.TARGETS,
    device: str = "auto",
) -> tuple[dict[tuple[str, str], deep_intraday.Forecast], list[str]]:
    """Return {(model, target): Forecast} and the skipped-model notes."""
    forecasts: dict[tuple[str, str], deep_intraday.Forecast] = {}
    skipped: list[str] = []
    for model in models:
        package = _missing(REQUIRES.get(model, ()))
        if package is not None:
            skipped.append(f"{model}: {package} is not importable here")
            say(skipped[-1])
            continue
        say(f"{model}: walking forward on {', '.join(targets)}")
        for target, forecast in deep_stage2.walk_forward(
            ds, model, targets, log=say, device=device
        ).items():
            forecasts[(model, target)] = forecast
    return forecasts, skipped


# The first of `packages` that cannot be imported here, or None.
def _missing(packages: tuple[str, ...]) -> str | None:
    import importlib

    for package in packages:
        try:
            importlib.import_module(package)
        except ImportError:
            return package
    return None


# Build the dataset from the store: the cubes of the book and the
# benchmarks, the membership mask, the desk report, the rows. Returns
# (dataset, cubes), or None (after saying why) when nothing can be built.
def build_from_store(
    args: argparse.Namespace,
    store: MarketStore,
    benchmarks: tuple[str, ...],
    say: Callable[[str], None],
    desk_run: Callable[[MarketStore], Any],
) -> tuple[Dataset2, dict[str, Any]] | None:
    """Return (dataset, cubes) built from the store, or None."""
    book = tuple(
        t
        for t in select_tickers(args.tickers)
        if t not in session_anatomy.BENCHMARKS and t not in benchmarks
    )
    cubes, lines = load_cubes(store, (*book, *benchmarks), workers=max(1, args.workers))
    say(f"cubes from {store.root} ({len(book)} names, {len(benchmarks)} benchmarks):")
    for line in lines:
        say(line)
    if not any(t in cubes for t in book):
        say("no complete sessions in the store")
        return None
    present = tuple(b for b in benchmarks if b in cubes)
    absent = tuple(b for b in benchmarks if b not in cubes)
    if absent:
        say(f"benchmarks without a cube in the store: {', '.join(absent)}")
    mask = membership_mask(cubes, args.membership)
    began = time.perf_counter()
    report = desk_run(store)
    say(f"desk run: {time.perf_counter() - began:.1f} s")
    began = time.perf_counter()
    ds = deep_stage2.dataset(cubes, mask, report, present, k=args.k)
    say(
        f"dataset: {len(ds):,} rows,"
        f" {len(np.unique(ds.tickers)) if len(ds) else 0} names,"
        f" {len(ds.sessions):,} sessions, x_seq {ds.x_seq.shape},"
        f" {ds.benchmark_fill:,} benchmark rows zero-filled,"
        f" {time.perf_counter() - began:.1f} s"
    )
    if len(ds) == 0:
        say("no rows after the membership, completeness and desk rules")
        return None
    return ds, cubes


# Load, mask, grade, build, walk forward, score, write, print. `desk_run`
# returns the desk report for a store; the default runs the live rule.
def run(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    desk_run: Callable[[MarketStore], Any] | None = None,
) -> int:
    """Run the study for the parsed arguments; return the exit code."""
    root = Path(args.root)
    store = MarketStore(root)
    models = parse_models(args.models)
    targets = parse_targets(args.targets)
    benchmarks = parse_benchmarks(args.benchmarks)
    out_name = parse_out(args.out)
    device = deep_intraday.resolve_device(args.device, deep_intraday.cuda_available())
    quiet = bool(args.json)

    # Progress lines, silenced under --json so the output stays JSON.
    def say(text: str) -> None:
        if not quiet:
            print(text, file=out)

    cubes: dict = {}
    if args.dataset:
        ds = deep_stage2.load_dataset(Path(args.dataset))
        say(
            f"dataset from {args.dataset}: {len(ds):,} rows,"
            f" {len(np.unique(ds.tickers)) if len(ds) else 0} names,"
            f" {len(ds.sessions):,} sessions, {ds.k} sessions of bars,"
            f" benchmarks {', '.join(ds.benchmarks) or 'none'}"
        )
    else:
        built = build_from_store(args, store, benchmarks, say, desk_run or default_desk)
        if built is None:
            print("no rows to study (see the lines above)", file=out)
            return 1
        ds, cubes = built
    if args.export:
        written = deep_stage2.save_dataset(Path(args.export), ds)
        print(
            f"wrote dataset {written} ({len(ds):,} rows, sequence as float16)", file=out
        )
        if not models:
            return 0
    deep_intraday.announce_device(device, say)
    forecasts, skipped = forecast_all(ds, models, say, targets, device)
    payload = deep_stage2.study(ds, forecasts)
    payload["root"] = str(root)
    payload["membership_history"] = str(args.membership)
    payload["requested"] = {
        "models": list(models),
        "targets": list(targets),
        "benchmarks": list(benchmarks),
    }
    payload["device"] = device
    payload["skipped"] = skipped
    payload["exclusions"] = {t: c.excluded for t, c in cubes.items()}
    payload["sessions_per_ticker"] = {t: len(c) for t, c in cubes.items()}
    payload["asof"] = str(
        max(c.dates[-1] for c in cubes.values()) if cubes else ds.sessions[-1]
    )
    payload["dataset_file"] = str(args.dataset) if args.dataset else None
    path = root / "desk" / out_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    if quiet:
        print(json.dumps(payload, indent=2, allow_nan=False), file=out)
    else:
        print(render(payload), file=out)
        print(f"\nwrote {path}", file=out)
    return 0


# Entry point.
def main(argv: list[str] | None = None) -> int:
    """Parse the arguments and run."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
