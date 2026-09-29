"""Stage 3's T-S1 overlay: the `/4` book without its worst-forecast decile.

    python -m backend.cli.market_stage3_overlay --forecast research/stage3/s1_lgbm.npz
    python -m backend.cli.market_stage3_overlay --forecast s1_lgbm.npz \
        --root data/market --offsets 20 --costs 10 16 25
    python -m backend.cli.market_stage3_overlay --forecast s1_lgbm.npz \
        --seed-column 3 --costs 25

Runs the desk, restricts the report to the point-in-time book
(`point_in_time.point_in_time` on the dated membership file), places the
S1 forecast (`stage3_io.Stage3Forecast`, kind "s1") on the panel's grid
(`stage3_overlay.align`: row (ticker, t) at the panel's row of t), and
prices `ew-redeploy` (the live executor with the redeploy of idle cash,
`profit_taking.control_options`) against the overlay that drops the
lowest-forecast decile of the book (`stage3_overlay.Overlay`) from every
start offset of the 20-session clock at each cost. Prints a table (line x
window x cost: median CAGR, median worst drawdown, bp a day against the
control and its Newey-West t, offsets above the control, cash and idle
share), what the overlay dropped, and this run's reading of the plan's
criteria (`stage3_verdict.s1_reading`); the ADOPT / RECORD verdict needs
the other candidates' excess and the five single-seed runs
(`stage3_verdict.s1_verdict`). `--seed-column K` prices seed K's column of
the forecast instead of the ensemble (the seed-stability runs; `--costs
25` is enough for them). Writes `--out`, or by default
`<root>/desk/stage3_overlay_<family>[_seed<K>].json`. Nothing here trades
or changes the executor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from backend.agents.trading.desk import point_in_time
from backend.cli.market_profit_taking import default_desk
from backend.market import stage3_io as io
from backend.market import stage3_overlay, universe
from backend.market.session_anatomy import json_ready
from backend.market.store import MarketStore

FILE = "stage3_overlay_{family}{seed}.json"


# The sha256 of a file's bytes, read in chunks.
def _sha256(path: Path) -> str:
    """Return the hex sha256 of the file at `path`."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Build the parser for the T-S1 overlay study."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--forecast", type=Path, required=True, help="the S1 forecast npz (stage3_io)"
    )
    parser.add_argument("--root", default="data/market", help="market store root")
    parser.add_argument(
        "--membership",
        type=Path,
        default=universe.MEMBERSHIP_HISTORY_PATH,
        help="dated membership history CSV for the point-in-time book",
    )
    parser.add_argument(
        "--offsets",
        type=int,
        default=stage3_overlay.OFFSETS,
        help="start offsets on the 20-session clock",
    )
    parser.add_argument(
        "--costs",
        type=float,
        nargs="+",
        default=list(stage3_overlay.COSTS),
        help="one-way costs in basis points; the verdict reads 25, the floor all three",
    )
    parser.add_argument(
        "--seed-column",
        type=int,
        default=None,
        help="price seed K's column of the forecast instead of the ensemble",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="where to write the payload"
    )
    parser.add_argument("--json", action="store_true", help="print the payload as JSON")
    return parser


# A fraction as a percentage string, "n/a" for NaN or None.
def _pct(x: float | None, digits: int = 1) -> str:
    """Return `x` as a percentage, "n/a" when missing."""
    return "n/a" if x is None or x != x else f"{x * 100:.{digits}f}%"


# A signed number, "n/a" for NaN or None.
def _num(x: float | None, digits: int = 2) -> str:
    """Return `x` with its sign, "n/a" when missing."""
    return "n/a" if x is None or x != x else f"{x:+.{digits}f}"


# The paired entry of the overlay for a window at a cost, or {}.
def _pair(payload: dict[str, Any], window: str, cost: float) -> dict[str, Any]:
    """Return the overlay's paired entry on (window, cost), {} when absent."""
    pair: dict[str, Any]
    for pair in payload["paired"]:
        if pair["window"] == window and float(pair["cost_bps"]) == float(cost):
            return pair
    return {}


# The payload as tables people can read, the drops, then this run's reading.
def render(payload: dict[str, Any]) -> str:
    """Return the study's tables and reading as text."""
    forecast = payload["forecast"]
    seed = payload.get("seed_column")
    lines = [
        f"stage-3 T-S1 overlay {payload['candidate']} for {payload['policy']} as of "
        f"{payload['asof']}: {payload['line']} against {payload['control']}, "
        f"{payload['offsets']} offsets (paired statistics at offset "
        f"{payload['median_offset']}, Newey-West lag {payload['hac_lag']}), "
        + ("seed ensemble" if seed is None else f"seed column {seed}"),
        f"forecast {forecast.get('file', 'n/a')} (sha256 "
        f"{str(forecast.get('sha256') or 'n/a')[:12]}): {forecast['placed']} of "
        f"{forecast['rows']} rows on the panel, first forecast "
        f"{forecast['first_forecast_date'] or 'never'}",
    ]
    for cost in payload["costs_bps"]:
        for window in payload["windows"]:
            lines.append(f"\n{cost:g} bp, {window}")
            lines.append(
                f"  {'line':<14}{'CAGR':>8}{'maxDD':>8}{'vs ctl':>9}{'t':>7}{'>ctl':>6}"
                f"{'cash':>7}{'idle':>7}{'mc turn':>8}"
            )
            pair = _pair(payload, window, cost)
            for row in payload["rows"]:
                if float(row["cost_bps"]) != float(cost) or row["window"] != window:
                    continue
                overlay = row["line"] == payload["line"]
                lines.append(
                    f"  {row['line']:<14}{_pct(row['median_cagr']):>8}"
                    f"{_pct(row['median_drawdown']):>8}"
                    f"{_num(pair.get('mean_daily_bp') if overlay else 0.0, 1):>9}"
                    f"{(_num(pair.get('hac_t')) if overlay else ''):>7}"
                    f"{row['offsets_above_control']:>6}{_pct(row.get('cash_share')):>7}"
                    f"{_pct(row.get('idle_target_share')):>7}"
                    f"{_num(row.get('midcycle_turnover'), 2):>8}"
                )
    drops = payload.get("drops") or {}
    if drops:
        resets = drops["resets"]
        held = drops["held_after_reset_drop"]
        lines.append(
            f"\ndrops at the median offset, {payload['verdict_cost_bps']:g} bp: "
            f"{resets['with_drops']} of {resets['sessions']} resets dropped names "
            f"(mean {_num(resets['mean_dropped'], 2)} of "
            f"{_num(resets['mean_candidates'], 1)} candidates); most dropped: "
            + ", ".join(
                f"{t} {n}" for t, n in list(drops["dropped_at_resets"].items())[:10]
            )
        )
        lines.append(
            f"held after a reset's fill in the names it dropped (sells held on a green "
            f"open, breakout entries): mean {_pct(held['mean'], 2)}, max "
            f"{_pct(held['max'], 2)}, on {_pct(held['held_share'])} of "
            f"{held['sessions']} sessions"
        )
    reading = payload["reading"]
    lines.append(
        "\nthis run's reading (the verdict adds the deflated Sharpe and the seeds, "
        "stage3_verdict.s1_verdict):"
    )
    for key, floor in reading["floor"].items():
        lines.append(
            f"  model window at {key} bp: {_num(floor['bp'], 1)} bp/session "
            f"(t {_num(floor['t'])}) - floor "
            + ("cleared" if floor["passes"] else "not cleared")
        )
    lines.append(
        f"  offsets above the control at {reading['cost_bps']:g} bp: "
        f"{reading['offsets_above_control']}/{reading['offsets']} "
        f"({'passes' if reading['passes_offsets'] else 'fails'}); median worst "
        f"drawdown {_num(reading['drawdown_gap_points'], 1)} pt against the control "
        f"({'passes' if reading['passes_drawdown'] else 'fails'}); 2024-2026 "
        f"{_num(reading['reported_bp'], 1)} bp/session "
        f"({'passes' if reading['not_worse_reported'] else 'fails'}); "
        f"exposure-adjusted {_num(reading['exposure_adjusted_points'], 1)} pt"
    )
    return "\n".join(lines)


# The file a run writes: `--out` when given, else one per family and seed
# column under <root>/desk/.
def _target(args: argparse.Namespace, root: Path, family: str) -> Path:
    """Return the payload's destination path."""
    if args.out is not None:
        return Path(args.out)
    seed = "" if args.seed_column is None else f"_seed{int(args.seed_column)}"
    return root / "desk" / FILE.format(family=family, seed=seed)


# Read and check the forecast, run the desk, restrict, align, price both
# lines at every offset and cost, write and print.
def run(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    desk_run: Callable[[MarketStore], Any] | None = None,
) -> int:
    """Run the study for the parsed arguments; return the exit code."""
    root = Path(args.root)
    path = Path(args.forecast)
    if not path.exists():
        print(f"forecast file not found: {path}", file=out)
        return 1
    try:
        forecast = io.load_forecast(path)
        if forecast.kind != io.S1:
            raise ValueError(
                f"{path} holds a {forecast.kind} forecast; the overlay reads S1"
            )
        if forecast.family not in io.FAMILIES[io.S1]:
            raise ValueError(f"{path}: {forecast.family!r} is not an S1 family")
        column = args.seed_column
        seeds = forecast.yhat_seeds
        if column is not None and (seeds.ndim != 2 or not 0 <= column < seeds.shape[1]):
            raise ValueError(
                f"seed column {column} is outside the file's "
                f"{seeds.shape[1] if seeds.ndim == 2 else 0} seed columns"
            )
    except ValueError as error:
        print(str(error), file=out)
        return 2
    identity = {"file": str(path), "sha256": _sha256(path), "meta": forecast.meta}
    store = MarketStore(root)
    report = (desk_run or default_desk)(store)
    restricted, mask = point_in_time.point_in_time(report, args.membership)
    s1 = stage3_overlay.align(forecast, restricted.panel, args.seed_column)
    payload = stage3_overlay.run_overlay(
        restricted,
        mask,
        s1,
        offsets=max(1, args.offsets),
        costs=tuple(float(c) for c in args.costs),
        candidate=f"s1_{forecast.family}",
        identity=identity,
    )
    payload["root"] = str(root)
    payload["membership_history"] = str(args.membership)
    payload = json_ready(payload)
    target = _target(args, root, forecast.family)
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
