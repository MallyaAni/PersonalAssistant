"""Forward earnings calendar from stored 8-K item 2.02 filing dates.

The store has no announced forward earnings date: the next release is not in
the store until it is filed. This module predicts it from the company's own
release history, using only filings filed on or before the decision session.

The prediction is the median of the same fiscal quarter's release dates in the
prior years, each shifted by its whole-year offset, matched by date rather than
by index so a missed filing does not move the quarter. When no prior-year match
exists it falls back to the median interval between recent releases. The
prediction is descriptive: the live rule does not read it, and the scan writes
under `research/earnings-calendar/`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from statistics import median

import numpy as np

from backend.market import calendar as market_calendar

# The stored 8-K frames and the earnings item.
EVENTS_KIND = "edgar_events"
EARNINGS_FORM = "8-K"
EARNINGS_ITEM = "2.02"

# The predictor's fixed design. The horizon is the number of prior years whose
# same-quarter release is a candidate; the match tolerance absorbs a fiscal
# calendar that moves a few weeks between years.
HORIZON_YEARS = 3
MATCH_DAYS = 50
QUARTER_DAYS = 91
MIN_RELEASES = 5
INTERVAL_MIN_DAYS = 60
INTERVAL_MAX_DAYS = 120
INTERVAL_LOOKBACK = 8

# Confidence from the spread of the same-quarter candidates.
HIGH_RANGE_DAYS = 10
MEDIUM_RANGE_DAYS = 20


# The earnings release dates in one stored events frame: 8-K item 2.02.
def release_dates(columns: Mapping[str, list]) -> list[date]:
    """Return the sorted unique 8-K item 2.02 filing dates in a frame."""
    out = set()
    filed = columns.get("filed", [])
    items = columns.get("items", [])
    forms = columns.get("form", [])
    for index, day in enumerate(filed):
        form = str(forms[index]) if index < len(forms) else ""
        item = str(items[index]) if index < len(items) else ""
        codes = {code.strip() for code in item.split(",")}
        if form != EARNINGS_FORM or EARNINGS_ITEM not in codes:
            continue
        try:
            out.add(date.fromisoformat(str(day)))
        except ValueError:
            continue
    return sorted(out)


# The same calendar day in another year. A leap day falls back to February 28
# so the shift never raises and never drifts by a day across a leap year.
def shift_years(day: date, years: int) -> date:
    """Return `day` shifted by whole calendar years."""
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


# The same fiscal quarter in prior years, matched by date, not by index.
def same_quarter_candidates(dates: list[date], index: int) -> list[date]:
    """Return prior-year release dates for the quarter after `dates[index]`."""
    anchor = dates[index]
    out = []
    for years in range(1, HORIZON_YEARS + 1):
        target = shift_years(anchor, -years) + timedelta(days=QUARTER_DAYS)
        best = None
        distance = None
        for earlier in dates[: index + 1]:
            gap = abs((earlier - target).days)
            if gap <= MATCH_DAYS and (distance is None or gap < distance):
                best, distance = earlier, gap
        if best is not None:
            out.append(shift_years(best, years))
    return sorted(out)


# The median interval between recent quarterly releases, ignoring gaps.
def interval_days(dates: list[date], index: int) -> int | None:
    """Return the median quarterly gap in days, or None."""
    gaps = [
        (dates[j] - dates[j - 1]).days
        for j in range(max(1, index - INTERVAL_LOOKBACK + 1), index + 1)
    ]
    gaps = [gap for gap in gaps if INTERVAL_MIN_DAYS <= gap <= INTERVAL_MAX_DAYS]
    if not gaps:
        return None
    return int(round(median(gaps)))


# The middle date of a non-empty list, used instead of averaging dates.
def median_date(values: list[date]) -> date:
    """Return the middle date of a non-empty list."""
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


# The confidence label from the spread of the same-quarter candidates.
def confidence(candidates: list[date], method: str) -> str:
    """Return high, medium or low for a prediction."""
    if method != "same_quarter" or len(candidates) < 2:
        return "low"
    spread = (max(candidates) - min(candidates)).days
    if len(candidates) >= 3 and spread <= HIGH_RANGE_DAYS:
        return "high"
    if spread <= MEDIUM_RANGE_DAYS:
        return "medium"
    return "low"


# Predict the next release from the releases filed on or before `asof`.
def predict(dates: list[date], asof: date) -> dict | None:
    """Return the next-release prediction using only releases filed by asof."""
    known = [day for day in dates if day <= asof]
    if len(known) < MIN_RELEASES:
        return None
    index = len(known) - 1
    candidates = same_quarter_candidates(known, index)
    if candidates:
        predicted = median_date(candidates)
        method = "same_quarter"
        low, high = min(candidates), max(candidates)
    else:
        gap = interval_days(known, index)
        if gap is None:
            return None
        predicted = known[index] + timedelta(days=gap)
        method = "interval"
        low = high = predicted
    return {
        "last_release": known[index].isoformat(),
        "predicted": predicted.isoformat(),
        "low": low.isoformat(),
        "high": high.isoformat(),
        "years": len(candidates),
        "method": method,
        "confidence": confidence(candidates, method),
        "overdue": predicted < asof,
    }


# The reviewed sessions after `start` through `end`, or None outside the calendar.
def _sessions(start: date, end: date) -> int | None:
    """Return the reviewed sessions after start through end, or None."""
    years, busday = market_calendar.reviewed_sessions()
    if start.year not in years or end.year not in years:
        return None
    return int(
        np.busday_count(
            np.datetime64(start + timedelta(days=1), "D"),
            np.datetime64(end + timedelta(days=1), "D"),
            busdaycal=busday,
        )
    )


# The signed number of reviewed sessions from `asof` to `target`: negative when
# the target has passed, so an overdue prediction says how late it is.
def sessions_until(asof: date, target: date) -> int | None:
    """Return the signed session count from asof to target, or None."""
    if target < asof:
        later = _sessions(target, asof)
        return None if later is None else -later
    return _sessions(asof, target)


# One name's calendar row: the last release and the next expected one.
def calendar_row(ticker: str, columns: Mapping[str, list], asof: date) -> dict | None:
    """Return the calendar row for one name, or None without enough history."""
    prediction = predict(release_dates(columns), asof)
    if prediction is None:
        return None
    return {"ticker": ticker, **prediction}
