"""The events listing, written by code from typed records.

Every line here used to be the reply model's to write, and on 2026-08-29 it
wrote five invented map links, an invented video link, and a venue's opening
hours in the place where a start time goes. Nothing in the pipeline could have
caught that, because there was nothing to compare the words against.

Now the model's part is over before this runs: it quoted, the extractor
checked the quotations against the results, and what arrives here is a set of
records whose every field some page actually stated
(`backend/core/event_extraction.py`). This module turns those into the lines a
person reads, and builds the links itself from the venue and the act - search
boxes, not destinations, which is the one kind of address code can honestly
construct (`backend/core/links.py`).

The count of what was dropped is part of the listing, not a footnote. "Nothing
is on this week" and "four things turned up and none of them said when" are
different answers, and a reader who cannot tell them apart is being misled by
omission.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from backend.core.event_extraction import Extraction, ListedEvent
from backend.core.links import calendar_link, maps_search, youtube_search

# Longer than a phone shows at a glance, and past the point where a listing
# stops being read. The rest is offered rather than printed.
MAX_LISTED = 8


# The whole listing as text, or "" when there is nothing to render at all -
# in which case the caller keeps the model's prose answer.
def render_listing(
    extraction: Extraction,
    now: datetime | None = None,
    limit: int = MAX_LISTED,
) -> str:
    events = list(extraction.events)[: max(1, limit)]
    if not events:
        return ""
    moment = now or datetime.now(UTC)
    lines: list[str] = []
    current: date | None = None
    for event in events:
        day = event.day
        if day != current:
            current = day
            if lines:
                lines.append("")
            lines.append(_day_heading(day, moment))
        lines.extend(_event_lines(event))
    tail = _dropped_line(extraction, len(extraction.events) - len(events))
    if tail:
        lines.extend(["", tail])
    lines.extend(["", "Tap Add on any of them, or tell me which one and I'll set a reminder."])
    return "\n".join(lines)


# "Today", "Tomorrow", then "Sun 31 Aug" - written out rather than left as a
# bare weekday, because "Sunday" alone is the phrasing that made a recurring
# listing read as though it were this week.
def _day_heading(day: date | None, now: datetime) -> str:
    if day is None:
        return "Date not given"
    today = now.date()
    if day == today:
        return f"Today, {day.strftime('%a')} {day.day} {day.strftime('%b')}"
    if (day - today).days == 1:
        return f"Tomorrow, {day.strftime('%a')} {day.day} {day.strftime('%b')}"
    return f"{day.strftime('%a')} {day.day} {day.strftime('%b')}"


def _event_lines(event: ListedEvent) -> list[str]:
    headline = event.name
    if event.artist and event.artist.casefold() not in event.name.casefold():
        headline = f"{headline} — {event.artist}"
    lines = [f"• {headline}"]
    where = ", ".join(part for part in (event.venue, event.area) if part)
    if where:
        lines.append(f"  {where}")
    if event.what:
        lines.append(f"  {event.what}")
    detail = " · ".join(part for part in (_when(event), _price(event)) if part)
    if detail:
        lines.append(f"  {detail}")
    subject = " ".join(part for part in (event.venue, event.area) if part)
    lines.append(f"  Map: {maps_search(subject)}")
    # One tap and it is in their calendar, with the name, the time and the
    # place already filled in. The listing used to end by asking "want any of
    # these in your calendar?" and then have no way to do it, which is the
    # kind of offer that makes an assistant feel like a brochure.
    lines.append(f"  Add: {calendar_link(event.name, event.starts_at, location=subject)}")
    if event.artist:
        lines.append(f"  Hear it: {youtube_search(event.artist)}")
    if event.source_url:
        lines.append(f"  Details: {event.source_url}")
    return lines


# The time, said only as strongly as the source said it. A recurring night
# carries the phrase it was read from, so a reader can see the date is this
# week's occurrence of something regular rather than a one-off announcement.
def _when(event: ListedEvent) -> str:
    clock = _clock(event.start_time) if event.start_time else ""
    if event.recurring:
        phrase = event.when_text.strip()
        return f"{clock} ({phrase})" if clock else f"({phrase})"
    return clock or "time not listed"


def _clock(value: time) -> str:
    hour = value.hour % 12 or 12
    meridiem = "am" if value.hour < 12 else "pm"
    return f"{hour}{meridiem}" if value.minute == 0 else f"{hour}:{value.minute:02d}{meridiem}"


# Always labelled, and always present. A listing that simply omits the price
# when a page did not give one reads as free; and the post-deploy harness looks
# for a price statement as its evidence that the events shape was applied
# (backend/cli/exercise_search_scenarios.py), which it can only do if there is
# always one to find.
def _price(event: ListedEvent) -> str:
    stated = event.price_text.strip()
    return f"price: {stated}" if stated else "price not listed"


# What did not make the listing, and why. Silence here would read as "that is
# everything there is", which is the failure this whole path exists to end.
def _dropped_line(extraction: Extraction, over_limit: int) -> str:
    parts: list[str] = []
    if extraction.undated:
        parts.append(f"{extraction.undated} more that never said when")
    if extraction.opening_hours:
        parts.append(
            f"{extraction.opening_hours} where the only time given was the venue's opening hours"
        )
    if extraction.unsourced:
        parts.append(f"{extraction.unsourced} I could not trace back to a page")
    if over_limit > 0:
        parts.append(f"{over_limit} further down the list")
    if not parts:
        return ""
    return "Not listed: " + "; ".join(parts) + ". Say the word and I'll dig into any of them."


# The listing with nothing in it - said out loud, because an empty answer that
# looks like a shrug is indistinguishable from a broken search.
def render_nothing_found(extraction: Extraction) -> str:
    tail = _dropped_line(extraction, 0)
    if tail:
        return "Nothing I can date from what came back. " + tail
    return ""
