"""The catastrophe stop: a single-name stop priced on the `/4` book, from entry and from peak.

    python -m backend.cli.market_catastrophe_stop --root data/market
    python -m backend.cli.market_catastrophe_stop --offsets 20 --costs 10 25 --json

Runs the desk, restricts the report to the point-in-time book
(`point_in_time.point_in_time` on the dated membership file) and prices
`policy_v4.allocator(mask)` under plain next-open fills with each stop in
`catastrophe_stop.VARIANTS` - the control, then a sale on the first close
40, 50 or 60% below the entry close and the same below the peak close since
entry - from every start offset of the 20-session clock at each cost.
Prints a table (variant x window: median CAGR, median worst drawdown, worst
single-name day, triggers a year, false-alarm rate, bp a day against the
control and its Newey-West t, offsets above the control), the verdict
(ADOPT (registered) or RECORD under the floors `catastrophe_stop` fixes,
with the insurance premium) and the twenty deepest triggers. Writes
`<root>/desk/catastrophe_stop.json`. Nothing here trades or changes the
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
from backend.market import catastrophe_stop, universe
from backend.market.session_anatomy import json_ready
from backend.market.store import MarketStore

FILE = "catastrophe_stop.json"
TOP_TRIGGERS = 20


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Build the parser for the catastrophe-stop trial."""
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
def _pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None or x != x else f"{x * 100:.{digits}f}%"


# A signed number, "n/a" for NaN or None.
def _num(x: float | None, digits: int = 2) -> str:
    return "n/a" if x is None or x != x else f"{x:+.{digits}f}"


# A plain number, "n/a" for NaN or None.
def _plain(x: float | None, digits: int = 2) -> str:
    return "n/a" if x is None or x != x else f"{x:.{digits}f}"


# The paired entry for a line against the control in a window at a cost, or {}.
def _pair(payload: dict[str, Any], line: str, window: str, cost: float) -> dict:
    for p in payload["paired"]:
        if (
            p["line"] == line
            and p["against"] == catastrophe_stop.NONE
            and p["window"] == window
            and float(p["cost_bps"]) == float(cost)
        ):
            return p
    return {}


# The deepest triggers across the stored variants, deepest first.
def top_triggers(payload: dict[str, Any], count: int = TOP_TRIGGERS) -> list[dict]:
    """Return up to `count` triggers, deepest first, each tagged with its variant."""
    pooled: list[dict] = []
    for name, triggers in payload.get("triggers", {}).items():
        for tr in triggers:
            pooled.append({"variant": name, **tr})
    pooled.sort(key=lambda tr: tr["drawdown"] if tr["drawdown"] is not None else 0.0)
    return pooled[:count]


# The payload as a table people can read, the verdict, then the triggers.
def render(payload: dict[str, Any]) -> str:
    """Return the trial's tables, verdict and deepest triggers as text."""
    lines = [
        f"catastrophe stop for {payload['policy']} as of {payload['asof']}: "
        f"{payload['trials']} registered variants, {payload['offsets']} offsets "
        f"(paired statistics at the median offset, Newey-West lag "
        f"{payload['hac_lag']}; "
        f"recovery read over {payload['recovery_sessions']} sessions)"
    ]
    for cost in payload["costs_bps"]:
        for window in payload["windows"]:
            lines.append(f"\n{cost:g} bp, {window}")
            lines.append(
                f"  {'variant':<10}{'CAGR':>8}{'maxDD':>8}{'worst1':>8}{'trig/y':>8}"
                f"{'false':>7}{'vs none':>9}{'t':>7}{'>none':>7}"
            )
            for row in payload["rows"]:
                if float(row["cost_bps"]) != float(cost) or row["window"] != window:
                    continue
                vp = _pair(payload, row["line"], window, cost)
                lines.append(
                    f"  {row['line']:<10}{_pct(row['median_cagr']):>8}"
                    f"{_pct(row['median_drawdown']):>8}"
                    f"{_pct(row['worst_name_day'], 2):>8}"
                    f"{_plain(row['triggers_per_year'], 1):>8}"
                    f"{_pct(row['false_alarm_rate'], 0):>7}"
                    f"{_num(vp.get('mean_daily_bp'), 1):>9}{_num(vp.get('hac_t')):>7}"
                    f"{row['offsets_above_control']:>7}"
                )
    lines.append(f"\nverdict: {payload['verdict']['text']}")
    top = top_triggers(payload)
    lines.append(
        f"\ndeepest {len(top)} triggers (median offset at "
        f"{payload['verdict']['cost_bps']:g} bp):"
    )
    if top:
        lines.append(
            f"  {'variant':<10}{'ticker':<8}{'entered':<12}{'entry':>9}  {'fired':<12}"
            f"{'price':>9}{'drawdown':>10}{'recovered':>10}"
        )
    for tr in top:
        recovered = (
            "n/a"
            if tr["recovered"] is None
            else (f"in {tr['recovery_sessions']}" if tr["recovered"] else "no")
        )
        lines.append(
            f"  {tr['variant']:<10}{tr['ticker']:<8}{tr['entry_date']:<12}"
            f"{_plain(tr['entry_price']):>9}  {tr['trigger_date']:<12}"
            f"{_plain(tr['trigger_price']):>9}{_pct(tr['drawdown']):>10}{recovered:>10}"
        )
    return "\n".join(lines)


# Run the desk, restrict, price every variant, write and print.
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
    payload = catastrophe_stop.run_variants(
        report,
        restricted,
        mask,
        store,
        max(1, args.offsets),
        tuple(float(c) for c in args.costs),
    )
    payload["verdict"] = catastrophe_stop.verdict(payload)
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
