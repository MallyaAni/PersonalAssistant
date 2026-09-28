"""Profit-taking and dip-buying rules on the `/4` book, priced under the live executor.

    python -m backend.cli.market_profit_taking --root data/market
    python -m backend.cli.market_profit_taking --offsets 20 --costs 10 25 --json
    python -m backend.cli.market_profit_taking --root data/market \
        --drawdown-forecasts research/drawdown_forecasts.npz

Runs the desk, restricts the report to the point-in-time book
(`point_in_time.point_in_time` on the dated membership file) and prices
`policy_v4.allocator(mask)` under the live executor with the redeploy of
idle cash (the control, "ew-redeploy") and under each rule in
`profit_taking.VARIANTS` - the run-up trim, the RSI trim, the band trim,
the dip add, and with `--drawdown-forecasts` the two trims on the stage-2
CNN's 20-session drawdown forecast - from every start offset of the
20-session clock at each cost. Prints a table (variant x window: median
CAGR, median worst drawdown, bp a day against the control and its
Newey-West t, offsets above the control, cash share), the trim statistics
(trims and adds a year, mean trim size, the "sold too early" share, the
median 20-session return after a trim and what the sold slice would have
earned), the exposure reading and the verdict under the floors
`profit_taking` fixes. Without the forecast file the two model-based rules
are skipped and the output says so. Writes `<root>/desk/profit_taking.json`.
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
from backend.market import drawdown_forecast, profit_taking, universe
from backend.market.session_anatomy import json_ready
from backend.market.store import MarketStore

FILE = "profit_taking.json"
TOP_TRIMS = 20


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Build the parser for the profit-taking study."""
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
        "--drawdown-forecasts",
        type=Path,
        default=None,
        help=(
            "npz of the CNN's OOS drawdown20 forecast per (ticker, date), written by "
            "market_deep_stage2 --export-forecasts; without it the model rules "
            "are skipped"
        ),
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
def _plain(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None or x != x else f"{x:.{digits}f}"


# The paired entry for a line against the control in a window at a cost, or {}.
def _pair(payload: dict[str, Any], line: str, window: str, cost: float) -> dict:
    for p in payload["paired"]:
        if (
            p["line"] == line
            and p["against"] == profit_taking.CONTROL
            and p["window"] == window
            and float(p["cost_bps"]) == float(cost)
        ):
            return p
    return {}


# The payload as tables people can read - results, trims - then the verdict.
def render(payload: dict[str, Any]) -> str:  # noqa: C901 - one table per block
    """Return the study's tables, skips, largest trims and verdict as text."""
    lines = [
        f"profit-taking study for {payload['policy']} as of {payload['asof']}: "
        f"{payload['trials']} registered variants ({len(payload['ran'])} priced), "
        f"{payload['offsets']} offsets, control {payload['control']} "
        f"(paired statistics at the median offset, Newey-West lag {payload['hac_lag']})"
    ]
    for cost in payload["costs_bps"]:
        for window in payload["windows"]:
            lines.append(f"\n{cost:g} bp, {window}")
            lines.append(
                f"  {'variant':<24}{'CAGR':>8}{'maxDD':>8}{'vs ctl':>9}{'t':>7}"
                f"{'>ctl':>6}{'cash':>7}{'mc turn':>8}"
            )
            rows = [
                r
                for r in payload["rows"]
                if float(r["cost_bps"]) == float(cost) and r["window"] == window
            ]
            for row in rows:
                pair = _pair(payload, row["line"], window, cost)
                lines.append(
                    f"  {row['line']:<24}{_pct(row['median_cagr']):>8}"
                    f"{_pct(row['median_drawdown']):>8}"
                    f"{_num(pair.get('mean_daily_bp'), 1):>9}"
                    f"{_num(pair.get('hac_t')):>7}"
                    f"{row['offsets_above_control']:>6}{_pct(row.get('cash_share')):>7}"
                    f"{_plain(row.get('midcycle_turnover'), 2):>8}"
                )
            lines.append(
                f"  {'trims':<24}{'trims/y':>8}{'adds/y':>8}{'size':>7}{'early':>7}"
                f"{'fwd20':>8}{'fwd bp':>8}{'stops/y':>8}{'n':>6}"
            )
            for row in rows:
                if row["line"] == payload["control"]:
                    continue
                lines.append(
                    f"  {row['line']:<24}{_plain(row.get('trims_per_year')):>8}"
                    f"{_plain(row.get('adds_per_year')):>8}"
                    f"{_pct(row.get('mean_trim_size')):>7}"
                    f"{_pct(row.get('too_early_rate'), 0):>7}"
                    f"{_pct(row.get('median_forward_after_trim')):>8}"
                    f"{_num(row.get('trim_forward_bp'), 1):>8}"
                    f"{_plain(row.get('stops_per_year')):>8}"
                    f"{_plain(row.get('trims_total'), 0):>6}"
                )
    if payload.get("skipped"):
        lines.append("\nskipped:")
        for name, reason in payload["skipped"].items():
            lines.append(f"  {name}: {reason}")
    verdict = payload["verdict"]
    lines.append(
        f"\n{'exposure reading':<24}{'CAGR pt':>9}{'exp-adj pt':>11}{'invested':>10}"
        f"{'>ctl':>7}{'later >ctl':>11}  reading"
    )
    for name, info in verdict.get("variants", {}).items():
        lines.append(
            f"{name:<24}{_num(info.get('choosing_points'), 1):>9}"
            f"{_num(info.get('exposure_adjusted_points'), 1):>11}"
            f"{_pct(info.get('invested_share')):>10}"
            f"{info.get('offsets_above_control', 0)}/{info.get('offsets', 0):<4}"
            f"{info.get('reported_offsets_above_control', 0)}/"
            f"{info.get('offsets', 0):<8}"
            f"{info.get('reading', '')}"
        )
    largest = sorted(
        (
            dict(tr, line=name)
            for name, trims in payload.get("trims", {}).items()
            for tr in trims
            if tr["kind"] in (profit_taking.TRIM, profit_taking.STOP)
        ),
        key=lambda tr: -abs(tr["size"]),
    )[:TOP_TRIMS]
    if largest:
        lines.append(
            f"\nlargest trims at the median offset "
            f"({payload['forward_sessions']}-session forward return of the name "
            "after the trim)"
        )
        lines.append(
            f"  {'variant':<24}{'name':<8}{'date':<12}{'kind':<6}{'before':>8}"
            f"{'after':>8}{'fwd':>8}"
        )
        for tr in largest:
            lines.append(
                f"  {tr['line']:<24}{tr['ticker']:<8}{tr['date']:<12}{tr['kind']:<6}"
                f"{_pct(tr['weight_before']):>8}{_pct(tr['weight_after']):>8}"
                f"{_pct(tr.get('forward')):>8}"
            )
    lines.append(f"\nverdict: {verdict['text']}")
    return "\n".join(lines)


# Run the desk, restrict, align the forecast when given, price every
# variant, write and print.
def run(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    desk_run: Callable[[MarketStore], Any] | None = None,
) -> int:
    """Run the study for the parsed arguments; return the exit code."""
    root = Path(args.root)
    store = MarketStore(root)
    forecasts = getattr(args, "drawdown_forecasts", None)
    if forecasts is not None and not Path(forecasts).exists():
        print(f"drawdown forecast file not found: {forecasts}", file=out)
        return 1
    report = (desk_run or default_desk)(store)
    restricted, mask = point_in_time.point_in_time(report, args.membership)
    forecast = None
    meta = None
    if forecasts is not None:
        loaded = drawdown_forecast.load_forecasts(Path(forecasts))
        forecast = drawdown_forecast.align(
            loaded, restricted.panel.dates, tuple(restricted.panel.tickers)
        )
        meta = loaded.meta
    payload = profit_taking.run_variants(
        report,
        restricted,
        mask,
        store,
        max(1, args.offsets),
        tuple(float(c) for c in args.costs),
        forecast=forecast,
    )
    payload["verdict"] = profit_taking.verdict(payload)
    payload["root"] = str(root)
    payload["membership_history"] = str(args.membership)
    payload["forecast_file"] = str(forecasts) if forecasts is not None else None
    payload["forecast_meta"] = meta
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
