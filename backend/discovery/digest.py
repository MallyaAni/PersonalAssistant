"""Render a sweep into the message a person actually reads.

Two paths, and which one runs depends only on whether there is a model.

**Written.** `agents/scout/digesting.py` composes the greeting and one line per
find, and this module supplies the facts and attaches the links. That is where
the prose comes from now, because an assembled digest opened with the same six
words every week and read like a form letter — which earns a form letter's
attention.

**Assembled.** Everything below, unchanged, for when there is no model. It is
worse to read and impossible to subvert, and a digest that arrives beats one
that does not.

What stays in code either way is what a 4B model must not be trusted with. The
clock is the sharp one: `_format_when` distinguishes a date the source stated
with no time from a real start, after a concert listed for Oct 3 was announced
as "Fri Oct 2, 8:00pm" — a date shifted into a zone it was never in. The written
path renders that string here and requires it back verbatim. Links come from the
typed record on both paths and are never asked of the model.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from backend.agents.scout.digesting import DigestWriter, Find
from backend.discovery.relevance import RankedCandidate

# How many finds one digest sends.
#
# Five. The whole week's shortlist goes to the phone, because the phone is where
# this is read: a find held back to keep the thread quiet is a find nobody sees,
# and there is no second place the reader was ever going to look for it.
#
# It sits at the top of what sweeps actually produce — across thirteen real runs
# the finds reaching a digest ran one to five — so in practice everything that
# qualifies is sent, and the bound only guards against an unusually busy week.
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
@dataclass(frozen=True, slots=True)
class Bubble:
    """One message to send, and the find it is about.

    The greeting is a bubble with no find: it carries no identity and draws no
    useful reaction, but it arrives first and says what this is.
    """

    text: str
    item_digest: str | None = None
    label: str | None = None


# Split a digest into the messages it should be sent as, one per find.
#
# A tapback attaches to a bubble, so this is what makes per-find feedback
# possible at all: sent as one message, a digest can only be rated as a whole.
# The cost is real and is the reason this is a separate function rather than the
# only way — five notifications instead of one.
async def write_bubbles(
    selected: tuple[RankedCandidate, ...],
    writer: DigestWriter | None = None,
    timezone: str = "America/New_York",
    limit: int = MAX_EVENTS_IN_MESSAGE,
    now: datetime | None = None,
) -> tuple[Bubble, ...]:
    zone = _zone(timezone)
    moment = now or datetime.now(UTC)
    live = tuple(item for item in selected if not _has_passed(item, moment))
    if not live:
        return ()
    kept = list(live)[:limit]
    finds = tuple(
        Find(
            index=position,
            name=" ".join(item.event.title.split()),
            description=item.event.summary,
            when=_format_when(item.event.starts_at, zone),
            place=item.event.place or None,
        )
        for position, item in enumerate(kept)
    )
    written = None if writer is None else await writer.write(finds)
    if written is None:
        # No model. Each find still gets its own bubble, because the feedback
        # this exists for must not depend on the runtime being up.
        bubbles = [
            Bubble(
                text=_assembled_bubble(item, zone),
                item_digest=item.candidate.digest,
                label=item.event.title,
            )
            for item in kept
        ]
        return tuple(bubbles)

    # Written lines by find, so a find the model skipped can be noticed rather
    # than quietly lost. Asked for five, it returned three on a real digest and
    # "Sounds of Summer" and "Seven Wonders at Tarara Winery" simply never
    # arrived — a shorter digest with nothing anywhere saying it was shorter.
    written_by_index = {line.index: line.text for line in written.lines}

    bubbles = [Bubble(text=written.greeting)]
    for position, item in enumerate(kept):
        # The model's words where it wrote them, the assembled line where it did
        # not. Which finds are sent is not the model's decision to make: it was
        # given the ones that qualified, and its job is wording, not selection.
        text = written_by_index.get(position) or _assembled_bubble(item, zone)
        # The source's own link, from the typed record, never from the model.
        if item.event.url and item.event.url not in text:
            text = f"{text}\n{item.event.url}"
        bubbles.append(
            Bubble(
                text=text,
                item_digest=item.candidate.digest,
                label=item.event.title,
            )
        )
    return tuple(bubbles)


# One find as its own message when there is no model to word it.
def _assembled_bubble(item: RankedCandidate, zone: ZoneInfo) -> str:
    event = item.event
    line = _bound(event.title, MAX_TITLE_CHARS)
    when = _format_when(event.starts_at, zone)
    if when:
        line += f" — {when}"
    if event.place:
        line += f" ({_bound(event.place, MAX_PLACE_CHARS)})"
    parts = [line]
    if event.summary:
        parts.append(_bound(event.summary, MAX_SUMMARY_CHARS))
    if event.url:
        parts.append(event.url)
    return "\n".join(parts)


async def write_message(
    selected: tuple[RankedCandidate, ...],
    writer: DigestWriter | None = None,
    timezone: str = "America/New_York",
    limit: int = MAX_EVENTS_IN_MESSAGE,
    now: datetime | None = None,
) -> str | None:
    """Return the digest text, written by the model where one is available."""
    zone = _zone(timezone)
    moment = now or datetime.now(UTC)
    live = tuple(item for item in selected if not _has_passed(item, moment))
    if not live:
        return None
    if writer is None:
        return render_message(selected, timezone=timezone, limit=limit, now=now)

    # The facts, rendered here because the clock is not the model's to compute.
    kept = list(live)[:limit]
    finds = tuple(
        Find(
            index=position,
            name=" ".join(item.event.title.split()),
            description=item.event.summary,
            when=_format_when(item.event.starts_at, zone),
            place=item.event.place or None,
        )
        for position, item in enumerate(kept)
    )
    written = await writer.write(finds)
    if written is None:
        # No model answer. The assembled shape is worse to read and always
        # arrives, which is the right way round for a weekly message.
        return render_message(selected, timezone=timezone, limit=limit, now=now)

    lines = [written.greeting, ""]
    for line in written.lines:
        item = kept[line.index]
        lines.append(f"• {line.text}")
        # The source's own link, from the typed record, never from the model.
        # Not every find has one — a trail or a park is a place rather than a
        # page — and a line saying nothing is worse than no line.
        if item.event.url:
            lines.append(f"  {item.event.url}")
        lines.append("")
    remaining = len(live) - len(written.lines)
    if remaining > 0:
        lines.append(f"and {remaining} more")
    return "\n".join(lines).strip()


def render_message(
    selected: tuple[RankedCandidate, ...],
    calendar_base_url: str | None = None,
    timezone: str = "America/New_York",
    limit: int = MAX_EVENTS_IN_MESSAGE,
    notable: tuple[RankedCandidate, ...] = (),
    now: datetime | None = None,
) -> str | None:
    """Return the assembled digest text, for when there is no model."""
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
    if not lines:
        return None

    # An opening, so the message reads as something sent on purpose.
    #
    # Without one a digest of undated finds began "I found a few possibilities,
    # but couldn't confirm their dates:" — a caveat as the first thing anyone
    # sees, from a number they may not recognize, with no indication of what it
    # is or why it arrived. Fixed wording rather than written each time: this is
    # the same sentence every day, and a model composing it afresh would vary it
    # for no reason and could vary it into something wrong.
    return "\n".join([_greeting(moment, zone), ""] + lines)


# "Scout · Saturday morning" — who it is from and when it was put together.
def _greeting(moment: datetime, zone: ZoneInfo) -> str:
    local = moment.astimezone(zone)
    if local.hour < 12:
        part = "morning"
    elif local.hour < 17:
        part = "afternoon"
    else:
        part = "evening"
    return f"Scout · {local.strftime('%A')} {part}"


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
    if _is_date_only(starts_at):
        # A date the source stated with no time, which is most of them. Shifting
        # it into the reader's zone moves it to the previous evening and prints
        # a clock nobody published: a concert listed for Oct 3 was announced as
        # "Fri Oct 2, 8:00pm", one line below a title that said Oct 03, 9:30 PM.
        # The date is what was known, so the date is all that is said.
        stated = starts_at.astimezone(UTC)
        return f"{stated.strftime('%a %b')} {stated.day}"
    local = starts_at.astimezone(zone)
    hour = local.hour % 12 or 12
    meridiem = "am" if local.hour < 12 else "pm"
    clock = f"{hour}:{local.minute:02d}{meridiem}"
    return f"{local.strftime('%a %b')} {local.day}, {clock}"


# Whether a start carries only a date.
#
# Midnight UTC exactly is what a date-only value becomes once parsed — schema.org
# `"startDate": "2026-10-03"` and an ICS `VALUE=DATE` both land here. A real
# happening beginning at 00:00:00 UTC to the second is rare enough that reading
# one as date-only costs a time nobody would have trusted anyway, while the
# reverse invents one for every find that never had a time at all.
def _is_date_only(starts_at: datetime) -> bool:
    stated = starts_at.astimezone(UTC)
    return (stated.hour, stated.minute, stated.second) == (0, 0, 0)


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
