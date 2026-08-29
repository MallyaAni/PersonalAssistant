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
    parsed = stated_date(text)
    if parsed is None or parsed.date() < moment.date():
        return None
    return parsed


# Parse the first explicit calendar date without deciding whether it is current.
def stated_date(text: str) -> datetime | None:
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
