"""Score the installed leader rule on the whole S&P 500, point in time.

The desk's book is AI and software by decision, and that decision was made in
2026 knowing how those names did since 2015. A rule scored only on that book
cannot say how much of its record is the theme and how much is its own
selection. This run asks the second question the only way it can be asked
without hindsight: the same grading and the same allocator on every S&P 500
member as of each session, with the index's own dated additions and removals,
and the broad market as the control.

What is held fixed: the analysts, the grading, the expectations-gap model (it
is already fitted on the full universe and projected onto whatever book it is
asked for), the regime analyst (it keeps reading the AI-against-software spread
of the book names, exactly as the live desk does, so the only change is which
names the grades may pick), and the scorecard's costs, offsets and windows.
What changes: the valuation analyst's peer groups become GICS sectors instead
of the two book sides, since a bank's multiple means nothing beside a chip
maker's, and the point-in-time mask becomes the index's membership.

Membership is reconstructed from today's constituent list and the dated change
table: walking the changes back from today gives the list at the window start,
and walking them forward from there gives each name's intervals. A name the
table adds that today's list does not carry, or removes without ever adding,
is kept as the table says; a name with no bars in the store is never held, as
in every scorecard run. A name whose bars end before the window does (a
rename the change table never recorded, like WBD becoming PSKY) leaves the
book two rebalance cycles before its last price, so the simulation is sure to
have sold it on a session it can price (the scorecard's book trades the
allocator's weights on its rebalance sessions, and a held name without a
price stops the simulation rather than being carried at a stale value).

Run with the research venv on the Spark:

    PYTHONPATH=. python -m backend.cli.market_universe_hindsight_research \
        --root /home/animallya96/deploy/anios/data/market \
        --arms ew_graded_leader_forecast_ewma leader_ewma_minB
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import replace

import numpy as np
from datetime import date
from pathlib import Path

from backend.agents.trading.desk import desk, paper, point_in_time, regime
from backend.cli import market_pit_scorecard as scorecard
from backend.market import universe
from backend.market.panel import build_panel

WINDOW_START = date(2015, 1, 1)
CHANGES_PATH = universe.CONSTITUENTS_PATH.with_name("sp500_changes_wikipedia.csv")
OUTPUT_DIR = Path("research") / "universe-hindsight"
MEMBERSHIP_FILE = "sp500_membership_history.csv"
DEFAULT_ARMS = ("ew_graded_leader_forecast_ewma", "leader_ewma_minB")


# The index's dated membership intervals, reconstructed from today's list and
# the change table, as rows the membership reader accepts.
def membership_rows(
    constituents: Path = universe.CONSTITUENTS_PATH,
    changes: Path = CHANGES_PATH,
    ends: dict[str, date] | None = None,
) -> list[dict[str, str]]:
    """Return membership rows since the window start; `ends` closes a name where its bars stop."""
    ends = ends or {}
    today = {m.ticker for m in universe.load_constituents(constituents)}
    events: list[tuple[date, str, bool]] = []
    with changes.open(newline="", encoding="utf-8") as handle:
        for item in csv.DictReader(line for line in handle if not line.startswith("#")):
            when = date.fromisoformat(item["effective"])
            if item["added"].strip():
                events.append((when, item["added"].strip(), True))
            if item["removed"].strip():
                events.append((when, item["removed"].strip(), False))
    events.sort(key=lambda event: event[0])
    # Back from today to the window start: an addition was not a member
    # before its date, a removal was.
    members = set(today)
    for when, ticker, added in reversed(events):
        if when < WINDOW_START:
            break
        if added:
            members.discard(ticker)
        else:
            members.add(ticker)
    source = f"{constituents.name} with {changes.name}"
    rows: list[dict[str, str]] = []
    open_since: dict[str, date] = {ticker: WINDOW_START for ticker in members}

    def close(ticker: str, when: date, rule: str) -> None:
        entered = open_since.pop(ticker)
        if ticker in ends and ends[ticker] < when:
            when, rule = ends[ticker], "S&P 500 member until its bars end in the store"
        if when <= entered:
            return
        rows.append(
            {
                "ticker": ticker,
                "entered": entered.isoformat(),
                "entry_announced": entered.isoformat(),
                "exited": when.isoformat(),
                "exit_announced": when.isoformat(),
                "source": source,
                "rule": rule,
            }
        )

    for when, ticker, added in events:
        if when < WINDOW_START:
            continue
        if added and ticker not in open_since:
            open_since[ticker] = when
        elif not added and ticker in open_since:
            close(ticker, when, "S&P 500 member between the dated effective changes")
    for ticker in sorted(open_since):
        if ticker in ends:
            close(ticker, ends[ticker], "S&P 500 member until its bars end in the store")
    for ticker, entered in sorted(open_since.items()):
        rows.append(
            {
                "ticker": ticker,
                "entered": entered.isoformat(),
                "entry_announced": entered.isoformat(),
                "exited": "",
                "exit_announced": "",
                "source": source,
                "rule": "S&P 500 member from the dated effective change, or at the window start",
            }
        )
    rows.sort(key=lambda row: (row["ticker"], row["entered"]))
    return rows


def write_membership(rows: list[dict[str, str]], path: Path) -> None:
    """Write the membership rows as the history CSV the mask reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


# The session a name must leave the book on when its bars end before the
# panel does: two rebalance cycles and two sessions before its last price, so the
# scorecard's book has sold it on a session with a price.
def bar_ends(panel) -> dict[str, date]:
    """Return {ticker: exit session} for names priced only part way."""
    out: dict[str, date] = {}
    for j, ticker in enumerate(panel.tickers):
        priced = np.flatnonzero(np.isfinite(panel.adj_close[:, j]))
        margin = 2 * paper.REBALANCE_EVERY + 2
        if len(priced) > margin and priced[-1] < len(panel.dates) - 1:
            out[ticker] = panel.dates[priced[-1] - margin].astype("datetime64[D]").astype(object)
    return out


# A session missing from the store inside a name's history (FISV on 2025-11-12
# is the one such hole on this panel) carries the previous session's bar, and so
# does every session after a name's last bar: a held name without a mark stops
# the simulation, and the book keeps a dust remainder of every name it ever
# sold (a sale under the trade floor is skipped, never cleaned up), so a name
# whose bars end is carried flat, at zero return, once the membership has
# taken it out. Nothing before a name's first bar is invented.
def carry_holes(panel):
    """Return the panel with holes and the stretch after the last bar carried forward."""
    fields = {}
    for name in ("open", "high", "low", "close", "adj_close"):
        values = np.array(getattr(panel, name), dtype=float)
        for j in range(values.shape[1]):
            ok = np.isfinite(values[:, j])
            if not ok.any():
                continue
            first = int(np.flatnonzero(ok)[0])
            for t in np.flatnonzero(~ok[first:]) + first:
                values[t, j] = values[t - 1, j]
        fields[name] = values
    return replace(panel, **fields)


# The broad panel: every universe member with bars, peers grouped by sector.
def broad_panel(store, asof=None):
    """Return (panel, sector sides) over the whole universe; `ends` is filled from the raw bars."""
    members = universe.build_universe()
    tickers = universe.tickers_with_role(members, universe.MEMBER, universe.FOCUS)
    themes = {t: g for t, g in universe.theme_map(members).items() if t in tickers}
    sides = {m.ticker: (m.sector or "other") for m in members if m.ticker in tickers}
    panel = build_panel(store, tuple(sorted(tickers)), universe.MARKET_BENCHMARK, themes, asof=asof)
    ends.clear()
    ends.update(bar_ends(panel))
    return carry_holes(panel), sides


# Where each name's bars really end, read before the panel is carried forward.
ends: dict[str, date] = {}


# The desk run with the broad panel in place of the book, the regime still
# reading the book's own sides.
def broad_report(store):
    """Return the desk report graded over the whole universe."""
    book_sides = universe.book_sides(universe.build_universe())
    original_panel, original_opine = desk.book_panel, regime.opine

    def opine(panel, sides, *args, **kwargs):
        return original_opine(panel, book_sides, *args, **kwargs)

    desk.book_panel, regime.opine = broad_panel, opine
    try:
        return scorecard._desk_with_expiry(
            desk, store, dict(inputs=(desk.EXPECTATIONS_GAP,), signed_rotation=False), scorecard._expiry_mode(None)
        )
    finally:
        desk.book_panel, regime.opine = original_panel, original_opine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", default="data/market")
    parser.add_argument("--arms", nargs="+", default=list(DEFAULT_ARMS))
    parser.add_argument("--offsets", type=int, default=20)
    parser.add_argument("--costs", type=float, nargs="+", default=[25.0])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    from backend.market.store import MarketStore

    root = Path(args.root)
    scorecard._RELEASES_ROOT[0] = str(root)
    out = args.output_dir or root / OUTPUT_DIR
    membership = out / MEMBERSHIP_FILE
    store = MarketStore(root)
    report = broad_report(store)
    panel = report.panel
    write_membership(membership_rows(ends=ends), membership)
    print(f"broad panel: {len(panel.tickers) - 1} names, {panel.dates[0]} -> {panel.dates[-1]}")
    # The scorecard's "today's book" line grades every name on the panel as the
    # report does and lets the executor's mid-cycle redeploy buy any name graded
    # in, member or not, including names whose bars end before the window does,
    # which the simulation refuses to carry unpriced. The report handed to the
    # scorecard is therefore already restricted to the dated membership, so both
    # rule lines read the same point-in-time grades.
    restricted, _ = point_in_time.point_in_time(report, membership)
    for arm in args.arms:
        payload = scorecard.build(
            restricted, store, args.offsets, tuple(args.costs), history_path=membership, arm=scorecard.ARMS[arm]
        )
        payload["arm"] = arm
        payload["universe"] = "S&P 500 point in time"
        payload["note"] = __doc__.split("\n\n")[1] + " " + payload["note"]
        target = out / f"{arm}.json"
        target.write_text(json.dumps(payload, indent=2, allow_nan=True), encoding="utf-8")
        print(scorecard.render(payload))
        print(f"\nwrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
