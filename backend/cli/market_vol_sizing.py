"""Volatility sizing on the `/4` book: the CNN forecast against trailing volatility, priced.

    python -m backend.cli.market_vol_sizing --root data/market --forecasts vol_forecasts.npz
    python -m backend.cli.market_vol_sizing --forecasts vol_forecasts.npz --offsets 20 --costs 10 25 --json

Runs the desk, restricts the report to the point-in-time book
(`point_in_time.point_in_time` on the dated membership file), aligns the
forecast file written by `market_vol_forecast` to the panel (a row dated t
is read at decision t and applies to session t + 1; no lookahead) and
prices every variant in `vol_sizing.VARIANTS` - the control, inverse
volatility, the volatility target and the hybrid, each fed the CNN
forecast and fed the trailing baseline - under plain next-open fills AND
under the live execution policy, from every start offset of the 20-session
clock at each cost. Prints one table per option set (variant x window:
median CAGR, median worst drawdown, CAGR / |maxDD|, median exposure,
fallback share, bp a day against the control and its Newey-West t,
offsets above the control), the volatility target measured from the
control before the run, and the verdict (ADOPT (registered), RECORD, or
RECORD labelled inverse vol, under the floors `vol_sizing` fixes; the
verdict reads live at 25 bp). Writes `<root>/desk/vol_sizing.json`.
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
from backend.market import universe, vol_forecast, vol_sizing
from backend.market.session_anatomy import json_ready
from backend.market.store import MarketStore

FILE = "vol_sizing.json"


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Build the parser for the volatility-sizing trial."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market", help="market store root")
    parser.add_argument(
        "--membership",
        type=Path,
        default=universe.MEMBERSHIP_HISTORY_PATH,
        help="dated membership history CSV for the point-in-time book",
    )
    parser.add_argument(
        "--forecasts",
        type=Path,
        required=True,
        help="forecast npz written by market_vol_forecast",
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


# The paired entry for a line against the control under an option set in a
# window at a cost, or {}.
def _pair(
    payload: dict[str, Any], line: str, option_set: str, window: str, cost: float
) -> dict:
    for p in payload["paired"]:
        if (
            p["line"] == line
            and p["against"] == vol_sizing.CONTROL
            and p["options"] == option_set
            and p["window"] == window
            and float(p["cost_bps"]) == float(cost)
        ):
            return p
    return {}


# The payload as tables people can read, one per option set, then the verdict.
def render(payload: dict[str, Any]) -> str:
    """Return the trial's tables and verdict as text."""
    target = payload["vol_target"]
    coverage = payload["forecast_coverage"]
    lines = [
        f"volatility sizing for {payload['policy']} as of {payload['asof']}: "
        f"{payload['trials']} registered variants and the control, {payload['offsets']} "
        f"offsets (paired statistics at the median offset, Newey-West lag "
        f"{payload['hac_lag']})",
        f"volatility target {_plain(target['target'], 4)} per session from the control's "
        f"{target['source']} volatility on {target['window']} ({target['sessions']} "
        f"sessions); forecast covers {_pct(coverage['held_cells'], 0)} of held cells, "
        f"first {coverage['first_session_with_forecast'] or 'never'}",
    ]
    for option_set in payload["option_sets"]:
        for cost in payload["costs_bps"]:
            for window in payload["windows"]:
                lines.append(f"\n{option_set} options, {cost:g} bp, {window}")
                lines.append(
                    f"  {'variant':<22}{'CAGR':>8}{'maxDD':>8}{'ratio':>7}{'expo':>6}"
                    f"{'fallbk':>7}{'vs ew':>8}{'t':>7}{'>ew':>5}"
                )
                for row in payload["rows"]:
                    if (
                        row["options"] != option_set
                        or float(row["cost_bps"]) != float(cost)
                        or row["window"] != window
                    ):
                        continue
                    vp = _pair(payload, row["line"], option_set, window, cost)
                    lines.append(
                        f"  {row['line']:<22}{_pct(row['median_cagr']):>8}"
                        f"{_pct(row['median_drawdown']):>8}{_plain(row['ratio']):>7}"
                        f"{_plain(row['median_exposure']):>6}"
                        f"{_pct(row['fallback_share'], 0):>7}"
                        f"{_num(vp.get('mean_daily_bp'), 1):>8}{_num(vp.get('hac_t')):>7}"
                        f"{row['offsets_above_control']:>5}"
                    )
    if payload.get("refused"):
        lines.append("\nrefused: " + "; ".join(f"{k}: {v}" for k, v in payload["refused"].items()))
    lines.append(f"\nverdict: {payload['verdict']['text']}")
    return "\n".join(lines)


# Run the desk, restrict, align the forecasts, price every variant, write
# and print.
def run(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    desk_run: Callable[[MarketStore], Any] | None = None,
) -> int:
    """Run the trial for the parsed arguments; return the exit code."""
    root = Path(args.root)
    if not args.forecasts.exists():
        print(f"forecast file not found: {args.forecasts}", file=out)
        return 1
    store = MarketStore(root)
    report = (desk_run or default_desk)(store)
    restricted, mask = point_in_time.point_in_time(report, args.membership)
    aligned = vol_forecast.aligned_to_panel(args.forecasts, restricted.panel)
    payload = vol_sizing.run_variants(
        report,
        restricted,
        mask,
        store,
        max(1, args.offsets),
        tuple(float(c) for c in args.costs),
        aligned,
    )
    payload["verdict"] = vol_sizing.verdict(payload)
    payload["root"] = str(root)
    payload["membership_history"] = str(args.membership)
    payload["forecast_file"] = str(args.forecasts)
    payload["forecast_meta"] = vol_forecast.load_forecasts(args.forecasts).meta
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
