"""Whether a session closes its trading week, read from the exchange calendar.

The weekly EMA needs to know, on each row, whether that session is the last
of its Monday-to-Friday week. A historical panel can look at the next row;
the live run cannot, because the next session has not happened yet, so a
Thursday before a Friday holiday used to close the week in the replay and
not in the live grade. The reviewed XNYS calendar knows the next session in
advance, so both read the answer from here.

This lives beside `calendar.py` rather than inside it because the saved
timing and holding artefacts bind the exact bytes of `calendar.py`
(`probabilistic_execution_saved.CORRECTED_CALENDAR_SHA`, the learned
holding release's source identity); a helper added there would invalidate
every installed approval for a change that touches none of their logic.
"""

from datetime import date

import numpy as np

from backend.market import calendar


# Whether a reviewed session closes its Monday-to-Friday week: no scheduled
# session remains in the same week. None means the date or its next session
# is outside the reviewed years, so the caller must fall back to the panel it
# has rather than guessing holidays.
def ends_week(day: date | np.datetime64) -> bool | None:
    """Return whether `day` is the last reviewed session of its week."""
    value = np.datetime64(day, "D")
    years, sessions = calendar.reviewed_sessions()
    if value.astype(object).year not in years:
        return None
    # A date the calendar says is closed is not a session, so it cannot close
    # a week even if a synthetic panel happens to carry a row for it.
    if not np.is_busday(value, busdaycal=sessions):
        return False
    following = np.busday_offset(value, 1, busdaycal=sessions)
    if following.astype(object).year not in years:
        return None
    return (int(following.astype(int)) + 3) // 7 != (int(value.astype(int)) + 3) // 7
