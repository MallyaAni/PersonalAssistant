"""Read the date a publisher put in its own URL.

Undated finds are the weak half of every digest, and the reason they slip past
the past-event filter: that filter reads `starts_at`, and a find with no start
has nothing to compare. So a jazz evening on 6 August was announced on the 8th,
because nothing in the pipeline knew it had happened — even though the page
said so plainly, in `/event/2026-08-06-phillips-after-5`.

The date is used for exactly one thing: deciding that a find has **passed**. It
is never promoted to `starts_at`.

That restraint is the point. A slug date is a strong signal that something is
over and a poor one for when it begins — it carries no time of day, no zone,
and on some sites it is the day the page was published rather than the day the
thing happens. Turning it into an appointment would be inventing one, which is
what `links` refuses to do for section headings and what this refuses to do
here. Declining to show something stale needs far less certainty than putting a
time in front of someone, so the weaker signal is spent on the weaker claim.
"""

import re
from datetime import date

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_MONTH_NAMES = "|".join(_MONTHS)
_DAY = r"0?[1-9]|[12]\d|3[01]"

# 2026-08-06 and 2026/08/06. Unambiguous, so it is tried first.
_ISO = re.compile(rf"(?<!\d)(20\d{{2}})[-/](0?[1-9]|1[0-2])[-/]({_DAY})(?!\d)")

# august-01-2026, aug-1-2026, august-2026 (day optional).
_MONTH_FIRST = re.compile(
    rf"(?<![a-z])({_MONTH_NAMES})[-_/]?({_DAY})?[-_/](20\d{{2}})(?!\d)",
    re.IGNORECASE,
)

# 01-august-2026.
_DAY_FIRST = re.compile(
    rf"(?<!\d)({_DAY})[-_/]({_MONTH_NAMES})[-_/](20\d{{2}})(?!\d)",
    re.IGNORECASE,
)


# The date a URL states, or None when it states none.
#
# Only the first match is read. A URL carrying two dates is a range or an
# archive path, and picking one of them would be a guess.
def date_from_url(url: str | None) -> date | None:
    if not url:
        return None
    lowered = url.lower()

    iso = _ISO.search(lowered)
    if iso is not None:
        return _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))

    # Day-first before month-first, because the month-first pattern treats the
    # day as optional and would read "01-august-2026" as a bare "august-2026",
    # quietly moving the date to the end of the month.
    day_first = _DAY_FIRST.search(lowered)
    if day_first is not None:
        return _safe_date(
            int(day_first.group(3)),
            _MONTHS[day_first.group(2)],
            int(day_first.group(1)),
        )

    month_first = _MONTH_FIRST.search(lowered)
    if month_first is not None:
        day = month_first.group(2)
        return _safe_date(
            int(month_first.group(3)),
            _MONTHS[month_first.group(1)],
            # A month with no day is treated as its last possible day, so a
            # whole month is only "past" once every day in it is.
            int(day) if day else 28,
        )
    return None


# Whether a find with no stated start is demonstrably over.
#
# Strictly before today, so anything dated today survives: an evening event is
# still ahead of someone reading at nine in the morning, and the slug carries no
# time of day to decide otherwise.
def looks_past(url: str | None, today: date) -> bool:
    stated = date_from_url(url)
    return stated is not None and stated < today


# Reject an impossible date rather than raising. A URL containing 2026-02-31 is
# a slug, not a calendar.
def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


# A deadline stated without a year — "through August 3", "until Sept 12".
#
# The explicit-date parser deliberately requires a year, because a bare month
# and day is ambiguous. A deadline is the case where it is not: nobody writes
# "open through August 3" about next year, so the current year is what they
# meant, and if that has passed the thing is over.
#
# This exists because asking the model was not enough. The describe call already
# says "Today is {today}. Set already_happened true when a deadline has gone by",
# and a real digest still offered a vote that closed on August 3 to someone
# reading it on August 10. Date arithmetic is not what a 4B model is for; it is
# what a date library is for.
_MONTH_INDEX = {
    month: index
    for index, month in enumerate(
        (
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ),
        start=1,
    )
}

_DEADLINE = re.compile(
    r"\b(?:through|until|thru|ends?|clos(?:e|es|ing)|deadline)\s+"
    r"(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\b(?!\s*,?\s*20\d{2})",
    re.IGNORECASE,
)

# How long after a stated deadline a find is still allowed through. A day, so a
# timezone difference between the page and this machine cannot drop something
# that is still open where it is happening.
_DEADLINE_GRACE_DAYS = 1


# Whether the text states a deadline, in the current year, that has already gone.
def deadline_has_passed(text: str | None, today: date) -> bool:
    if not text:
        return False
    for match in _DEADLINE.finditer(text):
        month = _MONTH_INDEX.get(match.group("mon").lower()[:3])
        if month is None:
            continue
        try:
            stated = date(today.year, month, int(match.group("day")))
        except ValueError:
            continue
        # A deadline late in the year read in January is last year's phrasing
        # only if it is wildly ahead; treat anything more than six months out as
        # belonging to the year just gone rather than inventing a future.
        if (stated - today).days > 183:
            stated = date(today.year - 1, month, int(match.group("day")))
        if (today - stated).days > _DEADLINE_GRACE_DAYS:
            return True
    return False
