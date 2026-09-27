"""The mid-cycle rule redesigned for the `/4` book: entry variants under live execution.

    python -m backend.cli.market_midcycle_ew --root data/market
    python -m backend.cli.market_midcycle_ew --offsets 20 --costs 10 25 --json
    python -m backend.cli.market_midcycle_ew --only mc-redeploy reset-full-invest \
        --merge data/market/desk/midcycle_ew.json

Runs the desk, restricts the report to the point-in-time book
(`point_in_time.point_in_time` on the dated membership file) and prices
`policy_v4.allocator(mask)` under every variant in `midcycle_ew.VARIANTS` -
live without the mid-cycle rule (the ablation's anchor), live, and the live
policy with the mid-cycle entry leg alone modified - from every start
offset of the 20-session clock at each cost. Prints a table (variant x
window: median CAGR, median worst drawdown, bp a day against live and its
Newey-West t, the same against mc-off, offsets above live), the
diagnostics read off each run's ledger (mid-cycle turnover, cash share,
entries and exits a year, entry weight, entries still held at the next
rebalance, exits the rebalance buys back; where the cash comes from) and
the verdict under the floors `midcycle_ew` fixes, with the exposure-adjusted
reading and the per-offset sign test beside it. `--only` prices the named
variants and the two anchors alone; `--merge <path>` folds that run into an
earlier payload of the same study, keeping the earlier rows of every line
this run did not price, and the verdict is recomputed on the merged rows.
Writes `<root>/desk/midcycle_ew.json`. Nothing here trades or changes the
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
from backend.market import midcycle_ew, universe
from backend.market.session_anatomy import json_ready
from backend.market.store import MarketStore

FILE = "midcycle_ew.json"


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Build the parser for the mid-cycle study."""
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
    parser.add_argument(
        "--only",
        nargs="+",
        default=None,
        metavar="VARIANT",
        help="price only these variants (the anchors live and mc-off always are)",
    )
    parser.add_argument(
        "--merge",
        type=Path,
        default=None,
        help="an earlier payload of this study to fold this run into",
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


# A plain number, "n/a" for NaN or None.
def _plain(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None or x != x else f"{x:.{digits}f}"


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


# The payload as tables people can read - results, then diagnostics - then the verdict.
def render(payload: dict[str, Any]) -> str:
    """Return the study's tables, refusals and verdict as text."""
    lines = [
        f"mid-cycle rule study for {payload['policy']} as of {payload['asof']}: "
        f"{payload['trials']} registered variants, {payload['offsets']} offsets "
        f"(paired statistics at the median offset, Newey-West lag {payload['hac_lag']})"
    ]
    for cost in payload["costs_bps"]:
        for window in payload["windows"]:
            lines.append(f"\n{cost:g} bp, {window}")
            lines.append(
                f"  {'variant':<20}{'CAGR':>8}{'maxDD':>8}{'vs live':>10}{'t':>7}"
                f"{'vs mc-off':>10}{'t':>7}{'>live':>7}"
            )
            rows = [
                r
                for r in payload["rows"]
                if float(r["cost_bps"]) == float(cost) and r["window"] == window
            ]
            for row in rows:
                vl = _pair(payload, row["line"], midcycle_ew.LIVE, window, cost)
                vo = _pair(payload, row["line"], midcycle_ew.MC_OFF, window, cost)
                lines.append(
                    f"  {row['line']:<20}{_pct(row['median_cagr']):>8}"
                    f"{_pct(row['median_drawdown']):>8}"
                    f"{_num(vl.get('mean_daily_bp'), 1):>10}{_num(vl.get('hac_t')):>7}"
                    f"{_num(vo.get('mean_daily_bp'), 1):>10}{_num(vo.get('hac_t')):>7}"
                    f"{row['offsets_above_live']:>7}"
                )
            lines.append(
                f"  {'diagnostics':<20}{'mc turn':>8}{'rb turn':>8}{'cash':>7}"
                f"{'mc cash':>8}"
                f"{'entr/y':>7}{'entry w':>8}{'held@rb':>8}{'exit/y':>7}{'rebought':>9}"
            )
            for row in rows:
                lines.append(
                    f"  {row['line']:<20}{_plain(row.get('midcycle_turnover'), 2):>8}"
                    f"{_plain(row.get('rebalance_turnover'), 2):>8}"
                    f"{_pct(row.get('cash_share')):>7}{_pct(row.get('midcycle_cash_share')):>8}"
                    f"{_plain(row.get('entries_per_year')):>7}{_pct(row.get('entry_weight')):>8}"
                    f"{_pct(row.get('entries_held_at_rebalance')):>8}"
                    f"{_plain(row.get('exits_per_year')):>7}"
                    f"{_pct(row.get('exits_rebought_at_rebalance')):>9}"
                )
            lines.append(
                f"  {'where the cash is':<20}{'cash':>8}{'unpaused':>9}{'idle tgt':>9}"
                f"{'idle@rst':>9}{'post-rst':>9}{'invested':>9}"
            )
            for row in rows:
                cash = row.get("cash_share")
                invested = None if cash is None or cash != cash else 1.0 - cash
                lines.append(
                    f"  {row['line']:<20}{_pct(cash):>8}"
                    f"{_pct(row.get('cash_share_unpaused')):>9}"
                    f"{_pct(row.get('idle_target_share')):>9}"
                    f"{_pct(row.get('idle_target_at_reset')):>9}"
                    f"{_pct(row.get('cash_share_post_reset')):>9}"
                    f"{_pct(invested):>9}"
                )
    if payload.get("refused"):
        lines.append("\nrefused:")
        for name, reason in payload["refused"].items():
            lines.append(f"  {name}: {reason}")
    if payload.get("merged"):
        merged = payload["merged"]
        lines.append(
            f"\nmerged with the earlier payload (as of {merged.get('earlier_asof')}): "
            f"kept {', '.join(merged.get('kept', [])) or 'nothing'}; "
            f"repriced {', '.join(merged.get('repriced', [])) or 'nothing'}"
        )
    verdict = payload["verdict"]
    lines.append(
        f"\n{'exposure reading':<22}{'CAGR pt':>9}{'exp-adj pt':>11}{'invested':>10}"
        f"{'>live':>7}{'later >live':>12}  reading"
    )
    for name, info in verdict.get("variants", {}).items():
        lines.append(
            f"{name:<22}{_num(info.get('choosing_points'), 1):>9}"
            f"{_num(info.get('exposure_adjusted_points'), 1):>11}"
            f"{_pct(info.get('invested_share')):>10}"
            f"{info.get('offsets_above_live', 0)}/{info.get('offsets', 0):<4}"
            f"{info.get('reported_offsets_above_live', 0)}/{info.get('offsets', 0):<9}"
            f"{info.get('reading', '')}"
        )
    lines.append(f"\nverdict: {verdict['text']}")
    return "\n".join(lines)


# Run the desk, restrict, price every variant, write and print.
def run(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    desk_run: Callable[[MarketStore], Any] | None = None,
) -> int:
    """Run the study for the parsed arguments; return the exit code."""
    root = Path(args.root)
    store = MarketStore(root)
    report = (desk_run or default_desk)(store)
    restricted, mask = point_in_time.point_in_time(report, args.membership)
    only = getattr(args, "only", None)
    merge = getattr(args, "merge", None)
    earlier = None
    if merge is not None:
        # Read the earlier payload before the run, so a missing or foreign
        # file refuses in seconds rather than after hours of pricing.
        earlier = json.loads(Path(merge).read_text(encoding="utf-8"))
        if earlier.get("study") != midcycle_ew.STUDY:
            raise SystemExit(f"{merge} is not a {midcycle_ew.STUDY} payload")
    payload = midcycle_ew.run_variants(
        report,
        restricted,
        mask,
        store,
        max(1, args.offsets),
        tuple(float(c) for c in args.costs),
        only=only,
    )
    if earlier is not None:
        payload = midcycle_ew.merge_payload(earlier, payload)
    payload["verdict"] = midcycle_ew.verdict(payload)
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
