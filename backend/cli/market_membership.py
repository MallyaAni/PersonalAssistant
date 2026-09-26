"""Build the book's point-in-time membership file from dated public sources.

    python -m backend.cli.market_membership            # write the file
    python -m backend.cli.market_membership --check    # rebuild and diff

Every backtest in this repository so far graded 2016-2026 on the book as it
stands today: this year's S&P 500 constituents in the book's sub-industries
plus a hand-written overlay that includes 2024-25 listings and this year's
winners. `market_survivorship` measured that choice at about 19 CAGR points
a year, so no comparison between learners on that book is readable.
`universe.as_of` has always refused to answer without a dated history
(`membership.load_history`); this command writes that history.

Two dated sources, each conservative:

* **Index membership.** The committed constituent file (a dated snapshot of
  the S&P 500) walked backward through the published component changes
  (`data/sp500_changes_wikipedia.csv`, effective dates). A name is a book
  member while it is in the index AND in one of `BOOK_SUB_INDUSTRIES`. The
  sub-industry of a current member comes from the constituent file; a name
  that left the index carries the sub-industry it had when it left, from
  the curated table below, and an exit not in that table is not a book
  member (it is listed by the `--check` report so the omission is visible).
  The announcement date is set equal to the effective date. S&P announces
  changes a few sessions earlier, so this makes a new member eligible a
  few sessions late, never early.
* **The overlay.** A name the operator listed by hand becomes eligible on
  the date the line was committed to `universe.py`. That is the whole
  truth about when the desk knew it wanted the name; every one of the 68
  overlay lines was written in September 2026, so over 2016-2025 the book
  is the index rule alone. That is the point.

Sessions before `WINDOW_START` are not covered: a name in the index on that
date is recorded as entering then, with the rule saying so.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from backend.market import membership, universe

DATA = Path(universe.__file__).parent / "data"
CHANGES_PATH = DATA / "sp500_changes_wikipedia.csv"
OUTPUT_PATH = universe.MEMBERSHIP_HISTORY_PATH
# The first session the desk's panels cover; nothing earlier is dated.
WINDOW_START = date(2016, 1, 4)
# The constituent file's own date, from its header comment.
CONSTITUENTS_ASOF = date(2026, 9, 5)
CHANGES_SOURCE = (
    "https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500 "
    "(read 2026-09-26)"
)
CONSTITUENTS_SOURCE = (
    "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies (2026-09-05)"
)

# Names that left the index during the window while in a book sub-industry,
# with the GICS sub-industry they carried at exit. Keyed by (ticker, exit
# date) because a ticker can be reused by an unrelated company (Q was
# QuintilesIMS in 2017 and Qnity in 2025). Exits in the change table that
# are not listed here are treated as non-book and reported by --check.
EXITED_BOOK_SUB_INDUSTRY: dict[tuple[str, date], str] = {
    ("BRCM", date(2016, 2, 1)): "Semiconductors",
    ("FSLR", date(2017, 3, 20)): "Semiconductors",
    ("LLTC", date(2017, 3, 13)): "Semiconductors",
    ("CA", date(2018, 11, 6)): "Systems Software",
    ("RHT", date(2019, 7, 15)): "Systems Software",
    ("MXIM", date(2021, 8, 30)): "Semiconductors",
    ("XLNX", date(2022, 2, 15)): "Semiconductors",
    ("CTXS", date(2022, 10, 3)): "Application Software",
    ("SEDG", date(2023, 12, 18)): "Semiconductor Materials & Equipment",
    ("CDAY", date(2024, 2, 1)): "Application Software",
    ("QRVO", date(2024, 12, 23)): "Semiconductors",
    ("JNPR", date(2025, 7, 9)): "Communications Equipment",
    ("ANSS", date(2025, 7, 18)): "Application Software",
    ("ENPH", date(2025, 9, 22)): "Semiconductor Materials & Equipment",
    ("DAY", date(2026, 2, 9)): "Application Software",
    ("PAYC", date(2026, 3, 23)): "Application Software",
}

# When each overlay line was committed to universe.py: `git log -S` for the
# UniverseMember line, oldest commit. Frozen here so the file rebuilds
# without git; re-run the git query when a line is added.
OVERLAY_ADDED: dict[str, tuple[date, str]] = {
    **{
        t: (date(2026, 9, 4), "b38c64e2")
        for t in (
            "CRWV", "IREN", "SNDK", "MSFT", "ORCL", "NVDA", "AMD", "AVGO", "SMCI",
            "DELL", "MU", "WDC", "STX", "ANET", "CSCO", "VRT", "ETN", "NOW", "CRM",
            "ADBE",
        )
    },
    **{
        t: (date(2026, 9, 4), "1e4970de")
        for t in (
            "AMZN", "GOOGL", "META", "MRVL", "HPE", "NBIS", "APLD", "CIFR", "WULF",
            "CORZ", "HUT", "GLXY", "ARM", "TSM", "ASML", "ALAB", "CRDO", "NTAP",
            "SIMO", "CIEN", "COHR", "LITE", "FN", "AAOI", "GEV", "CEG", "VST", "TLN",
            "OKLO", "SMR", "BE", "POWL", "MOD", "SNOW", "DDOG", "MDB", "NET", "CRWD",
            "PLTR", "INTU", "WDAY", "TEAM", "ZS", "PANW",
        )
    },
    "AAPL": (date(2026, 9, 6), "0e251bc3"),
    "IBM": (date(2026, 9, 6), "0e251bc3"),
    "ACN": (date(2026, 9, 6), "0e251bc3"),
    "GLW": (date(2026, 9, 19), "4b322ea8"),
}


@dataclass(frozen=True)
class Change:
    """One published index change: who came in and who went out on a date."""

    effective: date
    added: str
    removed: str


# Read the published change table; blank fields mean no name on that side.
def load_changes(path: Path = CHANGES_PATH) -> list[Change]:
    """Return the changes, newest first as the table lists them."""
    out: list[Change] = []
    with path.open(encoding="utf-8") as handle:
        rows = [line for line in handle if not line.startswith("#")]
    for item in csv.DictReader(rows):
        out.append(
            Change(
                date.fromisoformat(item["effective"]),
                item["added"].strip(),
                item["removed"].strip(),
            )
        )
    return out


# Index membership intervals per ticker over the window, reconstructed by
# walking the change table backward from the constituent snapshot and then
# forward from the window start. Returns {ticker: [(entered, exited|None)]}.
def index_intervals(
    current: frozenset[str], changes: list[Change], snapshot: date, start: date
) -> tuple[dict[str, list[tuple[date, date | None]]], list[str]]:
    """Return (intervals by ticker, notes about inconsistent rows)."""
    notes: list[str] = []
    ordered = sorted(changes, key=lambda c: c.effective)
    # The snapshot already reflects every change up to its date and none
    # after it, so walk backward from it to the window start.
    members = set(current)
    for c in reversed([c for c in ordered if start < c.effective <= snapshot]):
        if c.added:
            if c.added not in members:
                notes.append(f"{c.effective}: {c.added} added but not a member later")
            members.discard(c.added)
        if c.removed:
            members.add(c.removed)
    at_start = frozenset(members)
    # Forward: open an interval at the start for every member, then apply
    # each change on its effective date (removals before additions on the
    # same date, so a same-day rename keeps the name continuous).
    open_since: dict[str, date] = {t: start for t in at_start}
    intervals: dict[str, list[tuple[date, date | None]]] = {}
    for c in [c for c in ordered if c.effective > start]:
        if c.removed:
            since = open_since.pop(c.removed, None)
            if since is None:
                notes.append(f"{c.effective}: {c.removed} removed while not a member")
            elif since < c.effective:
                intervals.setdefault(c.removed, []).append((since, c.effective))
        if c.added:
            if c.added in open_since:
                notes.append(f"{c.effective}: {c.added} added while already a member")
            else:
                open_since[c.added] = c.effective
    latest = set(current)
    for c in [c for c in ordered if c.effective > snapshot]:
        latest.discard(c.removed)
        if c.added:
            latest.add(c.added)
    for ticker, since in open_since.items():
        if ticker not in latest:
            # Added by the table but not in the index today and never
            # removed by it: a ticker change the table does not record
            # (FLT->CPAY, RE->EG). The interval cannot be closed honestly.
            notes.append(f"{ticker}: added {since}, no exit recorded, not in the index today; dropped")
            continue
        intervals.setdefault(ticker, []).append((since, None))
    # A same-day rename row (added X, removed X) leaves two touching stints;
    # merged, the name is continuous.
    return {t: _merge(rows) for t, rows in intervals.items()}, notes


# Merge overlapping or touching intervals of one ticker.
def _merge(rows: list[tuple[date, date | None]]) -> list[tuple[date, date | None]]:
    merged: list[tuple[date, date | None]] = []
    for entered, exited in sorted(rows, key=lambda r: r[0]):
        if merged and (merged[-1][1] is None or merged[-1][1] >= entered):
            last_entered, last_exited = merged[-1]
            if last_exited is None or exited is None:
                merged[-1] = (last_entered, None)
            else:
                merged[-1] = (last_entered, max(last_exited, exited))
        else:
            merged.append((entered, exited))
    return merged


# The book's membership records: index members in book sub-industries plus
# overlay names from their commit dates, with a source and a rule on each.
def build_records(
    constituents: list[universe.UniverseMember] | None = None,
    changes: list[Change] | None = None,
    overlay_added: dict[str, tuple[date, str]] | None = None,
    start: date = WINDOW_START,
) -> tuple[list[membership.MembershipRecord], list[str]]:
    """Return (records, notes)."""
    constituents = constituents if constituents is not None else universe.load_constituents()
    changes = changes if changes is not None else load_changes()
    overlay_added = overlay_added if overlay_added is not None else OVERLAY_ADDED
    current = frozenset(m.ticker.replace(".", "-") for m in constituents)
    sub_industry = {m.ticker.replace(".", "-"): m.sub_industry for m in constituents}
    intervals, notes = index_intervals(current, changes, CONSTITUENTS_ASOF, start)
    unclassified: list[str] = []
    per_ticker: dict[str, list[tuple[date, date | None, str, str]]] = {}
    for ticker, rows in intervals.items():
        for entered, exited in rows:
            # A closed interval is classified only by the curated table: the
            # constituent file describes today's company, and a ticker can
            # have belonged to another one (Q in 2017).
            if exited is None:
                industry = sub_industry.get(ticker)
            else:
                industry = EXITED_BOOK_SUB_INDUSTRY.get((ticker, exited))
                if industry is None:
                    unclassified.append(f"{ticker}@{exited}")
                    continue
            if industry not in universe.BOOK_SUB_INDUSTRIES:
                continue
            rule = f"S&P 500 member in {industry}"
            if entered == start:
                rule += f"; in the index at the window start {start}"
            per_ticker.setdefault(ticker, []).append(
                (entered, exited, CHANGES_SOURCE, rule)
            )
    for ticker, (added, commit) in overlay_added.items():
        per_ticker.setdefault(ticker, []).append(
            (
                added,
                None,
                f"backend/market/universe.py OVERLAY, commit {commit}",
                f"listed by hand in universe.py on {added}",
            )
        )
    records: list[membership.MembershipRecord] = []
    for ticker in sorted(per_ticker):
        rows = per_ticker[ticker]
        merged = _merge([(e, x) for e, x, _, _ in rows])
        for entered, exited in merged:
            covering = [r for r in rows if r[0] <= entered and (r[1] is None or r[1] > entered)]
            source = "; ".join(sorted({r[2] for r in covering})) or rows[0][2]
            rule = " | ".join(sorted({r[3] for r in covering})) or rows[0][3]
            records.append(
                membership.MembershipRecord(
                    ticker=ticker,
                    entered=entered,
                    entry_announced=entered,
                    exited=exited,
                    exit_announced=exited,
                    source=source,
                    rule=rule,
                )
            )
    if unclassified:
        notes.append(
            "exits with no curated sub-industry, treated as non-book: "
            + " ".join(sorted(unclassified))
        )
    membership.validate_history(records)
    return records, notes


# Serialise records in the column order `membership.load_history` reads.
def render(records: list[membership.MembershipRecord]) -> str:
    """Return the CSV text."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        ["ticker", "entered", "entry_announced", "exited", "exit_announced", "source", "rule"]
    )
    for r in records:
        writer.writerow(
            [
                r.ticker,
                r.entered.isoformat(),
                r.entry_announced.isoformat(),
                r.exited.isoformat() if r.exited else "",
                r.exit_announced.isoformat() if r.exit_announced else "",
                r.source,
                r.rule,
            ]
        )
    return buffer.getvalue()


# Build, then write or compare, and print what the reconstruction could not place.
def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="diff against the committed file")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args(argv)
    records, notes = build_records()
    text = render(records)
    today = universe.book_sides(universe.build_universe())
    listed = {r.ticker for r in records}
    missing = sorted(set(today) - listed)
    print(f"{len(records)} intervals over {len(listed)} names")
    print(f"today's book: {len(today)} names, {len(missing)} not covered: {missing}")
    for note in notes:
        print("note:", note)
    if args.check:
        if not args.output.exists():
            print(f"{args.output} does not exist")
            return 1
        if args.output.read_text(encoding="utf-8") != text:
            print(f"{args.output} differs from the rebuild")
            return 1
        print("committed file matches the rebuild")
        return 0
    args.output.write_text(text, encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
