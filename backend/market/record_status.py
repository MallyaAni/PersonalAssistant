"""Whether the desk has written what the last completed session requires.

The page shows the latest record as if it were the decision for tonight.
On 2026-09-15 it was not: the nightly was still running fourteen hours
after the close, the last record was three sessions old, and nothing on
the page said so. This names the last completed exchange session, when
its record and its ML observation are due, and whether each is current,
still pending tonight, or late. The API carries it and the page shows a
plain sentence when something is late.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from backend.market import calendar as exchange_calendar

NEW_YORK = ZoneInfo("America/New_York")
CLOSE = time(16, 0)
# A session's record and observation are due by this hour of the next
# calendar day, New York: the nightly starts at 19:30 and has a three-hour
# tone budget, so a run that is still going at seven is a run that failed.
DUE = time(7, 0)


# The exchange sessions calendar; weekdays alone when a year is not covered.
def _sessions(year: int) -> np.busdaycalendar:
    try:
        years, sessions = exchange_calendar._published_sessions()
    except (OSError, ValueError, KeyError):
        return np.busdaycalendar()
    return sessions if year in years else np.busdaycalendar()


# The last session whose close has happened, New York time.
def last_completed_session(now: datetime) -> date:
    """Return the most recent exchange session that has closed by `now`."""
    local = now.astimezone(NEW_YORK)
    today = np.datetime64(local.date())
    sessions = _sessions(local.year)
    is_session = bool(np.is_busday(today, busdaycal=sessions))
    if is_session and local.time() >= CLOSE:
        return local.date()
    # A session day before the close: the previous session. A weekend or
    # holiday: the nearest session before it (a roll, not an offset, or a
    # Sunday would land on Thursday).
    steps = -1 if is_session else 0
    previous = np.busday_offset(today, steps, roll="backward", busdaycal=sessions)
    return previous.astype(object)


# When a session's record is due: the next calendar morning, New York.
def due_at(session: date) -> datetime:
    """Return the deadline for a session's record and observation."""
    return datetime.combine(session + timedelta(days=1), DUE, tzinfo=NEW_YORK)


# One item's standing against the expected session.
def standing(have: str | None, expected: date, now: datetime) -> str:
    """Return 'current', 'pending' or 'late'.

    Nothing on file is treated like an old session: pending until the
    morning after the expected session, late after it. A frozen
    experiment that has never observed is late, not exempt.
    """
    if have and date.fromisoformat(have) >= expected:
        return "current"
    return "late" if now >= due_at(expected) else "pending"


# The status block for the API.
def describe(root: Path, now: datetime | None = None) -> dict:
    """Return the record's and the ML observation's standing as plain data."""
    from backend.market import deskrecord, opportunity_shadow

    now = now or datetime.now(tz=NEW_YORK)
    expected = last_completed_session(now)
    sessions = deskrecord.sessions(root)
    record_session = max(sessions) if sessions else None
    state = opportunity_shadow.latest(Path(root) / "desk/ml-forward")
    observed = (state or {}).get("session")
    return {
        "expected": expected.isoformat(),
        "due_at": due_at(expected).isoformat(timespec="minutes"),
        "record": {
            "session": record_session,
            "status": standing(record_session, expected, now),
        },
        "ml_forward": {
            "session": observed,
            "status": standing(observed, expected, now),
        },
    }
