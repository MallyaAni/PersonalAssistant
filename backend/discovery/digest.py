"""Render a sweep into the message a person actually reads.

Assembled from typed records rather than generated, for one specific reason:
feed text is untrusted, and this string leaves the machine. A model asked to
"write a friendly summary" of hostile input can be steered by that input into
writing whatever the input wants — and here the output is delivered to third
parties over a channel that cannot be unsent.

So the shape is fixed and only bounded field values vary.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from backend.discovery.relevance import RankedCandidate

# What one message may carry. A digest longer than this is not read.
MAX_EVENTS_IN_MESSAGE = 5
MAX_TITLE_CHARS = 90
MAX_PLACE_CHARS = 60
MAX_SUMMARY_CHARS = 170


# One entry per find: what it is, when, where, and a link when the source gave
# one. No calendar file and no calendar link — a message is read on a phone in a
# few seconds, and an attachment nobody asked for is friction rather than help.
#
# `calendar_base_url` is accepted and ignored so existing callers keep working;
# it is removed once none pass it.
def render_message(
    selected: tuple[RankedCandidate, ...],
    calendar_base_url: str | None = None,
    timezone: str = "America/New_York",
    limit: int = MAX_EVENTS_IN_MESSAGE,
    notable: tuple[RankedCandidate, ...] = (),
    now: datetime | None = None,
) -> str | None:
    """Return the digest text, or None when there is nothing worth sending."""
    zone = _zone(timezone)
    moment = now or datetime.now(UTC)
    # Something that already happened is worse than nothing: it is the clearest
    # possible signal that whatever sent it is not paying attention. Selection
    # already applies a lead-time window, but a digest can be rendered from a
    # stored run long after the sweep that produced it.
    selected = tuple(item for item in selected if not _has_passed(item, moment))
    notable = tuple(item for item in notable if not _has_passed(item, moment))
    if not selected and not notable:
        # Silence is a valid outcome. Sending "nothing this week" every week is
        # how a proactive assistant trains people to ignore it.
        return None

    dated = [item for item in selected if item.event.starts_at is not None]
    undated = [item for item in selected if item.event.starts_at is None]

    lines = _render_dated(dated, zone, limit)
    mentions = _render_undated(undated)
    if lines and mentions:
        lines.append("")
    lines.extend(mentions)

    return "\n".join(lines) if lines else None


# Whether this find is already in the past. An undated find cannot have passed:
# nobody said when it happens, so it is a standing thing rather than a missed
# one.
def _has_passed(item: RankedCandidate, moment: datetime) -> bool:
    starts_at = item.event.starts_at
    return starts_at is not None and starts_at < moment


def _render_dated(
    dated: list[RankedCandidate],
    zone: ZoneInfo,
    limit: int,
) -> list[str]:
    if not dated:
        return []
    lines = ["Coming up near you:", ""]
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
        # The source's own link, which works from anywhere. Not every find has
        # one — a trail or a park is a place rather than a page — and a line
        # saying nothing is worse than no line.
        if event.url:
            lines.append(f"  {event.url}")
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
    heading = (
        "I found this, but couldn't confirm the date:"
        if len(undated) == 1
        else "I found a few possibilities, but couldn't confirm their dates:"
    )
    lines = [heading, ""]
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
