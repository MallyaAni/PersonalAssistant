"""Structure rules S1: six level-aware fills against the board's dip_or_close.

    python -m backend.cli.market_structure_rules --root data/market \\
        --offsets 20 --out docs/research/scorecards/structure-rules/structure_rules.json

    python -m backend.cli.market_structure_rules --notch control.json notch.json \\
        --fills structure_rules.json

`docs/research/structure-rules-plan-2026-09-30.md` registers the study;
`backend/market/structure_rules.py` prices and judges it. The command runs
the desk as the adaptive-entry study does (`market_stage4_decisions.
load_inputs`: the desk report and the SIP cubes; the EDGAR records it also
loads are not read), reads the index cube (`sip_cube.load` on the panel's
benchmark; absent, S1e is the control everywhere and the payload says so),
restricts the desk to the point-in-time book, builds the fill grids on both
sides, runs the control executor under `graded-equal-weight/5` from each of
the `--offsets` start offsets (`--max-offsets` prices fewer, a smoke run),
writes the payload (`--out`, with the git revision and the membership
file's sha256) and prints one verdict line per candidate.

`--notch CONTROL NOTCH` judges S1g instead: two point-in-time scorecard
payloads (`market_pit_scorecard --graded-cap 0.25`, without and with
`--structure-notch`) on the plan's book gate and drawdown route, the
deflated Sharpe's trial variance from `--fills` (this study's payload)
when given; writes `structure_notch_verdict.json` beside the notch payload.
Nothing here trades or changes the executor or the analyst.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from backend.agents.trading.desk import point_in_time, policy_v5
from backend.cli.market_stage4_decisions import _sha256, load_inputs, revision
from backend.market import sip_cube, universe
from backend.market import stage3_io as io
from backend.market import stage4_orders as so
from backend.market import structure_rules as sr
from backend.market.store import MarketStore

FILE = "research/structure_rules/structure_rules.json"
NOTCH_FILE = "structure_notch_verdict.json"


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", default="data/market", help="market store root")
    parser.add_argument(
        "--membership",
        type=Path,
        default=universe.MEMBERSHIP_HISTORY_PATH,
        help="dated membership history CSV for the point-in-time book",
    )
    parser.add_argument(
        "--offsets", type=int, default=sr.OFFSETS, help="the registered offsets"
    )
    parser.add_argument(
        "--max-offsets", type=int, default=None, help="price only this many (smoke)"
    )
    parser.add_argument(
        "--cost", type=float, default=so.COST_BPS, help="the control run's cost, bp"
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--out", type=Path, default=None, help=f"the payload (default <root>/{FILE})"
    )
    parser.add_argument("--json", action="store_true", help="print the payload as JSON")
    parser.add_argument(
        "--notch",
        nargs=2,
        type=Path,
        metavar=("CONTROL", "NOTCH"),
        default=None,
        help="judge S1g from two point-in-time scorecard payloads instead",
    )
    parser.add_argument(
        "--fills",
        type=Path,
        default=None,
        help="this study's payload, for the notch verdict's trial variance",
    )
    return parser


# The run's record: the store, the code revision, the cost, the membership
# file's sha256, the panel and the cube coverage.
def run_record(
    args: argparse.Namespace, panel: Any, coverage: dict[str, Any]
) -> dict[str, Any]:
    """Return the payload's "run" block."""
    tickers = [t for t in panel.tickers if t != panel.benchmark]
    return {
        "root": str(args.root),
        "revision": revision(),
        "cost_bps": float(args.cost),
        "basis": so.EXECUTED,
        "policy": policy_v5.POLICY_VERSION,
        "inputs": {
            "membership": {
                "file": str(args.membership),
                "sha256": _sha256(args.membership),
            }
        },
        "panel": {
            "sessions": len(panel.dates),
            "names": len(tickers),
            "benchmark": panel.benchmark,
            "first": str(panel.dates[0]),
            "last": str(panel.dates[-1]),
        },
        "cubes": coverage,
    }


# The index cube for S1e: the panel's benchmark from the SIP partitions,
# None (logged) when the store has none or the cube is empty.
def load_spy(store: MarketStore, benchmark: str, log: Callable[[str], None]):
    """Return the benchmark's SessionCube, or None."""
    try:
        cube = sip_cube.load(store, str(benchmark))
    except Exception as exc:  # noqa: BLE001 - S1e then applies the control
        log(f"{benchmark} cube: not read ({type(exc).__name__}: {exc})")
        log("S1e is the control on every session")
        return None
    if not len(cube):
        log(f"{benchmark} cube: no complete sessions; S1e is the control")
        return None
    log(f"{benchmark} cube: {len(cube)} sessions {cube.dates[0]}..{cube.dates[-1]}")
    return cube


# Check the arguments, load, build the grids, run the offsets, price,
# judge, write and print; or, with --notch, judge S1g from two payloads.
# `loader` replaces `load_inputs` and `spy_loader` `load_spy` (tests).
# Exit codes: 0 done, 1 an input file is missing, 2 an argument is refused
# - both before the desk runs.
def run(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    loader: Callable[..., tuple[Any, dict[str, Any], dict[str, Any]]] | None = None,
    spy_loader: Callable[..., Any] | None = None,
) -> int:
    """Run the study; return the exit code."""
    began = time.perf_counter()

    # Print one timed progress line.
    def say(text: str) -> None:
        print(f"[{time.perf_counter() - began:7.0f} s] {text}", file=out, flush=True)

    if args.notch is not None:
        return run_notch(args, out)
    if not Path(args.membership).exists():
        print(f"file not found: {args.membership}", file=out)
        return 1
    if args.offsets < 1 or (args.max_offsets is not None and args.max_offsets < 1):
        print("--offsets and --max-offsets must be at least 1", file=out)
        return 2
    root = Path(args.root)
    store = MarketStore(root)
    load = loader or load_inputs
    report, cubes, _ = load(store, args.workers, say)
    restricted, mask = point_in_time.point_in_time(report, args.membership)
    panel = restricted.panel
    spy = (spy_loader or load_spy)(store, panel.benchmark, say)
    fills, next_bar, oracle, oracle_five, coverage = sr.fill_grids(panel, cubes, spy)
    say(
        f"fills: {coverage['names_with_cube']} names with a cube; "
        f"{coverage['name_sessions_with_level']} name-sessions with a level"
    )
    market = sr.build_market(
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
    payload = sr.evaluate(runs, market, registered=args.offsets)
    payload["run"] = run_record(args, panel, coverage)
    payload["run"]["seconds"] = time.perf_counter() - began
    target = Path(args.out) if args.out is not None else root / FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(io.clean_json(payload), indent=2, allow_nan=False)
    target.write_text(text, encoding="utf-8")
    print(text if args.json else render(json.loads(text)), file=out)
    print(f"wrote {target}", file=out)
    return 0


# S1g's verdict from the two scorecard payloads named by --notch, the trial
# variance from --fills when given; writes the verdict beside the notch
# payload (or at --out) and prints its lines. Exit 1 when a file is missing.
def run_notch(args: argparse.Namespace, out: TextIO = sys.stdout) -> int:
    """Judge the structure notch; return the exit code."""
    control_path, notch_path = (Path(p) for p in args.notch)
    for path in (control_path, notch_path, args.fills):
        if path is not None and not Path(path).exists():
            print(f"file not found: {path}", file=out)
            return 1
    control = json.loads(control_path.read_text(encoding="utf-8"))
    notch = json.loads(notch_path.read_text(encoding="utf-8"))
    variance = float("nan")
    fills_record: dict[str, Any] | None = None
    if args.fills is not None:
        fills = json.loads(Path(args.fills).read_text(encoding="utf-8"))
        first = next(iter(fills["deflated"].values()))
        variance = float(first["trial_variance"] or "nan")
        fills_record = {"file": str(args.fills), "sha256": _sha256(Path(args.fills))}
    reading = sr.notch_verdict(control, notch, variance)
    reading["inputs"] = {
        "control": {"file": str(control_path), "sha256": _sha256(control_path)},
        "notch": {"file": str(notch_path), "sha256": _sha256(notch_path)},
        "fills": fills_record,
        "revision": revision(),
    }
    target = Path(args.out) if args.out is not None else notch_path.parent / NOTCH_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(io.clean_json(reading), indent=2, allow_nan=False)
    target.write_text(text, encoding="utf-8")
    print(text if args.json else "\n".join(reading["lines"]), file=out)
    print(f"wrote {target}", file=out)
    return 0


# A number to `digits` decimals with its sign, "n/a" when missing.
def _num(x: Any, digits: int = 2) -> str:
    """Return `x` signed, "n/a" for None or NaN."""
    return "n/a" if x is None or x != x else f"{float(x):+.{digits}f}"


# The payload as the lines people read: what was run, the orders, the
# drift, then the verdict and one line per candidate.
def render(payload: dict[str, Any]) -> str:
    """Return the verdict text of a payload."""
    offsets = payload["offsets"]
    control = payload["control"]
    median = payload["orders"]["median_by_window"]
    model = payload["windows"][sr.MODEL][0]
    cubes = payload.get("run", {}).get("cubes", {})
    head = (
        f"structure rules ({payload['plan']}) as of {payload['asof']}: "
        f"{len(sr.CANDIDATES)} candidates on the {control['basis']} orders of "
        f"{control['executor']} "
        f"under {control['policy']} against {control['fills']}; {offsets['priced']} of "
        f"{offsets['registered']} offsets, statistics at offset {offsets['median']}; "
        f"model window {model}..2023-12-29; Newey-West lag {payload['hac_lag']}"
    )
    orders = "; ".join(
        f"{w} {m['buys']} buys and {m['sells']} sells over {m['decision_sessions']} "
        "sessions"
        for w, m in median.items()
    )
    drift = "; ".join(
        f"{w} {_num(d['mu_bp'])} bp/session over {d['name_days']} A/A+ name-days"
        for w, d in payload["drift"].items()
    )
    spy = (
        f"SPY cube: {cubes.get('spy_sessions', 0)} sessions"
        if cubes.get("spy_sessions")
        else "SPY cube: absent (S1e is the control)"
    )
    lines = [
        head,
        f"orders at the median offset: {orders}",
        f"drift: {drift}",
        spy,
        "",
        payload["verdict"]["text"],
    ]
    lines += [f"  {line}" for line in payload["verdict"]["lines"]]
    return "\n".join(lines)


# Entry point.
def main(argv: list[str] | None = None) -> int:
    """Parse and run."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
