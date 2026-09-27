"""Tonight's live grades against the point-in-time replay, asserted every night.

The operator takes real-account positions from the live board's grades.
Three things must agree for that to be safe: the grade the board shows for
a name, the grade the nightly record wrote for it, and the grade the
backtest machinery would assign the same name on the same date. They are
produced by different paths - the record by `market_daily.record` on the
desk report, the backtest by `point_in_time.point_in_time` on a report of
its own, the board by `/desk` reading the record - and any of them can
drift silently: a code path that changed one and not the other, a stale
store rebuilt after more data arrived, a name missing from
`membership_history.csv` so the backtest grades it C while the board says
A. This module makes that disagreement loud.

**The replay grade for date d** is the letter the point-in-time report has
at row d for the name: `market_daily.desk_report` (the desk with the
nightly's own arguments - live inputs, `fundamentals="current"`) restricted
by `point_in_time.point_in_time` (every non-member of the dated book graded
C and unscored, the benchmark excluded), then `graded.letter(row_d, col)`.
That restricted report is exactly what `market_pit_scorecard.build` prices,
so its row d is the grade matrix the backtest uses for that session. It is
computable from the same store on the same night with no lookahead: row d
is the report's last session, decided from partitions on or before d, and
membership is read from the dated history, not from today's book.

Two things the scorecard's own CLI does differently are deliberately not
replayed here. `market_pit_scorecard.main` runs the desk with the research
default `fundamentals="corrected"` (source `/2`), where the nightly opts
into `current` (`/3`); a parity check that rebuilt the report on `/2`
would fail every night the reporting-period safeguard reset a vote, which
is the safeguard doing its job, not a drift. And the scorecard's curves
are priced from earlier rows too; those are history, and the live board
shows only row d. Both are stated in the result's `basis`.

What is compared, for the record's session d:

* every graded name on the board that is a member on d: live letter
  (`record["grades"][t]["grade"]`) against the replay letter;
* membership: names on the board that are not members on d (the replay
  grades them C whatever the board says), and members on d with no grade on
  the board;
* targets: `record["targets"]["weights"]` against `live_policy.targets`
  recomputed on the rebuilt report, to 1e-9, every name either side;
* the session: a rebuilt report whose last session is not d means the
  store moved on since the record (after-hours bars, a later filing
  version) and the replay is not the same evening's evidence. It is
  reported, and targets are not compared, because `live_policy.targets`
  is defined on the last row only.

`run` writes `<root>/desk/grade_parity.json`: one row per date, replaced
when the same date is checked again, the last 90 days kept. On a mismatch
the CLI exits 1 and the nightly prints `GRADE PARITY MISMATCH` into the
same log the shadow ledger's receipt goes to (`~/desk_daily.log` on the
Spark); the nightly never raises on it, and the result rides on the record
as `record["grade_parity"]` so the board shows a red banner.

Legitimate reasons the two can differ, none of which is a reason to trade:
the store refreshed between the record and a later CLI run (the session
row says so); `membership_history.csv` edited after the record; a code
deploy between the two. Each of those is exactly what the operator should
know before sizing a position from the board.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from datetime import date as _date
from pathlib import Path

import numpy as np

VERSION = "grade-parity/1"
FILE = "grade_parity.json"
TOLERANCE = 1e-9
KEEP_DAYS = 90
# The kinds a mismatch row can carry, in the order the CLI prints them.
GRADE = "grade"
MEMBERSHIP = "membership"
TARGETS = "targets"
SESSION = "session"
KINDS = (SESSION, MEMBERSHIP, GRADE, TARGETS)


# Where the parity file lives under the market data root.
def path(root: Path) -> Path:
    """Return `<root>/desk/grade_parity.json`."""
    return Path(root) / "desk" / FILE


# The dated membership file the replay reads, resolved once so the result can
# name it: the universe's default unless the caller points elsewhere.
def _history(history_path: Path | None) -> Path:
    """Return the membership history path in use."""
    from backend.market import universe

    return (
        Path(history_path) if history_path else Path(universe.MEMBERSHIP_HISTORY_PATH)
    )


# The point-in-time restriction of a desk report at one session: the replay
# letter for every non-benchmark name and whether it was a member that day.
# `row` is the panel index of `day`; a day the report does not have is a
# caller error, because there is no row to replay.
def replay(report, day: _date | str, history_path: Path | None = None) -> dict:
    """Return {"grades": {t: letter}, "members": {t: bool}, "row", "session"}."""
    from backend.agents.trading.desk import point_in_time

    panel = report.panel
    days = np.asarray(panel.dates, dtype="datetime64[D]")
    wanted = np.datetime64(str(day), "D")
    hits = np.flatnonzero(days == wanted)
    if len(hits) != 1:
        raise ValueError(f"the report has no session {day}; last is {days[-1]}")
    row = int(hits[0])
    restricted, mask = point_in_time.point_in_time(report, _history(history_path))
    grades: dict[str, str] = {}
    members: dict[str, bool] = {}
    for column, ticker in enumerate(panel.tickers):
        if ticker == panel.benchmark:
            continue
        grades[ticker] = restricted.graded.letter(row, column)
        members[ticker] = bool(mask[row, column])
    return {
        "grades": grades,
        "members": members,
        "row": row,
        "session": str(days[row]),
        "last_session": str(days[-1]),
    }


# Two weights equal to the tolerance; a missing weight is zero, and a
# non-finite one never equals anything, so a NaN target is a mismatch.
def _same_weight(a: float | None, b: float | None) -> bool:
    """Return True when the two weights agree to `TOLERANCE`."""
    x = float(a or 0.0)
    y = float(b or 0.0)
    if not (math.isfinite(x) and math.isfinite(y)):
        return False
    return abs(x - y) <= TOLERANCE


# The comparison itself, on data already in hand: the saved record, the
# desk report the nightly decided from (rebuilt or the very object), and
# the date. Pure: reads nothing, writes nothing, so a test can inject a
# flipped grade or a missing member and read the row that names it.
def compare(
    record: dict, report_pit, day: _date | str, history_path: Path | None = None
) -> dict:
    """Return the parity result for `record` against `report_pit` on `day`."""
    from backend.agents.trading.desk import live_policy

    day_text = str(day)
    mismatches: list[dict] = []
    live_grades = {
        t: (g or {}).get("grade") for t, g in (record.get("grades") or {}).items()
    }
    if record.get("session") != day_text:
        mismatches.append(
            {
                "kind": SESSION,
                "detail": f"record is for {record.get('session')}, not {day_text}",
            }
        )
    rep = replay(report_pit, day_text, history_path)
    same_evening = rep["last_session"] == day_text
    if not same_evening:
        mismatches.append(
            {
                "kind": SESSION,
                "detail": (
                    f"the rebuilt report ends {rep['last_session']}, not "
                    f"{day_text}: the store moved on since the record; "
                    "targets not compared"
                ),
            }
        )
    board = set(live_grades)
    members = {t for t, on in rep["members"].items() if on}
    for ticker in sorted(board - members):
        mismatches.append(
            {
                "kind": MEMBERSHIP,
                "ticker": ticker,
                "live": live_grades[ticker],
                "replay": rep["grades"].get(ticker),
                "detail": "on the board, not a member of the point-in-time book on "
                f"{day_text} (membership_history.csv)",
            }
        )
    for ticker in sorted(members - board):
        mismatches.append(
            {
                "kind": MEMBERSHIP,
                "ticker": ticker,
                "live": None,
                "replay": rep["grades"].get(ticker),
                "detail": (
                    f"a member of the point-in-time book on {day_text}, "
                    "not graded on the board"
                ),
            }
        )
    compared = sorted(board & members)
    for ticker in compared:
        if live_grades[ticker] != rep["grades"][ticker]:
            mismatches.append(
                {
                    "kind": GRADE,
                    "ticker": ticker,
                    "live": live_grades[ticker],
                    "replay": rep["grades"][ticker],
                    "detail": "live grade differs from the point-in-time replay",
                }
            )
    targets_compared = False
    if same_evening:
        targets_compared = True
        live_targets = dict((record.get("targets") or {}).get("weights") or {})
        wanted = live_policy.targets(report_pit)
        for ticker in sorted(set(live_targets) | set(wanted)):
            if not _same_weight(live_targets.get(ticker), wanted.get(ticker)):
                mismatches.append(
                    {
                        "kind": TARGETS,
                        "ticker": ticker,
                        "live": live_targets.get(ticker),
                        "replay": wanted.get(ticker),
                        "detail": (
                            "record target differs from live_policy.targets "
                            f"by more than {TOLERANCE:g}"
                        ),
                    }
                )
    return {
        "version": VERSION,
        "date": day_text,
        "checked": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "ok": not mismatches,
        "names": len(compared),
        "members": len(members),
        "on_board": len(board),
        "targets_compared": targets_compared,
        "replay_session": rep["last_session"],
        "membership_history": str(_history(history_path)),
        "basis": (
            "replay = market_daily.desk_report (live inputs, fundamentals=current) "
            "restricted by point_in_time.point_in_time, letter at the record's "
            "session; "
            "targets = live_policy.targets on the same report"
        ),
        "mismatches": mismatches,
    }


# The result when the check itself could not run: never `ok`, and the
# reason on the row, so a broken check reads as a failed check on the board
# and not as a passed one.
def unavailable(day: _date | str | None, exc: BaseException) -> dict:
    """Return a not-ok result naming why the check did not run."""
    return {
        "version": VERSION,
        "date": str(day) if day else None,
        "checked": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "ok": False,
        "names": 0,
        "mismatches": [
            {
                "kind": "unavailable",
                "detail": f"{type(exc).__name__}: {exc}",
            }
        ],
        "note": f"{type(exc).__name__}: {exc}",
    }


# Distinct names a result's mismatches touch, for the banner and the line.
def names_touched(result: dict) -> list[str]:
    """Return the sorted tickers named in the result's mismatches."""
    return sorted(
        {m["ticker"] for m in result.get("mismatches") or [] if m.get("ticker")}
    )


# The one-line verdict the nightly prints and the CLI ends with.
def line(result: dict) -> str:
    """Return "grade parity: OK (n names)" or the mismatch line."""
    if result.get("ok"):
        return f"grade parity: OK ({result.get('names', 0)} names)"
    touched = names_touched(result)
    parts = []
    for m in result.get("mismatches") or []:
        kind = m.get("kind")
        if m.get("ticker"):
            parts.append(
                f"{m['ticker']} {kind} live={m.get('live')} replay={m.get('replay')}"
            )
        else:
            parts.append(f"{kind}: {m.get('detail')}")
    return (
        f"GRADE PARITY MISMATCH: {result.get('date')}: {len(touched)} names - "
        + "; ".join(parts)
        + " - do not trade from the board"
    )


# The file's rows, oldest first; a missing or unreadable file is no rows.
def load(root: Path) -> dict:
    """Return {"version", "rows": [...]} from the parity file."""
    target = path(root)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": VERSION, "rows": []}
    rows = data.get("rows") if isinstance(data, dict) else None
    return {"version": VERSION, "rows": list(rows or [])}


# The stored row for one session, or None; what the API hands the board.
def for_session(root: Path, session: str | None) -> dict | None:
    """Return the parity row checked for `session`."""
    if not session:
        return None
    for row in load(root)["rows"]:
        if row.get("date") == session:
            return row
    return None


# Append or replace the row for its date and drop rows older than
# `KEEP_DAYS` before the newest, so the file stays a season's evidence.
def write(root: Path, result: dict) -> Path:
    """Write `result` into the parity file and return the path."""
    rows = [r for r in load(root)["rows"] if r.get("date") != result["date"]]
    rows.append(result)
    rows.sort(key=lambda r: r.get("date") or "")
    newest = rows[-1].get("date")
    if newest:
        floor = _date.fromisoformat(newest) - timedelta(days=KEEP_DAYS)
        rows = [
            r for r in rows if r.get("date") and _date.fromisoformat(r["date"]) >= floor
        ]
    target = path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"version": VERSION, "rows": rows}, indent=2, default=float),
        encoding="utf-8",
    )
    return target


# The check end to end. `date` None means the latest record. The report and
# record are rebuilt from the store exactly as the nightly builds them
# (`market_daily.desk_report`, `deskrecord.load`) unless the nightly, which
# has both in hand, passes them in. The result is written to the parity
# file and returned; raising is left to the caller, so the nightly can
# swallow it and the CLI can exit on it.
def run(
    root: Path,
    date: _date | str | None = None,
    *,
    report=None,
    record: dict | None = None,
    history_path: Path | None = None,
) -> dict:
    """Return tonight's parity result for `root`, having written it."""
    from backend.market import deskrecord

    root = Path(root)
    if record is None:
        if date is None:
            record, _previous = deskrecord.latest_pair(root)
        else:
            record = deskrecord.load(root, str(date))
        if record is None:
            raise FileNotFoundError(
                f"no desk record for {date or 'the latest session'} under {root}"
            )
    session = record["session"]
    if date is not None and str(date) != session:
        raise ValueError(f"the record under {root} is for {session}, not {date}")
    if report is None:
        from backend.cli import market_daily
        from backend.market.store import MarketStore

        store = MarketStore(root)
        # The nightly passes `asof=None` for tonight and a date for a
        # historical run; the replay mirrors that so partitions are bounded
        # the same way.
        asof = None if date is None else _date.fromisoformat(session)
        report = market_daily.desk_report(store, asof)
    result = compare(record, report, session, history_path)
    write(root, result)
    return result
