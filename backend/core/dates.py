"""The one parser in this repository that turns a written date into a date.

It lived in the web discovery source, because that is where it was first
needed. `backend/core/event_extraction.py` then had to reach across into the
discovery stack - and its httpx dependency - to read a date out of a search
snippet, which is the wrong direction for an import and the usual prelude to
someone writing a second parser instead. A date parser is not a discovery
concern; both sides import it from here now.

The rule it enforces has not changed, and is the whole point: a date is read,
never inferred. "This weekend", "next Saturday" and "summer" resolve to
nothing, because resolving them needs a reference point the text does not
carry - and an entry built on a guessed reference point is confidently wrong
in a way nobody notices until they turn up on the wrong day.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

# Three-letter stems, so "Sept", "Sep." and "September" all match one branch.
# Listing full names only would silently miss the abbreviations that dominate
# real listings.
#
# Public because the query skeleton below appends a month, so anything building
# a subject to go in front of it has to recognise the same set to avoid saying
# the month twice. One list, or the two drift.
MONTH_STEMS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"

# Explicit, unambiguous date forms only. Anything requiring inference — "this
# weekend", "next Saturday", "summer" — is deliberately absent, because
# resolving it needs a reference point the snippet does not carry.
_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 2026-09-12
    re.compile(r"\b(?P<y>20\d{2})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b"),
    # September 12, 2026  /  Sept 12 2026
    re.compile(
        rf"\b(?P<mon>{MONTH_STEMS})[a-z]*\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+"
        rf"(?P<y>20\d{{2}})\b",
        re.IGNORECASE,
    ),
    # 12 September 2026
    re.compile(
        rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<mon>{MONTH_STEMS})[a-z]*\.?,?\s+"
        rf"(?P<y>20\d{{2}})\b",
        re.IGNORECASE,
    ),
)

_MONTH_NUMBERS = {
    name: index
    for index, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        start=1,
    )
}



# Pull a date out of text only when the text states one outright.
#
# Returns midnight UTC on that day. That is a deliberate compromise: the day is
# what the source actually asserted, and a fabricated clock time would be
# invented precision. A calendar entry built from this reads as an all-day event
# rather than claiming a start nobody published.
def extract_explicit_date(text: str, now: datetime | None = None) -> datetime | None:
    moment = now or datetime.now(UTC)
    parsed = stated_date(text, moment)
    if parsed is None or parsed.date() < moment.date():
        return None
    return parsed


# Date forms that state the day and month but not the year - which is how
# event calendars write them: Patch's "Saturday, September 5", Eventbrite's
# "Fri, Sep 5 · 7:00 PM", ARLnow's "September 9", a "9/5" on a flyer. The
# year is the one that puts the day on or after today (the next such day),
# which is the same reading every person gives a poster. Until 2026-09-02
# these all read as "no date", and ten of twelve extracted Arlington events
# were dropped as undated from a listing for "events this week".
_YEARLESS_PATTERNS: tuple[re.Pattern[str], ...] = (
    # September 5  /  Sept. 5th  /  Sep 5
    re.compile(
        rf"\b(?P<mon>{MONTH_STEMS})[a-z]*\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\b(?!\s*,?\s*20\d{{2}})",
        re.IGNORECASE,
    ),
    # 5 September  /  5th Sept
    re.compile(
        rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<mon>{MONTH_STEMS})[a-z]*\.?\b(?!,?\s+20\d{{2}})",
        re.IGNORECASE,
    ),
    # 9/5  /  9/5/2026  (month first, as the sources here write it)
    re.compile(r"\b(?P<m>\d{1,2})/(?P<d>\d{1,2})(?:/(?P<y>20\d{2}))?\b"),
)


# Parse the first explicit calendar date without deciding whether it is
# current. A date written without its year resolves against `now` to the
# next such day; with no `now`, only year-bearing dates are read.
def stated_date(text: str, now: datetime | None = None) -> datetime | None:
    dated = _with_year(text)
    if dated is not None or now is None:
        return dated
    for pattern in _YEARLESS_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        groups = match.groupdict()
        if groups.get("m") is not None:
            month_number: int | None = int(groups["m"])
        else:
            month_number = _month_number((groups.get("mon") or "").lower())
        if month_number is None or not 1 <= month_number <= 12:
            continue
        day = int(groups["d"])
        year = int(groups["y"]) if groups.get("y") else now.year
        try:
            parsed = datetime(year, month_number, day, tzinfo=UTC)
        except ValueError:
            continue
        if not groups.get("y") and parsed.date() < now.date():
            try:
                parsed = datetime(year + 1, month_number, day, tzinfo=UTC)
            except ValueError:
                continue
        return parsed
    return None


def _with_year(text: str) -> datetime | None:
    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        groups = match.groupdict()
        month = groups.get("m")
        if month is None:
            month_name = (groups.get("mon") or "").lower()
            month_number = _month_number(month_name)
        else:
            month_number = int(month)
        if month_number is None or not 1 <= month_number <= 12:
            continue
        try:
            parsed = datetime(
                int(groups["y"]), month_number, int(groups["d"]), tzinfo=UTC
            )
        except ValueError:
            continue
        return parsed
    return None


def _month_number(name: str) -> int | None:
    for full, number in _MONTH_NUMBERS.items():
        if full.startswith(name[:3]) and name:
            return number
    return None
