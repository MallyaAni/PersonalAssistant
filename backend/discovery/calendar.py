"""Turn one selected event into a valid single-`VEVENT` iCalendar file.

iOS adds a `.ics` natively from a link or an attachment, so one artifact
satisfies every transport without CalDAV, an Apple developer account, or write
access to the user's calendar.

This is written against RFC 5545 rather than formatted from a template, because
the failure mode is silent: a calendar client that dislikes a file usually
declines to import it without explaining why, and a file it accepts but
misreads produces an appointment at the wrong time. The rules that matter here
are escaping, line folding, UTC normalization, and a stable UID.
"""

import hashlib
from datetime import UTC, datetime, timedelta

from backend.discovery.events import DiscoveredEvent

# RFC 5545 fixes lines at 75 octets, continued by CRLF and one leading space.
MAX_LINE_OCTETS = 75

# The default an entry gets when a feed states no end. Better than emitting an
# instant, which some clients render as a zero-length sliver.
DEFAULT_DURATION_MINUTES = 60

PRODUCT_ID = "-//AniOS//Ambient Discovery//EN"


# Escape the characters RFC 5545 reserves inside a TEXT value. Order matters:
# backslash first, or the escapes introduced below get escaped again.
def escape_text(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    escaped = escaped.replace(";", "\\;")
    escaped = escaped.replace(",", "\\,")
    escaped = escaped.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    return escaped


# Fold to 75 octets, counting bytes rather than characters so a multi-byte
# character is never split across the boundary and corrupted.
def fold_line(line: str) -> str:
    encoded = line.encode("utf-8")
    if len(encoded) <= MAX_LINE_OCTETS:
        return line
    chunks: list[str] = []
    current = bytearray()
    limit = MAX_LINE_OCTETS
    for character in line:
        raw = character.encode("utf-8")
        if len(current) + len(raw) > limit:
            chunks.append(current.decode("utf-8"))
            current = bytearray()
            # Continuation lines carry a leading space that is not content, so
            # they hold one octet less.
            limit = MAX_LINE_OCTETS - 1
        current.extend(raw)
    if current:
        chunks.append(current.decode("utf-8"))
    return "\r\n ".join(chunks)


# Emit UTC. A feed's zone is not guaranteed to name an IANA zone the client
# knows, and an entry that is right everywhere beats one that is right only
# where a VTIMEZONE block happens to be understood.
def format_utc(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("Calendar timestamps must be timezone-aware.")
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


# A UID must be stable across regenerations of the same event, so re-importing
# updates the existing appointment instead of creating a second one.
def event_uid(event: DiscoveredEvent) -> str:
    payload = f"{event.source_id}\x1f{event.external_id}".encode()
    return f"{hashlib.sha256(payload).hexdigest()[:32]}@anios.local"


def build_vevent(
    event: DiscoveredEvent,
    now: datetime | None = None,
) -> str:
    """Render one event as a complete VCALENDAR containing a single VEVENT."""
    return build_calendar((event,), now=now)


def build_calendar(
    events: tuple[DiscoveredEvent, ...],
    now: datetime | None = None,
    calendar_name: str | None = None,
) -> str:
    """Render one or more events as a single VCALENDAR.

    A collection is what a calendar client subscribes to: it re-reads the whole
    document and reconciles by UID, so an event that disappears from this
    output disappears from the subscriber's calendar. That is why UIDs are
    stable rather than regenerated per render.
    """
    schedulable = tuple(item for item in events if item.starts_at is not None)
    if not schedulable:
        raise ValueError("An event without a start cannot become a calendar entry.")

    stamp = now or datetime.now(UTC)
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODUCT_ID}",
        "CALSCALE:GREGORIAN",
        # PUBLISH marks this as information, not an invitation needing a reply.
        # An invitation would need ORGANIZER and ATTENDEE, which would make this
        # file carry the identities of everyone it reached.
        "METHOD:PUBLISH",
    ]
    if calendar_name:
        # Both spellings exist in the wild; Apple reads X-WR-CALNAME.
        lines.append(f"X-WR-CALNAME:{escape_text(calendar_name)}")
        lines.append(f"NAME:{escape_text(calendar_name)}")
    for event in schedulable:
        lines.extend(_vevent_lines(event, stamp))
    lines.append("END:VCALENDAR")

    return "\r\n".join(fold_line(line) for line in lines) + "\r\n"


def _vevent_lines(event: DiscoveredEvent, stamp: datetime) -> list[str]:
    starts_at = event.starts_at
    if starts_at is None:  # pragma: no cover - guarded by the caller
        raise ValueError("An event without a start cannot become a calendar entry.")
    ends_at = event.ends_at
    if ends_at is None or ends_at <= starts_at:
        ends_at = starts_at + timedelta(minutes=DEFAULT_DURATION_MINUTES)

    lines = [
        "BEGIN:VEVENT",
        f"UID:{event_uid(event)}",
        f"DTSTAMP:{format_utc(stamp)}",
        f"DTSTART:{format_utc(starts_at)}",
        f"DTEND:{format_utc(ends_at)}",
        f"SUMMARY:{escape_text(event.title)}",
    ]
    if event.place:
        lines.append(f"LOCATION:{escape_text(event.place)}")
    # URI values are not TEXT and must not be escaped, but a comma or semicolon
    # inside one would still break parsing, so such a URL is dropped rather than
    # emitted broken.
    if event.url and not any(character in event.url for character in ",;"):
        lines.append(f"URL:{event.url}")
    description = _description(event)
    if description:
        lines.append(f"DESCRIPTION:{escape_text(description)}")
    lines.append("END:VEVENT")
    return lines


# A filename a phone will show sensibly. Restricted to characters that survive
# every transport, and never empty.
def calendar_filename(event: DiscoveredEvent) -> str:
    safe = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in event.title.strip()
    )
    collapsed = "-".join(part for part in safe.split("-") if part)
    return f"{collapsed[:60] or 'event'}.ics"


def _description(event: DiscoveredEvent) -> str | None:
    parts: list[str] = []
    if event.summary:
        parts.append(event.summary)
    if event.url:
        parts.append(event.url)
    if not parts:
        return None
    return "\n\n".join(parts)
