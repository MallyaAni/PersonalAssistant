"""Predict the book's next earnings releases from stored 8-K item 2.02 dates.

    python -m backend.cli.market_earnings_calendar --asof 2026-10-30

The store has no announced forward earnings date; the next release is not known
until it is filed. This scan predicts each book name's next release from its own
release history, using only filings filed on or before the as-of session, and
writes one JSON file per session under `data/market/research/earnings-calendar/`.
It reads no model, no prompt and no live rule: the output is descriptive
alerting, and nothing here changes a grade, target, order or prompt.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from backend.agents.trading.desk import desk
from backend.market import earnings_calendar
from backend.market.store import MarketStore

# The window the brief prints in full; the JSON carries every predicted name.
BRIEF_SESSIONS = 60
BRIEF_ROWS = 12


# The nightly scan: one predicted next release per book name with a history.
def scan(store: MarketStore, asof: date) -> dict:
    """Return the earnings-calendar scan for the book on an as-of date."""
    panel, _ = desk.book_panel(store, asof)
    desk_path = store.root / "desk" / f"asof={asof.isoformat()}" / "desk.json"
    decisions = (
        json.loads(desk_path.read_text(encoding="utf-8"))
        if desk_path.exists()
        else {}
    )
    grades = decisions.get("grades", {})
    actions = {row["ticker"]: row for row in decisions.get("actions", [])}
    book = {row["ticker"]: row["weight"] for row in decisions.get("book", [])}
    rows = []
    for ticker in panel.tickers:
        found = store.read_frame(earnings_calendar.EVENTS_KIND, ticker, asof)
        if found is None:
            continue
        row = earnings_calendar.calendar_row(ticker, found[0], asof)
        if row is None:
            continue
        grade = grades.get(ticker, "")
        if isinstance(grade, dict):
            grade = grade.get("grade", "")
        action = actions.get(ticker) or {}
        predicted = date.fromisoformat(row["predicted"])
        last = date.fromisoformat(row["last_release"])
        row.update(
            {
                "theme": panel.themes.get(ticker, ""),
                "grade": grade,
                "grade_headline": (
                    grades[ticker].get("headline")
                    if isinstance(grades.get(ticker), dict)
                    else None
                ),
                "action": action.get("action"),
                "target_weight": action.get("target_weight"),
                "current_weight": book.get(ticker),
                "sessions_until": earnings_calendar.sessions_until(asof, predicted),
                "sessions_since_release": earnings_calendar.sessions_until(last, asof),
            }
        )
        rows.append(row)
    rows.sort(key=lambda row: (row["predicted"], row["ticker"]))
    upcoming = [
        row
        for row in rows
        if row["sessions_until"] is None or row["sessions_until"] <= BRIEF_SESSIONS
    ]
    return {
        "version": "earnings-calendar/1",
        "asof": asof.isoformat(),
        "rule": {
            "source": "8-K item 2.02 filed dates",
            "horizon_years": earnings_calendar.HORIZON_YEARS,
            "match_days": earnings_calendar.MATCH_DAYS,
            "quarter_days": earnings_calendar.QUARTER_DAYS,
            "min_releases": earnings_calendar.MIN_RELEASES,
            "confidence_high_days": earnings_calendar.HIGH_RANGE_DAYS,
            "confidence_medium_days": earnings_calendar.MEDIUM_RANGE_DAYS,
        },
        "upcoming": upcoming,
        "names": rows,
        "counts": {
            "names": len(rows),
            "upcoming": len(upcoming),
            "overdue": sum(1 for row in rows if row["overdue"]),
            "held_upcoming": sum(
                1 for row in upcoming if (row["current_weight"] or 0) > 0
            ),
        },
    }


# The human-readable brief printed beside the JSON.
def brief(result: dict) -> str:
    """Return the plain-word summary of a scan."""
    lines = [f"Earnings calendar {result['asof']}"]
    counts = result["counts"]
    lines.append(
        f"Book names with a predicted next release: {counts['names']} "
        f"({counts['held_upcoming']} held names due within {BRIEF_SESSIONS} sessions, "
        f"{counts['overdue']} overdue predictions)."
    )
    shown = result["upcoming"][:BRIEF_ROWS]
    if shown:
        lines.append(
            f"Next {len(shown)} predicted releases "
            f"(confidence, sessions, held weight):"
        )
    for row in shown:
        weight = row["current_weight"] or 0.0
        held = f", held {weight * 100:.1f}%" if weight > 0 else ""
        sessions = (
            "unknown sessions"
            if row["sessions_until"] is None
            else f"{row['sessions_until']} sessions"
        )
        overdue = " (overdue)" if row["overdue"] else ""
        lines.append(
            f"  {row['ticker']} {row['predicted']}{overdue} "
            f"({row['confidence']}, {sessions}{held}), "
            f"last {row['last_release']}."
        )
    return "\n".join(lines)


# The newest session the nightly wrote a desk record for.
def latest_session(store: MarketStore) -> date | None:
    """Return the newest `desk/asof=` session on file, or None."""
    sessions = []
    for path in (store.root / "desk").glob("asof=*"):
        try:
            sessions.append(date.fromisoformat(path.name.split("=", 1)[1]))
        except ValueError:
            continue
    return max(sessions) if sessions else None


# Parse arguments, run the scan, and write the result.
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market")
    parser.add_argument("--asof", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    store = MarketStore(args.root)
    asof = (
        date.fromisoformat(args.asof)
        if args.asof
        else latest_session(store) or date.today()
    )
    result = scan(store, asof)
    output = Path(
        args.output
        or f"data/market/research/earnings-calendar/asof={asof.isoformat()}"
        "/earnings_calendar.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1, sort_keys=True, allow_nan=False))
    print(brief(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
