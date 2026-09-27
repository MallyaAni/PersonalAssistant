"""The execution ablation: the live policy's options switched off one at a time on the `/4` book.

    python -m backend.cli.market_execution_ablation --root data/market
    python -m backend.cli.market_execution_ablation --offsets 20 --costs 10 25 --json

Runs the desk, restricts the report to the point-in-time book
(`point_in_time.point_in_time` on the dated membership file) and prices
`policy_v4.allocator(mask)` under every option set in
`execution_ablation.VARIANTS` - plain next-open fills, the full live
execution policy, live with each option removed, plain with one option
added - from every start offset of the 20-session clock at each cost.
Prints a table (variant x window: median CAGR, median worst drawdown, bp a
day against plain and its Newey-West t, the same against live, offsets
above plain) and the verdict: the CAGR points each option's removal earns
or costs on 2016-2023 at 25 bp, REMOVE (registered) or KEEP under the
floors `execution_ablation` fixes, and the reconstruction check. Writes
`<root>/desk/execution_ablation.json`. Nothing here trades or changes the
executor.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from backend.agents.trading.desk import point_in_time
from backend.market import execution_ablation, universe
from backend.market.session_anatomy import json_ready
from backend.market.store import MarketStore

FILE = "execution_ablation.json"


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Build the parser for the execution ablation."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market", help="market store root")
    parser.add_argument(
        "--membership",
        type=Path,
        default=universe.MEMBERSHIP_HISTORY_PATH,
        help="dated membership history CSV for the point-in-time book",
    )
    parser.add_argument(
        "--offsets", type=int, default=20, help="start offsets on the 20-session clock"
    )
    parser.add_argument(
        "--costs",
        type=float,
        nargs="+",
        default=[10.0, 25.0],
        help="one-way costs in basis points; the verdict reads 25",
    )
    parser.add_argument("--json", action="store_true", help="print the payload as JSON")
    return parser


# The desk report for the store, the way every published curve gets it.
def default_desk(store: MarketStore) -> Any:
    """Return the desk report for the store."""
    from backend.agents.trading.desk import desk

    return desk.run(store, None, inputs=(desk.EXPECTATIONS_GAP,))


# A fraction as a percentage string, "n/a" for NaN or None.
def _pct(x: float | None) -> str:
    return "n/a" if x is None or x != x else f"{x * 100:.1f}%"


# A signed number, "n/a" for NaN or None.
def _num(x: float | None, digits: int = 2) -> str:
    return "n/a" if x is None or x != x else f"{x:+.{digits}f}"


# The paired entry for a line against a base in a window at a cost, or {}.
def _pair(
    payload: dict[str, Any], line: str, against: str, window: str, cost: float
) -> dict:
    for p in payload["paired"]:
        if (
            p["line"] == line
            and p["against"] == against
            and p["window"] == window
            and float(p["cost_bps"]) == float(cost)
        ):
            return p
    return {}


# The payload as a table people can read, then the verdict.
def render(payload: dict[str, Any]) -> str:
    """Return the ablation's tables, refusals and verdict as text."""
    lines = [
        f"execution ablation for {payload['policy']} as of {payload['asof']}: "
        f"{payload['trials']} registered variants, {payload['offsets']} offsets "
        f"(paired statistics at the median offset, Newey-West lag {payload['hac_lag']})"
    ]
    for cost in payload["costs_bps"]:
        for window in payload["windows"]:
            lines.append(f"\n{cost:g} bp, {window}")
            lines.append(
                f"  {'variant':<24}{'CAGR':>8}{'maxDD':>8}{'vs plain':>10}{'t':>7}"
                f"{'vs live':>10}{'t':>7}{'>plain':>8}"
            )
            for row in payload["rows"]:
                if float(row["cost_bps"]) != float(cost) or row["window"] != window:
                    continue
                vp = _pair(payload, row["line"], execution_ablation.PLAIN, window, cost)
                vl = _pair(payload, row["line"], execution_ablation.LIVE, window, cost)
                lines.append(
                    f"  {row['line']:<24}{_pct(row['median_cagr']):>8}"
                    f"{_pct(row['median_drawdown']):>8}"
                    f"{_num(vp.get('mean_daily_bp'), 1):>10}{_num(vp.get('hac_t')):>7}"
                    f"{_num(vl.get('mean_daily_bp'), 1):>10}{_num(vl.get('hac_t')):>7}"
                    f"{row['offsets_above_plain']:>8}"
                )
    if payload.get("refused"):
        lines.append("\nrefused:")
        for name, reason in payload["refused"].items():
            lines.append(f"  {name}: {reason}")
    lines.append(f"\nverdict: {payload['verdict']['text']}")
    return "\n".join(lines)


# Run the desk, restrict, price every variant, write and print.
def run(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    desk_run: Callable[[MarketStore], Any] | None = None,
) -> int:
    """Run the ablation for the parsed arguments; return the exit code."""
    root = Path(args.root)
    store = MarketStore(root)
    report = (desk_run or default_desk)(store)
    restricted, mask = point_in_time.point_in_time(report, args.membership)
    payload = execution_ablation.run_variants(
        report,
        restricted,
        mask,
        store,
        max(1, args.offsets),
        tuple(float(c) for c in args.costs),
    )
    payload["verdict"] = execution_ablation.verdict(payload)
    payload["root"] = str(root)
    payload["membership_history"] = str(args.membership)
    payload = json_ready(payload)
    target = root / "desk" / FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, indent=2, allow_nan=False), file=out)
    else:
        print(render(payload), file=out)
        print(f"\nwrote {target}", file=out)
    return 0


# Entry point.
def main(argv: list[str] | None = None) -> int:
    """Parse the arguments and run."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
