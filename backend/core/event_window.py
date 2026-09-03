"""The calendar window a question about events means.

"What's on this week?" asked on a Wednesday means Wednesday to Sunday, not
the momo crawl a week on Sunday - which is what a listing showed on
2026-09-02 for an Arlington question, because nothing between the search
and the reader checked the dates against the words. The words are few and
fixed, so the window is decided here in code, in the person's own calendar
day, and the listing is held to it.
"""
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True, slots=True)
class Window:
    """First and last calendar day, inclusive, and the words that named it."""

    start: date
    end: date
    label: str

    def holds(self, day: date | None) -> bool:
        return day is not None and self.start <= day <= self.end


_TODAY = re.compile(r"\b(today|tonight|this evening|this afternoon)\b", re.IGNORECASE)
_TOMORROW = re.compile(r"\btomorrow\b", re.IGNORECASE)
_THIS_WEEKEND = re.compile(r"\b(this|the|on the) weekend\b|\bweekend\b", re.IGNORECASE)
_NEXT_WEEKEND = re.compile(r"\bnext weekend\b", re.IGNORECASE)
_THIS_WEEK = re.compile(r"\bthis week\b|\bthe week\b|\bthe coming days\b|\bthe next few days\b", re.IGNORECASE)
_NEXT_WEEK = re.compile(r"\bnext week\b", re.IGNORECASE)


# Saturday and Sunday of the week `day` is in - or, from Friday on, the one
# already under way, since "this weekend" on a Friday night is not next week's.
def _weekend_of(day: date) -> tuple[date, date]:
    saturday = day + timedelta(days=(5 - day.weekday()) % 7)
    if day.weekday() >= 4 and saturday - day > timedelta(days=1):
        saturday -= timedelta(days=7)
    friday = saturday - timedelta(days=1)
    return (max(day, friday), saturday + timedelta(days=1))


# The window the words mean, or None when the question names no time.
def window_for(question: str, now: datetime) -> Window | None:
    text = " ".join((question or "").split())
    today = now.date()
    if _NEXT_WEEKEND.search(text):
        start, end = _weekend_of(today + timedelta(days=7 - today.weekday()))
        return Window(start, end, "next weekend")
    if _NEXT_WEEK.search(text):
        start = today + timedelta(days=7 - today.weekday())
        return Window(start, start + timedelta(days=6), "next week")
    if _TOMORROW.search(text):
        day = today + timedelta(days=1)
        return Window(day, day, "tomorrow")
    if _TODAY.search(text):
        return Window(today, today, "today")
    if _THIS_WEEKEND.search(text):
        start, end = _weekend_of(today)
        return Window(start, end, "this weekend")
    if _THIS_WEEK.search(text):
        end = today + timedelta(days=6 - today.weekday())
        return Window(today, end, "this week")
    return None
