"""Grounded links for typed events, built by code.

The listing used to inline a row of links under every event, and a weekend
answer was forty links before any content. They are now sent on request: the
listing ends by offering them, and this module builds them for the events the
person names. Same builders, same fence, called later.

Every address here is one code can honestly construct - search boxes, not
destinations - or a source URL some page actually stated.
"""

from __future__ import annotations

from backend.core.event_extraction import ListedEvent
from backend.core.links import calendar_link, ics_link, maps_search, youtube_search


# The grounded link row for one event, as markdown. The calendar base decides
# whether the native "Add to iMessage calendar" link is offered, exactly as it
# did when these lived inline in the listing.
def event_link_lines(
    event: ListedEvent, calendar_base_url: str | None = None
) -> list[str]:
    subject = " ".join(part for part in (event.venue, event.area) if part)
    lines = [f"[Map]({maps_search(subject)})"]
    lines.append(
        f"[Calendar]({calendar_link(event.name, event.starts_at, location=subject)})"
    )
    if calendar_base_url:
        ics = ics_link(
            calendar_base_url, event.name, event.starts_at, location=subject
        )
        lines.append(f"[Add to iMessage calendar]({ics})")
    if event.artist:
        lines.append(f"[Hear it]({youtube_search(event.artist)})")
    if event.source_url:
        lines.append(f"[Details]({event.source_url})")
    return lines


# The whole follow-up message for the chosen events, as one block the reply
# relays verbatim. Each event leads with its line and carries its link row,
# so the person sees at a glance which thing each link belongs to.
def render_links_for(
    events: list[ListedEvent], calendar_base_url: str | None = None
) -> str:
    blocks: list[str] = []
    for event in events:
        headline = event.name
        if event.artist and event.artist.casefold() not in event.name.casefold():
            headline = f"{headline} — {event.artist}"
        where = ", ".join(part for part in (event.venue, event.area) if part)
        lines = [f"• {headline}"]
        if where:
            lines.append(f"  {where}")
        links = ", ".join(event_link_lines(event, calendar_base_url))
        lines.append(f"  {links}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
