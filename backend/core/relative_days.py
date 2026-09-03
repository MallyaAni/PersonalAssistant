"""Relative day words, written out as the dates they meant when said.

A memory saved as "going to trivia at Courthouse Social today" is true on
the day it was said and false every day after; recalled the next morning it
read as today's plan (the group chat, 2026-09-03). A statement that names
its date stays true: "going to trivia at Courthouse Social on Wednesday
2 September 2026". The words are few and fixed, so they are resolved here,
in code, against the speaker's own calendar day, at the moment the memory is
written. Nothing else in the sentence is touched.
"""
import re
from datetime import datetime, timedelta

_PATTERNS: tuple[tuple[re.Pattern[str], int, str], ...] = (
    # (pattern, day offset, template) - the template takes the written date.
    (re.compile(r"\bthe day after tomorrow\b", re.IGNORECASE), 2, "on {date}"),
    (re.compile(r"\btonight\b", re.IGNORECASE), 0, "on the evening of {date}"),
    (re.compile(r"\bthis (?:evening|afternoon|morning)\b", re.IGNORECASE), 0, "on {date}"),
    (re.compile(r"\btoday\b", re.IGNORECASE), 0, "on {date}"),
    (re.compile(r"\btomorrow\b", re.IGNORECASE), 1, "on {date}"),
    (re.compile(r"\byesterday\b", re.IGNORECASE), -1, "on {date}"),
)
_WEEKEND = re.compile(r"\bthis weekend\b", re.IGNORECASE)


def _written(day: datetime) -> str:
    return f"{day:%A} {day.day} {day:%B} {day.year}"


# The text with every relative day word replaced by the date it meant, given
# the speaker's local `now`. "on today" would read oddly, so a preceding
# "on " is folded into the replacement.
def absolutize_days(text: str, now: datetime) -> str:
    out = text or ""
    for pattern, offset, template in _PATTERNS:
        date = _written(now + timedelta(days=offset))
        out = re.sub(r"\bon\s+" + pattern.pattern, template.format(date=date), out, flags=re.IGNORECASE)
        out = pattern.sub(template.format(date=date), out)
    if _WEEKEND.search(out):
        saturday = now + timedelta(days=(5 - now.weekday()) % 7)
        if now.weekday() >= 4 and saturday - now > timedelta(days=1):
            saturday -= timedelta(days=7)
        sunday = saturday + timedelta(days=1)
        out = _WEEKEND.sub(f"the weekend of {saturday.day}-{sunday.day} {sunday:%B} {sunday.year}", out)
    return out


# Whether the text carries a relative day word at all.
def has_relative_day(text: str) -> bool:
    return any(pattern.search(text or "") for pattern, _, _ in _PATTERNS) or bool(_WEEKEND.search(text or ""))
