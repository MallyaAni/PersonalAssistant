"""Adaptive entry: the three registered buy fills against the fixed 1% dip.

    python -m backend.cli.market_adaptive_entry --root data/market \\
        --offsets 20 --out data/market/research/adaptive_entry/adaptive_entry.json

`docs/research/adaptive-entry-plan-2026-09-30.md` registers the study;
`backend/market/adaptive_entry.py` prices and judges it. The command runs
the desk as the stage-4 decision test does (`market_stage4_decisions.
load_inputs`: the desk report and the SIP cubes; the EDGAR records it also
loads are not read), restricts it to the point-in-time book, builds the
fill grids, runs the control executor under `graded-equal-weight/5`
(`policy_v5.allocator`) from each of the `--offsets` start offsets
(`--max-offsets` prices fewer, a smoke run), writes the payload (`--out`,
with the git revision and the membership file's sha256) and prints one
verdict line per candidate. Nothing here trades or changes the executor.
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
from backend.market import adaptive_entry as ae
from backend.market import stage3_io as io
from backend.market import stage4_orders as so
from backend.market import universe
from backend.market.store import MarketStore

FILE = "research/adaptive_entry/adaptive_entry.json"


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
        "--offsets", type=int, default=ae.OFFSETS, help="the registered offsets"
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


# Check the arguments, load, build the grids, run the offsets, price,
# judge, write and print. `loader` replaces `load_inputs` (tests). Exit
# codes: 0 done, 1 the membership file is missing, 2 an argument is
# refused - both before the desk runs.
def run(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    loader: Callable[..., tuple[Any, dict[str, Any], dict[str, Any]]] | None = None,
) -> int:
    """Run the study; return the exit code."""
    began = time.perf_counter()

    # Print one timed progress line.
    def say(text: str) -> None:
        print(f"[{time.perf_counter() - began:7.0f} s] {text}", file=out, flush=True)

    if not Path(args.membership).exists():
        print(f"file not found: {args.membership}", file=out)
        return 1
    if args.offsets < 1 or (args.max_offsets is not None and args.max_offsets < 1):
        print("--offsets and --max-offsets must be at least 1", file=out)
        return 2
    root = Path(args.root)
    load = loader or load_inputs
    report, cubes, _ = load(MarketStore(root), args.workers, say)
    restricted, mask = point_in_time.point_in_time(report, args.membership)
    panel = restricted.panel
    fills, next_bar, oracle, oracle_five, coverage = ae.fill_grids(panel, cubes)
    say(f"fills: {coverage['names_with_cube']} names with a cube")
    market = ae.build_market(
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
    payload = ae.evaluate(runs, market, registered=args.offsets)
    payload["run"] = run_record(args, panel, coverage)
    payload["run"]["seconds"] = time.perf_counter() - began
    target = Path(args.out) if args.out is not None else root / FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(io.clean_json(payload), indent=2, allow_nan=False)
    target.write_text(text, encoding="utf-8")
    print(text if args.json else render(json.loads(text)), file=out)
    print(f"wrote {target}", file=out)
    return 0


# A number to `digits` decimals with its sign, "n/a" when missing.
def _num(x: Any, digits: int = 2) -> str:
    """Return `x` signed, "n/a" for None or NaN."""
    return "n/a" if x is None or x != x else f"{float(x):+.{digits}f}"


# The payload as the lines people read: what was run, the buys, the drift,
# then the verdict and one line per candidate.
def render(payload: dict[str, Any]) -> str:
    """Return the verdict text of a payload."""
    offsets = payload["offsets"]
    control = payload["control"]
    median = payload["orders"]["median_by_window"]
    model = payload["windows"][ae.MODEL][0]
    head = (
        f"adaptive entry ({payload['plan']}) as of {payload['asof']}: "
        f"{len(ae.CANDIDATES)} candidates on the {control['basis']} buys of "
        f"{control['executor']} "
        f"under {control['policy']} against {control['fills']}; {offsets['priced']} of "
        f"{offsets['registered']} offsets, statistics at offset {offsets['median']}; "
        f"model window {model}..2023-12-29; Newey-West lag {payload['hac_lag']}"
    )
    orders = "; ".join(
        f"{w} {m['buys']} buys over {m['decision_sessions']} sessions"
        for w, m in median.items()
    )
    drift = "; ".join(
        f"{w} {_num(d['mu_bp'])} bp/session over {d['name_days']} A/A+ name-days"
        for w, d in payload["drift"].items()
    )
    lines = [
        head,
        f"buys at the median offset: {orders}",
        f"drift: {drift}",
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
