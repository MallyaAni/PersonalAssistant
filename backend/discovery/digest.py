"""Render a sweep into the message a person actually reads.

Assembled from typed records rather than generated, for one specific reason:
feed text is untrusted, and this string leaves the machine. A model asked to
"write a friendly summary" of hostile input can be steered by that input into
writing whatever the input wants — and here the output is delivered to third
parties over a channel that cannot be unsent.

So the shape is fixed and only bounded field values vary.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from backend.discovery.relevance import RankedCandidate

# What one message may carry. A digest longer than this is not read.
MAX_EVENTS_IN_MESSAGE = 5
MAX_TITLE_CHARS = 90
MAX_PLACE_CHARS = 60
MAX_SUMMARY_CHARS = 170


# One line per event, in the recipient's own words as far as possible: what,
# when, where. The calendar link is what makes it actionable.
def render_message(
    selected: tuple[RankedCandidate, ...],
    calendar_base_url: str | None,
    timezone: str = "America/New_York",
    limit: int = MAX_EVENTS_IN_MESSAGE,
    notable: tuple[RankedCandidate, ...] = (),
) -> str | None:
    """Return the digest text, or None when there is nothing worth sending."""
    if not selected and not notable:
        # Silence is a valid outcome. Sending "nothing this week" every week is
        # how a proactive assistant trains people to ignore it.
        return None

    zone = _zone(timezone)
    dated = [item for item in selected if item.event.starts_at is not None]
    undated = [item for item in selected if item.event.starts_at is None]

    lines = _render_dated(dated, calendar_base_url, zone, limit)
    mentions = _render_undated(undated)
    if lines and mentions:
        lines.append("")
    lines.extend(mentions)

    return "\n".join(lines) if lines else None


def _render_dated(
    dated: list[RankedCandidate],
    calendar_base_url: str | None,
    zone: ZoneInfo,
    limit: int,
) -> list[str]:
    if not dated:
        return []
    heading = (
        "Coming up near you:"
        if calendar_base_url
        else "Coming up near you — the calendar file is attached:"
    )
    lines = [heading, ""]
    for item in dated[:limit]:
        event = item.event
        line = f"• {_bound(event.title, MAX_TITLE_CHARS)}"
        when = _format_when(event.starts_at, zone)
        if when:
            line += f" — {when}"
        if event.place:
            line += f" ({_bound(event.place, MAX_PLACE_CHARS)})"
        lines.append(line)
        # What the thing actually is. Without it a recipient is deciding from a
        # title alone, which is how you get ignored.
        if event.summary:
            lines.append(f"  {_bound(event.summary, MAX_SUMMARY_CHARS)}")
        # No link when the calendar file travels with the message: the
        # attachment is what the recipient taps, and a link would be the one
        # that only resolves on the sender's network.
        if calendar_base_url:
            lines.append(f"  Add: {_calendar_url(calendar_base_url, item)}")
    remaining = len(dated) - limit
    if remaining > 0:
        lines.extend(["", f"and {remaining} more"])
    return lines


# Found without a published date. These carry a link rather than a calendar
# entry: nobody stated when they happen, and inventing a time would put a
# confidently wrong appointment in someone's calendar.
def _render_undated(undated: list[RankedCandidate]) -> list[str]:
    if not undated:
        return []
    lines = ["Worth a look — no date given:", ""]
    for item in undated:
        lines.append(f"• {_bound(item.event.title, MAX_TITLE_CHARS)}")
        if item.event.summary:
            lines.append(f"  {_bound(item.event.summary, MAX_SUMMARY_CHARS)}")
        if item.event.url:
            lines.append(f"  {item.event.url}")
    return lines


# A local, human reading of the start. Rendered in the recipient's zone rather
# than UTC, since a message saying 03:00 for a 22:00 concert is worse than no
# time at all. Built from parts because the platform-specific strftime flags for
# unpadded numbers differ between Windows and Linux.
def _format_when(starts_at: datetime | None, zone: ZoneInfo) -> str | None:
    if starts_at is None:
        return None
    local = starts_at.astimezone(zone)
    hour = local.hour % 12 or 12
    meridiem = "am" if local.hour < 12 else "pm"
    clock = f"{hour}:{local.minute:02d}{meridiem}"
    return f"{local.strftime('%a %b')} {local.day}, {clock}"


def _calendar_url(base: str, item: RankedCandidate) -> str:
    return f"{base.rstrip('/')}/{item.candidate.digest}.ics"


def _bound(value: str, limit: int) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


# An unknown zone falls back to UTC rather than failing the delivery. A digest
# with a slightly wrong clock still beats one that never arrives.
def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")
