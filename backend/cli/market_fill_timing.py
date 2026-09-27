"""The fill-timing trial: the `/4` policy's orders under seven fill conventions.

    python -m backend.cli.market_fill_timing --root data/market --workers 8
    python -m backend.cli.market_fill_timing --tickers AVGO,NVDA --offsets 5 --json

Runs the desk, restricts the report to the point-in-time book
(`point_in_time.point_in_time` on the dated membership file), loads one SIP
session cube per name (`market_session_anatomy.load_cubes`, cached under
`<root>/research/sip_cubes/`), and runs `fill_timing.study`: the plain
simulator's orders for `graded-equal-weight/4` priced at each of the seven
conventions fixed in `docs/research/execution-timing-plan-2026-09-27.md`,
from every start offset, at one cost. Prints a table (convention x window:
median CAGR, bp a day against `next_open`, its Newey-West t, offsets above
the control, deferrals and fallbacks), the best convention's deflated
Sharpe, the gap between this engine's control and `simulate.run`, and the
verdict under the plan's kill criteria. Writes `<root>/desk/fill_timing.json`.
Nothing here trades or changes the executor.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from backend.agents.trading.desk import point_in_time
from backend.cli.market_session_anatomy import DEFAULT_WORKERS, load_cubes
from backend.market import fill_timing, universe
from backend.market.session_anatomy import json_ready
from backend.market.store import MarketStore

FILE = "fill_timing.json"


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Build the parser for the fill-timing trial."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market", help="market store root")
    parser.add_argument(
        "--tickers",
        default="",
        help="comma-separated names to load cubes for; default: every panel name",
    )
    parser.add_argument(
        "--membership",
        type=Path,
        default=universe.MEMBERSHIP_HISTORY_PATH,
        help="dated membership history CSV for the point-in-time book",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="processes building cubes in parallel (1 = in this process)",
    )
    parser.add_argument(
        "--offsets", type=int, default=20, help="start offsets on the 20-session clock"
    )
    parser.add_argument(
        "--cost",
        type=float,
        default=fill_timing.COST_BPS[0],
        help="one-way cost in basis points on every fill",
    )
    parser.add_argument("--json", action="store_true", help="print the payload as JSON")
    return parser


# The desk report for the store, the way every published curve gets it.
def default_desk(store: MarketStore) -> Any:
    """Return the desk report for the store."""
    from backend.agents.trading.desk import desk

    return desk.run(store, None, inputs=(desk.EXPECTATIONS_GAP,))


# A fraction as a percentage string, "n/a" for NaN.
def _pct(x: float | None) -> str:
    return "n/a" if x is None or x != x else f"{x * 100:.1f}%"


# A signed number to two decimals, "n/a" for NaN.
def _num(x: float | None, digits: int = 2) -> str:
    return "n/a" if x is None or x != x else f"{x:+.{digits}f}"


# The payload as a table people can read.
def render(payload: dict[str, Any]) -> str:
    """Return the trial's table, best lines, gap and verdict as text."""
    lines = [
        f"fill-timing trial for {payload['policy']} at {payload['cost_bps']:g} bp, "
        f"{payload['offsets']} offsets (paired statistics at offset "
        f"{payload['median_offset']})"
    ]
    cover = payload["cube_coverage"]
    lines.append(
        f"cubes: {cover['names_with_cube']} of {cover['names_in_panel']} panel names"
    )
    for window in payload["windows"]:
        lines.append(f"\n{window}")
        lines.append(
            f"  {'convention':<17}{'CAGR':>8}{'vs open':>9}{'bp/d':>8}{'t':>7}"
            f"{'>open':>7}{'defer':>7}{'fallbk':>8}{'fills':>7}"
        )
        for row in payload["rows"]:
            if row["window"] != window:
                continue
            lines.append(
                f"  {row['convention']:<17}{_pct(row['median_cagr']):>8}"
                f"{_pct(row['median_cagr_vs_open']):>9}"
                f"{_num(row['mean_daily_bp_vs_open'], 1):>8}"
                f"{_num(row['hac_t_vs_open']):>7}"
                f"{row['offsets_above_open']:>7}{row['deferrals']:>7}"
                f"{row['fallbacks']:>8}{row['fills']:>7}"
            )
        best = payload["best"].get(window, {})
        if best.get("convention"):
            lines.append(
                f"  best: {best['convention']} "
                f"{_num(best['mean_daily_bp_vs_open'], 1)} bp/d, "
                f"t {_num(best['hac_t_vs_open'])}, deflated Sharpe "
                f"{_num(best['deflated_sharpe'])} against {best['trials']} trials"
            )
    gap = payload["simulator_gap"]
    lines.append(
        f"\nnext_open against simulate.run at offset {gap['offset']}: mean |gap| "
        f"{_num(gap['mean_abs_bp'], 3)} bp/d, max {_num(gap['max_abs_bp'], 3)} bp/d, "
        f"{gap['nan_mismatch']} NaN mismatches over {gap['sessions']} sessions"
    )
    lines.append(f"\nverdict: {payload['verdict']}")
    lines.append(payload["breakout_gate"])
    return "\n".join(lines)


# Run the desk, restrict, load the cubes, study, write and print.
def run(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    desk_run: Callable[[MarketStore], Any] | None = None,
) -> int:
    """Run the trial for the parsed arguments; return the exit code."""
    root = Path(args.root)
    store = MarketStore(root)
    report = (desk_run or default_desk)(store)
    restricted, mask = point_in_time.point_in_time(report, args.membership)
    panel = restricted.panel
    if args.tickers:
        tickers = tuple(
            dict.fromkeys(
                t.strip().upper() for t in args.tickers.split(",") if t.strip()
            )
        )
    else:
        tickers = tuple(t for t in panel.tickers if t != panel.benchmark)
    cubes, lines = load_cubes(store, tickers, workers=max(1, args.workers))
    if not args.json:
        print(f"cubes from {root} ({len(tickers)} tickers requested):", file=out)
        for line in lines:
            print(line, file=out)
    if not cubes:
        print("no complete sessions in the store; nothing to price", file=out)
        return 1
    payload = fill_timing.study(
        restricted, cubes, mask, offsets=max(1, args.offsets), cost=args.cost
    )
    payload["root"] = str(root)
    payload["membership_history"] = str(args.membership)
    payload["exclusions"] = {t: c.excluded for t, c in cubes.items()}
    payload["sessions_per_ticker"] = {t: len(c) for t, c in cubes.items()}
    payload["asof"] = str(panel.dates[-1])
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
