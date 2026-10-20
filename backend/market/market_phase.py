"""The market phase the dashboard states beside every recommendation.

Stocks trade almost around the clock (pre-market from 04:00, after-hours to
20:00, overnight sessions at several brokers), but the strategy's inputs and
models are regular-session objects: grades come from daily closes, the timing
and sizing models were fitted on regular-hours fifteen-minute bars, and the
execution quotes carry a spread guard that extended hours would trip. So the
desk acts only between the reviewed open and close, and the honest thing to
show outside that window is not "unavailable" but which phase it is, when the
desk acts next, and when tonight's plan arrives. One function, read from the
reviewed XNYS calendar, so every panel shows the same clock.
"""

from datetime import datetime, time

import numpy as np

from backend.market import calendar, strategy_publication

# Brokers' after-hours sessions end at 20:00 New York; past that the night is
# "overnight" rather than "after-hours" so the words match what a person sees
# on their broker.
AFTER_HOURS_END = time(20, 0)
ACTS_IN = "regular_session"


# The next reviewed regular open strictly after `now`, or None outside the
# reviewed calendar years (fail closed: better no time than a guessed one).
def next_open_at(now: datetime) -> datetime | None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("next open requires a timezone-aware datetime")
    local = now.astimezone(calendar.NEW_YORK)
    years, sessions = calendar.reviewed_sessions()
    if local.year not in years:
        return None
    day = np.datetime64(local.date(), "D")
    candidate = np.busday_offset(day, 0, roll="forward", busdaycal=sessions)
    if candidate == day:
        opens = datetime.combine(local.date(), calendar.REGULAR_OPEN, calendar.NEW_YORK)
        if opens <= local:
            candidate = np.busday_offset(day, 1, busdaycal=sessions)
    target = candidate.astype(object)
    if target.year not in years:
        return None
    return datetime.combine(target, calendar.REGULAR_OPEN, calendar.NEW_YORK)


# Describe the phase and the two clocks a person needs: when the desk acts
# next and when the next plan is published.
def describe(now: datetime) -> dict[str, object]:
    status = calendar.exchange_status(now)
    local = now.astimezone(calendar.NEW_YORK)
    phase = {
        "pre-market": "pre_market",
        "open": "regular",
        "post-market": "after_hours" if local.time() < AFTER_HOURS_END else "overnight",
        "closed": "closed",
        "unknown": "unknown",
    }[str(status["phase"])]
    opens_next = next_open_at(now)
    return {
        "phase": phase,
        "exchange": status["exchange"],
        "calendar_known": status["calendar_known"],
        "is_session": status["is_session"],
        "opens_at": status["opens_at"],
        "closes_at": status["closes_at"],
        "acts_in": ACTS_IN,
        "next_open_at": opens_next.isoformat() if opens_next else None,
        # The desk acts only in the regular session, so the next action is
        # the next open whenever the session is not in progress.
        "next_action_at": status["opens_at"]
        if phase == "pre_market"
        else (
            now.isoformat()
            if phase == "regular"
            else (opens_next.isoformat() if opens_next else None)
        ),
        "next_publication_at": strategy_publication.next_publication_at(
            now
        ).isoformat(),
    }
