"""Read venue calendars published as iCalendar (RFC 5545).

Parsed with the standard library rather than a calendar package. Only a handful
of properties are needed, the grammar for those is small and stable, and doing
it here keeps every bound and every sanitization step visible at the boundary
where untrusted feed text enters. The parser is deliberately lenient about what
it ignores and strict about what it accepts.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.discovery.events import (
    MAX_EVENTS_PER_SOURCE,
    MAX_PLACE_CHARS,
    MAX_SUMMARY_CHARS,
    MAX_TITLE_CHARS,
    DiscoveredEvent,
    EventSource,
    clean_text,
    clean_title,
    clean_url,
    event_has_passed,
    is_date_only,
)
from backend.discovery.fetching import RequestBudget, fetch_feed
from backend.discovery.relevance import MAX_LEAD_DAYS

# A folded line continues when the next one begins with a space or tab.
_FOLD = re.compile(r"\r?\n[ \t]")
# TEXT values escape these. Applied by a single left-to-right scan rather than
# chained replacements, so an escaped backslash before a comma stays a literal
# backslash instead of being re-read as an escaped comma.
_ESCAPES = {"n": "\n", "N": "\n", ",": ",", ";": ";", "\\": "\\"}

# A recurring entry expands into its upcoming occurrences. The sweep only looks
# MAX_LEAD_DAYS ahead, so expanding further would create candidates no digest
# can use; the per-entry cap keeps one long series from consuming the source's
# whole allowance.
MAX_OCCURRENCES_PER_EVENT = 60
# An ancient series or a malformed rule must not make parsing unbounded.
MAX_RECURRENCE_STEPS = 2_000

_WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_BYDAY_TOKEN = re.compile(r"^([+-]?\d+)?(MO|TU|WE|TH|FR|SA|SU)$")


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


# The content lines of one VEVENT, grouped by what the parser does with them.
# RDATE, EXDATE and RECURRENCE-ID may legally repeat, so they are kept as lists
# rather than folded into the first-occurrence-wins field map.
@dataclass(frozen=True, slots=True)
class _Properties:
    fields: dict[str, tuple[dict[str, str], str]]
    attachments: list[tuple[str, dict[str, str], str]]
    rdates: list[tuple[dict[str, str], str]]
    exdates: list[tuple[dict[str, str], str]]
    recurrence_id: tuple[dict[str, str], str] | None


# Turn one calendar document into bounded, normalized events. Pure so the
# format's edge cases can be tested without touching the network.
def parse_ics(
    payload: str,
    source_id: str,
    default_timezone: str = "UTC",
    now: datetime | None = None,
) -> tuple[DiscoveredEvent, ...]:
    fallback = _zone(default_timezone) or UTC
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    # A series that began yesterday and is still running is actionable; anything
    # that ended before then is not.
    window_start = moment - timedelta(days=1)
    window_end = moment + timedelta(days=MAX_LEAD_DAYS)
    blocks = _vevent_blocks(payload)
    overrides = _overrides(blocks, fallback)
    events: list[DiscoveredEvent] = []
    for block in blocks:
        for event in _build_events(
            _properties(block),
            source_id,
            fallback,
            window_start,
            window_end,
            overrides,
        ):
            events.append(event)
            if len(events) >= MAX_EVENTS_PER_SOURCE:
                return tuple(events)
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


# Split one block's lines into the properties the builder reads.
def _properties(lines: list[str]) -> _Properties:
    fields: dict[str, tuple[dict[str, str], str]] = {}
    # Attachments are collected separately because a calendar may carry several
    # and the first is often a PDF rather than the poster.
    attachments: list[tuple[str, dict[str, str], str]] = []
    rdates: list[tuple[dict[str, str], str]] = []
    exdates: list[tuple[dict[str, str], str]] = []
    recurrence_id: tuple[dict[str, str], str] | None = None
    for line in lines:
        parsed = _content_line(line)
        if parsed is None:
            continue
        name, params, value = parsed
        if name in ("ATTACH", "IMAGE"):
            attachments.append((name, params, value))
        elif name == "RDATE":
            rdates.append((params, value))
        elif name == "EXDATE":
            exdates.append((params, value))
        elif name == "RECURRENCE-ID":
            recurrence_id = recurrence_id or (params, value)
        else:
            # First occurrence wins; a repeated property is not merged.
            fields.setdefault(name, (params, value))
    return _Properties(fields, attachments, rdates, exdates, recurrence_id)


# The occurrences a calendar replaces with a RECURRENCE-ID entry, keyed by UID,
# so the master series does not also offer the slot the override replaced.
def _overrides(
    blocks: list[list[str]],
    fallback: timezone | ZoneInfo,
) -> dict[str, set[datetime]]:
    overrides: dict[str, set[datetime]] = {}
    for block in blocks:
        properties = _properties(block)
        uid = clean_text(_value(properties.fields, "UID"), MAX_TITLE_CHARS)
        if uid is None or properties.recurrence_id is None:
            continue
        replaced = _timestamp(properties.recurrence_id, fallback)
        if replaced is not None:
            overrides.setdefault(uid, set()).add(replaced)
    return overrides


# Build the one event a block states, or the upcoming occurrences its recurrence
# rules define. Expansion is bounded by the sweep's own lead time so a feed
# cannot turn one weekly series into a year of candidates.
def _build_events(
    properties: _Properties,
    source_id: str,
    fallback: timezone | ZoneInfo,
    window_start: datetime,
    window_end: datetime,
    overrides: dict[str, set[datetime]],
) -> list[DiscoveredEvent]:
    fields = properties.fields
    title = clean_title(_value(fields, "SUMMARY"), MAX_TITLE_CHARS)
    if title is None:
        # A listing with no title cannot be shown to anyone usefully.
        return []

    starts_at = _timestamp(fields.get("DTSTART"), fallback)
    ends_at = _timestamp(fields.get("DTEND"), fallback)
    uid = clean_text(_value(fields, "UID"), MAX_TITLE_CHARS)
    # An identifier is what stage 4 deduplicates on. Without a UID, fall back to
    # the title and start so a stable event still resolves to a stable identity.
    base_id = uid or f"{title}|{starts_at.isoformat() if starts_at else 'undated'}"
    place = clean_text(_value(fields, "LOCATION"), MAX_PLACE_CHARS)
    url = clean_url(_value(fields, "URL"))
    summary = clean_text(_value(fields, "DESCRIPTION"), MAX_SUMMARY_CHARS)
    media_url = _image_url(properties.attachments)

    def event(
        identity: str,
        start: datetime | None,
        end: datetime | None,
    ) -> DiscoveredEvent:
        return DiscoveredEvent(
            source_id=source_id,
            external_id=identity,
            title=title,
            starts_at=start,
            ends_at=end,
            place=place,
            url=url,
            summary=summary,
            media_url=media_url,
        )

    # An override states one replaced occurrence; it is not itself a series.
    if properties.recurrence_id is not None:
        replaced = _timestamp(properties.recurrence_id, fallback)
        identity = base_id if replaced is None else f"{base_id}|{replaced.isoformat()}"
        return [event(identity, starts_at, ends_at)]

    rule = _parse_rrule(_value(fields, "RRULE"))
    if rule is None and not properties.rdates:
        return [event(base_id, starts_at, ends_at)]
    if starts_at is None:
        # A rule without a start cannot be placed on a timeline; keep the entry
        # as the undated listing it is rather than inventing one.
        return [event(base_id, None, None)]

    duration = None
    if ends_at is not None and ends_at > starts_at:
        if is_date_only(starts_at) and is_date_only(ends_at):
            # An all-day event's length is a number of calendar days. The
            # absolute difference across a daylight-saving change is 23 or 25
            # hours, and carrying that onto later occurrences would move their
            # midnight to 11pm or 1am.
            duration = timedelta(days=(ends_at.date() - starts_at.date()).days)
        else:
            duration = ends_at - starts_at
    excluded = set(_listed_times(properties.exdates, fallback))
    excluded.update(overrides.get(uid or "", set()))
    occurrences = _rule_occurrences(starts_at, rule) if rule is not None else []
    occurrences.extend(_listed_times(properties.rdates, fallback))
    upcoming = sorted(
        occurrence
        for occurrence in set(occurrences)
        if occurrence not in excluded
        and not event_has_passed(
            occurrence,
            occurrence + duration if duration is not None else None,
            window_start,
        )
        and occurrence <= window_end
    )[:MAX_OCCURRENCES_PER_EVENT]

    # The first occurrence keeps the bare identifier so an event announced
    # before expansion existed is not announced again under a new one.
    def identity(occurrence: datetime) -> str:
        if uid is None:
            return f"{title}|{occurrence.isoformat()}"
        return uid if occurrence == starts_at else f"{uid}|{occurrence.isoformat()}"

    return [
        event(
            identity(occurrence),
            occurrence,
            occurrence + duration if duration is not None else None,
        )
        for occurrence in upcoming
    ]


# Parse the supported RRULE subset. None means the entry is a single event,
# which is also what an unknown frequency degrades to rather than being dropped.
def _parse_rrule(value: str | None) -> dict[str, str] | None:
    if not value:
        return None
    rule: dict[str, str] = {}
    for part in value.split(";"):
        key, separator, raw = part.partition("=")
        if separator and key.strip():
            rule[key.strip().upper()] = raw.strip().upper()
    if rule.get("FREQ") not in {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}:
        return None
    return rule


# Expand one rule into the occurrences it defines, in order and bounded in both
# emitted occurrences and iterations. COUNT counts from DTSTART even when the
# early occurrences fall outside the window; UNTIL is inclusive.
def _rule_occurrences(  # noqa: C901 - one bounded cursor per frequency
    start: datetime, rule: dict[str, str]
) -> list[datetime]:
    frequency = rule["FREQ"]
    interval = _positive_int(rule.get("INTERVAL"), 1)
    count = _positive_int(rule.get("COUNT"), None)
    until, until_is_date = _until(rule.get("UNTIL"), start.tzinfo)
    byday = _byday(rule.get("BYDAY"))
    bymonthday = _bymonthday(rule.get("BYMONTHDAY"))
    bymonth = _bymonth(rule.get("BYMONTH"))
    weekdays = {weekday for _, weekday in byday}
    first_weekday = _WEEKDAYS.get(rule.get("WKST", "MO"), 0)

    occurrences: list[datetime] = []
    steps = 0

    def past_until(candidate: datetime) -> bool:
        if until is None:
            return False
        if until_is_date:
            return candidate.date() > until.date()
        return candidate > until

    def belongs(candidate: datetime) -> bool:
        return candidate >= start and (
            not bymonth or candidate.month in bymonth
        )

    def exhausted() -> bool:
        return count is not None and len(occurrences) >= count

    if frequency == "DAILY":
        candidate = start
        while steps < MAX_RECURRENCE_STEPS and not exhausted():
            steps += 1
            if weekdays and candidate.weekday() not in weekdays:
                candidate += timedelta(days=interval)
                continue
            if past_until(candidate):
                break
            if belongs(candidate):
                occurrences.append(candidate)
            candidate += timedelta(days=interval)

    elif frequency == "WEEKLY":
        offsets = sorted(
            (weekday - first_weekday) % 7
            for weekday in (weekdays or {start.weekday()})
        )
        week = start - timedelta(days=(start.weekday() - first_weekday) % 7)
        done = False
        while steps < MAX_RECURRENCE_STEPS and not done:
            for offset in offsets:
                steps += 1
                if steps > MAX_RECURRENCE_STEPS:
                    done = True
                    break
                candidate = week + timedelta(days=offset)
                if past_until(candidate):
                    done = True
                    break
                if belongs(candidate):
                    occurrences.append(candidate)
                    if exhausted():
                        done = True
                        break
            week += timedelta(days=7 * interval)

    elif frequency == "MONTHLY":
        month_offset = 0
        done = False
        while steps < MAX_RECURRENCE_STEPS and not done:
            steps += 1
            year, month = _shift_month(start.year, start.month, month_offset * interval)
            for day in _month_days(year, month, start, bymonthday, byday):
                steps += 1
                if steps > MAX_RECURRENCE_STEPS:
                    done = True
                    break
                candidate = _at_day(year, month, day, start)
                if past_until(candidate):
                    done = True
                    break
                if belongs(candidate):
                    occurrences.append(candidate)
                    if exhausted():
                        done = True
                        break
            month_offset += 1

    elif frequency == "YEARLY":
        year = start.year
        done = False
        months = sorted(bymonth or [start.month])
        while steps < MAX_RECURRENCE_STEPS and not done:
            steps += 1
            for month in months:
                for day in _month_days(year, month, start, bymonthday, byday):
                    steps += 1
                    if steps > MAX_RECURRENCE_STEPS:
                        done = True
                        break
                    candidate = _at_day(year, month, day, start)
                    if past_until(candidate):
                        done = True
                        break
                    if belongs(candidate):
                        occurrences.append(candidate)
                        if exhausted():
                            done = True
                            break
                if done:
                    break
            year += interval

    return occurrences


# Parse BYDAY into (ordinal or None, weekday) pairs, dropping unknown tokens.
def _byday(value: str | None) -> list[tuple[int | None, int]]:
    if not value:
        return []
    pairs: list[tuple[int | None, int]] = []
    for token in value.split(","):
        match = _BYDAY_TOKEN.match(token.strip().upper())
        if match is None:
            continue
        ordinal = int(match.group(1)) if match.group(1) else None
        if ordinal == 0:
            continue
        pairs.append((ordinal, _WEEKDAYS[match.group(2)]))
    return pairs


# Parse a comma-separated integer list, dropping zero and out-of-range values.
def _int_list(value: str | None, low: int, high: int) -> list[int]:
    numbers: list[int] = []
    for token in (value or "").split(","):
        try:
            number = int(token.strip())
        except ValueError:
            continue
        if number != 0 and low <= number <= high:
            numbers.append(number)
    return numbers


# Parse BYMONTHDAY into month days, positive or counted back from the month end.
def _bymonthday(value: str | None) -> list[int]:
    return _int_list(value, -31, 31)


# Parse BYMONTH into calendar months.
def _bymonth(value: str | None) -> list[int]:
    return _int_list(value, 1, 12)


# A rule's positive integer, or the default when the feed states none usable.
def _positive_int(value: str | None, default: int | None) -> int | None:
    try:
        number = int(value) if value is not None else 0
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


# Parse UNTIL, keeping whether it names a whole day so that day stays inclusive.
def _until(
    value: str | None,
    fallback: timezone | ZoneInfo,
) -> tuple[datetime | None, bool]:
    if not value:
        return None, False
    text = value.strip()
    is_date = len(text) == 8
    params = {"VALUE": "DATE"} if is_date else {}
    return _timestamp((params, text), fallback), is_date


# The instants an RDATE or EXDATE property lists, one content line at a time.
def _listed_times(
    entries: list[tuple[dict[str, str], str]],
    fallback: timezone | ZoneInfo,
) -> list[datetime]:
    times: list[datetime] = []
    for params, value in entries:
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            # RDATE may state a PERIOD; only its start is an occurrence.
            parsed = _timestamp((params, part.split("/", 1)[0]), fallback)
            if parsed is not None:
                times.append(parsed)
    return times


# The days in one month that a rule selects: stated month days, stated weekdays
# (with an optional ordinal), or the series' own day of the month.
def _month_days(
    year: int,
    month: int,
    start: datetime,
    bymonthday: list[int],
    byday: list[tuple[int | None, int]],
) -> list[int]:
    length = calendar.monthrange(year, month)[1]
    if bymonthday:
        days = set()
        for day in bymonthday:
            resolved = _resolve_day(year, month, day, length)
            if resolved is not None:
                days.add(resolved)
        return sorted(days)
    if byday:
        days = set()
        for ordinal, weekday in byday:
            if ordinal is None:
                days.update(
                    day
                    for day in range(1, length + 1)
                    if date(year, month, day).weekday() == weekday
                )
            else:
                resolved = _nth_weekday(year, month, ordinal, weekday, length)
                if resolved is not None:
                    days.add(resolved)
        return sorted(days)
    resolved = _resolve_day(year, month, start.day, length)
    return [resolved] if resolved is not None else []


# A positive or month-end-relative day, or None when the month is too short.
def _resolve_day(year: int, month: int, day: int, length: int) -> int | None:
    if day > 0:
        return day if day <= length else None
    resolved = length + day + 1
    return resolved if resolved >= 1 else None


# The nth weekday of a month; a negative ordinal counts back from its end.
def _nth_weekday(
    year: int,
    month: int,
    ordinal: int,
    weekday: int,
    length: int,
) -> int | None:
    if ordinal > 0:
        first = date(year, month, 1)
        day = 1 + (weekday - first.weekday()) % 7 + (ordinal - 1) * 7
        return day if day <= length else None
    last = date(year, month, length)
    day = length - (last.weekday() - weekday) % 7 + (ordinal + 1) * 7
    return day if day >= 1 else None


# Move a calendar month by a whole number of months.
def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + offset
    return index // 12, index % 12 + 1


# The occurrence on one date, at the series' stated wall-clock time.
def _at_day(year: int, month: int, day: int, start: datetime) -> datetime:
    return datetime(
        year,
        month,
        day,
        start.hour,
        start.minute,
        start.second,
        start.microsecond,
        tzinfo=start.tzinfo,
    )


# The event's poster from its attachments. RFC 7986's IMAGE property is a
# picture by definition; an ATTACH needs FMTTYPE image/* or, when untyped, an
# image file extension. A calendar commonly attaches a PDF or another .ics, so
# an untyped attachment is never assumed to be a picture.
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif")


def _image_url(attachments: list[tuple[str, dict[str, str], str]]) -> str | None:
    for name, params, value in attachments:
        candidate = clean_url(value)
        if candidate is None:
            continue
        declared = params.get("FMTTYPE", "").lower()
        path = candidate.lower().split("?", 1)[0].split("#", 1)[0]
        if name == "IMAGE" or declared.startswith("image/") or (
            not declared and path.endswith(_IMAGE_SUFFIXES)
        ):
            return candidate
    return None


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
