"""Session anatomy: how the 26 fifteen-minute bars build the daily bar.

    python -m backend.cli.market_session_anatomy --root data/market
    python -m backend.cli.market_session_anatomy --tickers AVGO,SPY --json

Loads one session cube per ticker from the raw-basis SIP store
(`sip_cube.load`, cached under `<root>/research/sip_cubes/`), printing
what each cube excluded (early closes, incomplete partitions, sessions
with no prior daily close), builds the point-in-time membership mask
from the dated history over the union of cube dates, runs
`session_anatomy.study` and writes `<root>/desk/session_anatomy.json`.
The default tickers are the book plus SPY, QQQ, SMH and IGV
(`market_intraday_sip.select_tickers`); the four benchmarks are reported
on their own and never pooled with the book.

The hypotheses are in `backend/market/session_anatomy.py`, written before
the first run. The choosing window is 2016-2023; 2024-2026 is reported,
never tuned on. Nothing here trades.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from backend.agents.trading.desk import point_in_time
from backend.cli.market_intraday_sip import select_tickers
from backend.market import session_anatomy, sip_cube, universe
from backend.market.sip_cube import SessionCube
from backend.market.store import MarketStore

FILE = "session_anatomy.json"
# Rendered slots for the extreme-slot shares: the first two and last two.
EDGE_SLOTS = session_anatomy.EDGE_SLOTS
# Width of one (difference, t, n) cell in the dip and extension tables.
CELL_WIDTH = 30


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Build the parser for the session-anatomy study."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market", help="market store root")
    parser.add_argument(
        "--tickers",
        default="",
        help="comma-separated; default: the book plus the benchmarks",
    )
    parser.add_argument(
        "--membership",
        type=Path,
        default=universe.MEMBERSHIP_HISTORY_PATH,
        help="dated membership history CSV for the point-in-time mask",
    )
    parser.add_argument("--json", action="store_true", help="print the payload as JSON")
    return parser


# Load every ticker's cube, reporting exclusions and names with no
# sessions at all. Returns (cubes with at least one session, lines).
def load_cubes(
    store: MarketStore, tickers: tuple[str, ...]
) -> tuple[dict[str, SessionCube], list[str]]:
    """Return {ticker: cube} for the tickers the store holds, and the log lines."""
    cubes: dict[str, SessionCube] = {}
    lines: list[str] = []
    for ticker in tickers:
        cube = sip_cube.load(store, ticker)
        excluded = ", ".join(f"{k} {v}" for k, v in cube.excluded.items())
        if len(cube) == 0:
            lines.append(f"  {ticker:<6} no complete sessions ({excluded})")
            continue
        cubes[ticker] = cube
        lines.append(
            f"  {ticker:<6} {len(cube):>5} sessions {cube.dates[0]}..{cube.dates[-1]}"
            f"  excluded: {excluded}"
        )
    return cubes, lines


# The membership mask over the union of the cubes' dates, as
# {ticker: member dates}; benchmarks are ignored by the study anyway.
def membership_mask(
    cubes: dict[str, SessionCube], history_path: Path
) -> dict[str, np.ndarray]:
    """Return {ticker: datetime64[D] array of member sessions}."""
    if not cubes:
        return {}
    dates = np.unique(np.concatenate([c.dates for c in cubes.values()]))
    tickers = tuple(cubes)
    eligible = point_in_time.eligibility(dates, tickers, history_path=history_path)
    return {t: dates[eligible[:, j]] for j, t in enumerate(tickers)}


# A number in basis points, or a dash.
def _bp(value: float | None) -> str:
    return f"{value * session_anatomy.BP:+.1f}" if value is not None else "-"


# A dispersion in basis points (no sign), or a dash.
def _bp_sd(value: float | None) -> str:
    return f"{value * session_anatomy.BP:.1f}" if value is not None else "-"


# A t-statistic, or a dash.
def _t(value: float | None) -> str:
    return f"{value:+.2f}" if value is not None else "-"


# A share as a percentage, or a dash.
def _pct(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else "-"


# The lines for one analysis block (a window of the book or a benchmark).
def _render_block(block: dict[str, Any]) -> list[str]:
    lines = [
        f"    names {block['names']}  sessions {block['sessions']}"
        f"  dates {block['dates']}  gap mean {_bp(block['gap']['mean'])} bp"
        f"  open-to-close mean {_bp(block['session_return']['mean'])} bp"
        f" sd {_bp_sd(block['session_return']['std'])} bp"
    ]
    shares = block["variance_shares"]
    lines.append(
        "    A. variance share by slot (%): "
        + " ".join(f"{s * 100:.1f}" if s is not None else "-" for s in shares)
    )
    high, low = block["high_slot_shares"], block["low_slot_shares"]
    lines.append(
        "    A. session high set in slot "
        + "  ".join(f"{k}: {_pct(high[k])}" for k in EDGE_SLOTS)
        + f"   (uniform {100 / len(high):.1f}%)"
    )
    lines.append(
        "    A. session low  set in slot "
        + "  ".join(f"{k}: {_pct(low[k])}" for k in EDGE_SLOTS)
    )
    drive = block["open_drive"]
    slope = f"{drive['slope']:+.3f}" if drive["slope"] is not None else "-"
    lines.append(
        f"    B. open drive: slope of r_rest on r1 {slope}  t {_t(drive['t'])}"
        f" (daily averages, HAC lag {session_anatomy.HAC_LAG},"
        f" {drive['dates']} dates)"
    )
    lines.append(
        f"       {'quintile of r1':<16}{'n':>7}{'mean r1 bp':>12}"
        f"{'mean r_rest bp':>16}{'t':>8}"
    )
    for q in drive["quintiles"]:
        lines.append(
            f"       {q['bin'] + 1:<16}{q['n']:>7}{_bp(q['mean_x']):>12}"
            f"{_bp(q['mean_y']):>16}{_t(q['t']):>8}"
        )
    for title, key in (
        ("C. dips (drawdown from open <= threshold)", "dips"),
        ("C. extensions (run-up from open >= threshold)", "extensions"),
    ):
        lines.append(f"    {title}: forward return to the close minus unconditional")
        lines.append(
            f"       {'threshold':>10}"
            + "".join(
                f"{'slot ' + str(k) + ' (diff bp, t, n)':>{CELL_WIDTH}}"
                for k in session_anatomy.CHECK_SLOTS
            )
        )
        by_threshold: dict[float, dict[int, dict[str, Any]]] = {}
        for cell in block[key]:
            by_threshold.setdefault(cell["threshold"], {})[cell["slot"]] = cell
        for threshold, cells in by_threshold.items():
            row = f"       {threshold * 100:>+9.0f}%"
            for k in session_anatomy.CHECK_SLOTS:
                cell = cells.get(k)
                text = (
                    "-"
                    if cell is None
                    else f"{_bp(cell['difference'])}  {_t(cell['t'])}  {cell['n']}"
                )
                row += f"{text:>{CELL_WIDTH}}"
            lines.append(row)
    costs = block["fill_costs"]
    lines.append(
        "    D. fill cost against the open"
        " (bp; VWAP proxy: bar closes weighted by bar volume)"
    )
    lines.append(f"       {'window':<18}{'mean':>9}{'median':>9}{'sd':>9}{'n':>8}")
    for name, label in (
        ("first_hour_vwap", "first-hour VWAP"),
        ("session_vwap", "session VWAP"),
        ("close", "close"),
    ):
        m = costs[name]
        lines.append(
            f"       {label:<18}{_bp(m['mean']):>9}{_bp(m['median']):>9}"
            f"{_bp_sd(m['std']):>9}{m['n']:>8}"
        )
    return lines


# The payload as readable text.
def render(payload: dict[str, Any]) -> str:
    """Return the study as text: the book per window, then each benchmark."""
    lines = [
        f"session anatomy (study v{payload['version']};"
        f" choosing window {payload['choosing_window']};"
        f" {len(payload['book_tickers'])} book names,"
        f" {len(payload['benchmark_tickers'])} benchmarks)"
    ]
    for window, block in payload["book"].items():
        lines.append(f"  book, {window}")
        lines.extend(_render_block(block))
    for ticker, windows in payload["benchmarks"].items():
        for window, block in windows.items():
            lines.append(f"  benchmark {ticker}, {window}")
            lines.extend(_render_block(block))
    return "\n".join(lines)


# Load, mask, study, write, print.
def run(args: argparse.Namespace, out: TextIO = sys.stdout) -> int:
    """Run the study for the parsed arguments; return the exit code."""
    root = Path(args.root)
    store = MarketStore(root)
    tickers = select_tickers(args.tickers)
    cubes, lines = load_cubes(store, tickers)
    if not args.json:
        print(f"cubes from {root} ({len(tickers)} tickers requested):", file=out)
        for line in lines:
            print(line, file=out)
    if not cubes:
        print("no complete sessions in the store; nothing to study", file=out)
        return 1
    mask = membership_mask(cubes, args.membership)
    payload = session_anatomy.study(cubes, mask)
    payload["root"] = str(root)
    payload["membership_history"] = str(args.membership)
    payload["exclusions"] = {t: c.excluded for t, c in cubes.items()}
    payload["sessions_per_ticker"] = {t: len(c) for t, c in cubes.items()}
    payload["asof"] = str(max(c.dates[-1] for c in cubes.values()))
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
