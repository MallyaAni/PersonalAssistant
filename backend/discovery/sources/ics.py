"""Read venue calendars published as iCalendar (RFC 5545).

Parsed with the standard library rather than a calendar package. Only a handful
of properties are needed, the grammar for those is small and stable, and doing
it here keeps every bound and every sanitization step visible at the boundary
where untrusted feed text enters. The parser is deliberately lenient about what
it ignores and strict about what it accepts.
"""

import re
from datetime import UTC, date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.discovery.events import (
    MAX_EVENTS_PER_SOURCE,
    MAX_PLACE_CHARS,
    MAX_SUMMARY_CHARS,
    MAX_TITLE_CHARS,
    DiscoveredEvent,
    EventSource,
    clean_text,
    clean_url,
)
from backend.discovery.fetching import RequestBudget, fetch_feed

# A folded line continues when the next one begins with a space or tab.
_FOLD = re.compile(r"\r?\n[ \t]")
# TEXT values escape these. Applied by a single left-to-right scan rather than
# chained replacements, so an escaped backslash before a comma stays a literal
# backslash instead of being re-read as an escaped comma.
_ESCAPES = {"n": "\n", "N": "\n", ",": ",", ";": ";", "\\": "\\"}


class IcsEventSource(EventSource):
    """One iCalendar feed of scheduled happenings."""

    def __init__(
        self,
        source_id: str,
        url: str,
        default_timezone: str = "UTC",
        budget: RequestBudget | None = None,
    ) -> None:
        self._source_id = source_id
        self.url = url
        self.default_timezone = default_timezone
        self.budget = budget

    @property
    def source_id(self) -> str:
        return self._source_id

    async def fetch(self) -> tuple[DiscoveredEvent, ...]:
        payload = await fetch_feed(self.url, budget=self.budget)
        return parse_ics(payload, self._source_id, self.default_timezone)


# Turn one calendar document into bounded, normalized events. Pure so the
# format's edge cases can be tested without touching the network.
def parse_ics(
    payload: str,
    source_id: str,
    default_timezone: str = "UTC",
) -> tuple[DiscoveredEvent, ...]:
    fallback = _zone(default_timezone) or UTC
    events: list[DiscoveredEvent] = []
    for block in _vevent_blocks(payload):
        event = _build_event(block, source_id, fallback)
        if event is not None:
            events.append(event)
        if len(events) >= MAX_EVENTS_PER_SOURCE:
            break
    return tuple(events)


# Yield each VEVENT as a list of unfolded content lines.
def _vevent_blocks(payload: str) -> list[list[str]]:
    unfolded = _FOLD.sub("", payload)
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for raw in unfolded.splitlines():
        line = raw.strip()
        if line == "BEGIN:VEVENT":
            current = []
        elif line == "END:VEVENT":
            if current is not None:
                blocks.append(current)
            current = None
        elif current is not None and line:
            current.append(line)
    return blocks


def _build_event(
    lines: list[str],
    source_id: str,
    fallback: timezone | ZoneInfo,
) -> DiscoveredEvent | None:
    fields: dict[str, tuple[dict[str, str], str]] = {}
    for line in lines:
        parsed = _content_line(line)
        if parsed is None:
            continue
        name, params, value = parsed
        # First occurrence wins; a repeated property is not merged.
        fields.setdefault(name, (params, value))

    title = clean_text(_value(fields, "SUMMARY"), MAX_TITLE_CHARS)
    if title is None:
        # A listing with no title cannot be shown to anyone usefully.
        return None

    starts_at = _timestamp(fields.get("DTSTART"), fallback)
    ends_at = _timestamp(fields.get("DTEND"), fallback)
    # An identifier is what stage 4 deduplicates on. Without a UID, fall back to
    # the title and start so a stable event still resolves to a stable identity.
    external_id = clean_text(_value(fields, "UID"), MAX_TITLE_CHARS) or (
        f"{title}|{starts_at.isoformat() if starts_at else 'undated'}"
    )

    return DiscoveredEvent(
        source_id=source_id,
        external_id=external_id,
        title=title,
        starts_at=starts_at,
        ends_at=ends_at,
        place=clean_text(_value(fields, "LOCATION"), MAX_PLACE_CHARS),
        url=clean_url(_value(fields, "URL")),
        summary=clean_text(_value(fields, "DESCRIPTION"), MAX_SUMMARY_CHARS),
    )


def _value(fields: dict[str, tuple[dict[str, str], str]], name: str) -> str | None:
    found = fields.get(name)
    return found[1] if found else None


# Split NAME;PARAM=VALUE:VALUE, honouring quoted parameter values so a colon
# inside a quoted TZID does not truncate the property.
def _content_line(line: str) -> tuple[str, dict[str, str], str] | None:
    in_quotes = False
    for index, character in enumerate(line):
        if character == '"':
            in_quotes = not in_quotes
        elif character == ":" and not in_quotes:
            head, value = line[:index], line[index + 1 :]
            break
    else:
        return None

    parts = _split_unquoted(head, ";")
    name = parts[0].strip().upper()
    if not name:
        return None
    params: dict[str, str] = {}
    for part in parts[1:]:
        key, _, raw = part.partition("=")
        params[key.strip().upper()] = raw.strip().strip('"')
    return name, params, _unescape(value)


def _split_unquoted(value: str, separator: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    in_quotes = False
    for character in value:
        if character == '"':
            in_quotes = not in_quotes
        if character == separator and not in_quotes:
            parts.append("".join(current))
            current = []
            continue
        current.append(character)
    parts.append("".join(current))
    return parts


def _unescape(value: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\\" and index + 1 < len(value):
            following = value[index + 1]
            # An unrecognized escape keeps both characters rather than silently
            # dropping the backslash and changing the author's text.
            out.append(_ESCAPES.get(following, character + following))
            index += 2
            continue
        out.append(character)
        index += 1
    return "".join(out)


# Resolve the three forms a calendar date takes: UTC with a trailing Z, a local
# time qualified by TZID, and a date-only all-day value.
def _timestamp(
    field: tuple[dict[str, str], str] | None,
    fallback: timezone | ZoneInfo,
) -> datetime | None:
    if field is None:
        return None
    params, value = field
    text = value.strip()
    if not text:
        return None

    if params.get("VALUE", "").upper() == "DATE" or len(text) == 8:
        try:
            day = date(int(text[0:4]), int(text[4:6]), int(text[6:8]))
        except ValueError:
            return None
        # An all-day entry becomes midnight in the calendar's zone so every
        # event downstream carries a comparable instant.
        return datetime.combine(day, time.min, tzinfo=fallback)

    if text.endswith("Z"):
        parsed = _naive(text[:-1])
        return parsed.replace(tzinfo=UTC) if parsed else None

    parsed = _naive(text)
    if parsed is None:
        return None
    zone = _zone(params.get("TZID", "")) or fallback
    return parsed.replace(tzinfo=zone)


def _naive(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, "%Y%m%dT%H%M%S")
    except ValueError:
        return None


def _zone(name: str) -> ZoneInfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        # An unknown zone must not fail the whole feed; the caller's default
        # applies instead.
        return None
