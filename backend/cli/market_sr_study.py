"""The support/resistance study: do dips into a level hold, dips into nothing continue?

    python -m backend.cli.market_sr_study --root data/market --workers 8
    python -m backend.cli.market_sr_study --tickers AVGO,NVDA --json

The pre-registration is `docs/research/sr-levels-plan-2026-09-29.md`.

What it does:

1. Runs the desk and restricts the report to the point-in-time book
   (`point_in_time.point_in_time` on the dated membership file).
2. Computes the daily structure once for the panel
   (`sr_levels.daily_levels`).
3. For each name, in a process pool:
   - loads its SIP session cube (`sip_cube.load`, cached under
     `<root>/research/sip_cubes/`);
   - builds the 22 levels in force during every bar;
   - finds its support and resistance touches and control candidates on
     its member sessions (`sr_study.name_events`).
4. Matches every touch to its controls, scores the 640 registered cells and
   reads the primary test (`sr_study.study`).

It prints what each cube excluded, the level coverage, the match rates, the
primary test and the Bonferroni line. Then, for each side, population and
window, one row per group (all touches, each family, each confluence), with
the difference from the controls and its month-clustered t for every
outcome. It writes `<root>/desk/sr_study.json`.

Nothing here trades or changes the board. The decision test is the fill
convention pair priced by `python -m backend.cli.market_fill_timing --only
level_dip,level_dip_confluence`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from backend.agents.trading.desk import point_in_time
from backend.cli.market_fill_timing import default_desk
from backend.cli.market_session_anatomy import DEFAULT_WORKERS
from backend.market import sip_cube, sr_levels, sr_study, universe
from backend.market.store import MarketStore

FILE = "sr_study.json"
# Width of one "difference (t)" cell in the tables.
CELL = 17
# The short outcome headers, in sr_study.OUTCOMES order.
HEADERS = ("to close bp", "bounce pp", "break pp", "next day bp", "5-day bp")

assert len(HEADERS) == len(sr_study.OUTCOMES)


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Build the parser for the support/resistance study."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market", help="market store root")
    parser.add_argument(
        "--tickers",
        default="",
        help="comma-separated book names to study; default: every panel name",
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
        help="processes reading cubes and finding events in parallel (1 = here)",
    )
    parser.add_argument("--json", action="store_true", help="print the payload as JSON")
    return parser


# One name's work in a worker process: its cube from the store at `root`
# (re-opened there, since a MarketStore is not sent across processes), then
# its touches and control candidates. Returns the events and what the cube
# left out.
def _events(job: tuple) -> tuple[sr_study.NameEvents, dict[str, int]]:
    """Return (NameEvents, the cube's exclusion counts) for one job."""
    root, ticker, daily, dates, adj_close, member, grades = job
    cube = sip_cube.load(MarketStore(Path(root)), ticker)
    events = sr_study.name_events(ticker, cube, daily, dates, adj_close, member, grades)
    return events, dict(cube.excluded)


# The names to study: the requested ones that the panel holds, else every
# panel name but the benchmark. Also returns the requested names the panel
# lacks.
def _names(panel, requested: str) -> tuple[list[str], list[str]]:
    """Return (names to study, requested names not in the panel)."""
    book = [t for t in panel.tickers if t != panel.benchmark]
    if not requested.strip():
        return book, []
    wanted = list(
        dict.fromkeys(t.strip().upper() for t in requested.split(",") if t.strip())
    )
    return [t for t in wanted if t in book], [t for t in wanted if t not in book]


# A number with a sign to `digits` decimals, "-" when absent.
def _num(x: float | None, digits: int = 1) -> str:
    """Return the formatted number."""
    return "-" if x is None else f"{x:+.{digits}f}"


# A share as a percentage, "-" when absent.
def _pct(x: float | None) -> str:
    """Return the formatted share."""
    return "-" if x is None else f"{x * 100:.0f}%"


# One table cell: the difference and its t, starred past the Bonferroni line.
def _cell_text(c: dict[str, Any]) -> str:
    """Return "diff (t)" for a cell."""
    star = "*" if c["beyond_bonferroni"] else " "
    return f"{_num(c['diff'])} ({_num(c['t'], 2)}){star}"


# The table of one side, population and window: a row per group.
def _table(
    payload: dict[str, Any], side: str, population: str, window: str
) -> list[str]:
    """Return the table's lines."""
    cells = sr_study.by_key(payload["cells"])
    people = (
        "every member" if population == "members" else "graded A/A+ at the prior close"
    )
    lines = [
        f"\n{side} touches, {people}, {window} "
        "(touch minus matched controls; t month-clustered)",
        f"  {'group':<16}{'touches':>9}{'dates':>7}"
        + "".join(f"{h:>{CELL}}" for h in HEADERS),
    ]
    for group in sr_study.GROUPS:
        first = cells[(side, population, window, group, sr_study.OUTCOMES[0])]
        row = f"  {group:<16}{first['touches']:>9}{first['dates']:>7}"
        for outcome in sr_study.OUTCOMES:
            text = _cell_text(cells[(side, population, window, group, outcome)])
            row += f"{text:>{CELL}}"
        lines.append(row)
    return lines


# The payload as text: coverage, the official close, the match rates, the
# touch counts, the primary test, the Bonferroni line, then every table.
def render(payload: dict[str, Any]) -> str:
    """Return the study as readable text."""
    close = payload["official_close"]
    lines = [
        f"support/resistance study v{payload['version']} ({payload['plan']})",
        f"names {payload['names']}, member sessions {payload['member_sessions']:,}; "
        f"the official close is the auction print on {close['auction']:,} and the "
        f"last bar on {close['last_bar']:,}",
        "levels in force at 10:00-10:15 (share of member sessions): "
        + ", ".join(f"{k} {_pct(v)}" for k, v in payload["coverage"].items()),
    ]
    for side in sr_study.SIDES:
        for window, m in payload["match"][side].items():
            lines.append(
                f"match, {side} {window}: {m['touches']:,} touches; own name "
                f"{_pct(m['own_name_rate'])}, pooled {_pct(m['pooled_rate'])}, "
                f"unmatched {_pct(m['unmatched_rate'])}; median controls "
                f"{m['median_controls'] if m['median_controls'] is not None else '-'}"
            )
        for window, t in payload["touches"][side].items():
            lines.append(
                f"touches, {side} {window}: "
                + ", ".join(f"{k} {v:,}" for k, v in t["families"].items())
                + "; "
                + ", ".join(f"{k} {v:,}" for k, v in t["confluence"].items())
            )
    first = payload["primary"]
    choose, later = first["choosing"], first["reported"]
    lines.append(
        "\nprimary (support, every member, all touches, return to the close): "
        f"{sr_study.CHOOSING} {_num(choose.get('diff'))} bp "
        f"(t {_num(choose.get('t'), 2)}, {choose.get('touches', 0):,} touches on "
        f"{choose.get('dates', 0):,} dates); {sr_study.REPORTED} "
        f"{_num(later.get('diff'))} bp (t {_num(later.get('t'), 2)}) -> "
        f"{first['verdict']} (needs > 0 with t >= {first['threshold_t']:g}, "
        "then > 0)"
    )
    lines.append(
        f"Bonferroni: {payload['trials']} cells, family-wise "
        f"{payload['family_alpha']:g}, |t| >= {payload['bonferroni_t']:.2f}; "
        f"beyond it: {len(payload['bonferroni_survivors'])}"
    )
    lines.extend(f"  {s}" for s in sr_study.survivors_text(payload))
    for side in sr_study.SIDES:
        for population in sr_study.POPULATIONS:
            for window in sr_study.WINDOWS:
                lines.extend(_table(payload, side, population, window))
    lines.append(
        "\n(each cell: the mean over dates of the daily average of touch minus "
        "control, bp or points, and its t clustered by calendar month over every "
        "touch and control bar; * beyond the Bonferroni line)"
    )
    return "\n".join(lines)


# Run the desk, restrict, find every name's events, study, write and print.
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
    panel = restricted.panel
    names, missing = _names(panel, args.tickers)
    daily = sr_levels.daily_levels(panel)
    grades = restricted.graded.grades
    jobs = []
    for ticker in names:
        j = panel.index(ticker)
        jobs.append(
            (
                str(root),
                ticker,
                sr_study.column(daily, j),
                np.asarray(panel.dates, dtype="datetime64[D]"),
                panel.adj_close[:, j],
                mask[:, j],
                grades[:, j],
            )
        )
    workers = max(1, int(args.workers))
    if workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_events, jobs))
    else:
        results = [_events(job) for job in jobs]
    events = [e for e, _ in results]
    if not args.json:
        print(f"events from {root} ({len(names)} names):", file=out)
        for ticker in missing:
            print(f"  {ticker:<6} not a book name in the panel; skipped", file=out)
        for e, excluded in results:
            touches = {s: len(e.sides[s].touch_date) for s in sr_study.SIDES}
            print(
                f"  {e.ticker:<6} {e.sessions:>5} sessions, {e.member_sessions:>5} "
                f"as a member; touches {touches['support']:,} / "
                f"{touches['resistance']:,}; excluded: "
                + ", ".join(f"{k} {v}" for k, v in excluded.items()),
                file=out,
            )
    if not any(e.member_sessions for e in events):
        print("no member sessions with a cube; nothing to study", file=out)
        return 1
    payload = sr_study.study(events)
    payload["root"] = str(root)
    payload["membership_history"] = str(args.membership)
    payload["exclusions"] = {e.ticker: excluded for e, excluded in results}
    payload["asof"] = str(panel.dates[-1])
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
