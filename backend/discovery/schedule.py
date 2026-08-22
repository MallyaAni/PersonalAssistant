"""When a discovery run is due, computed in the user's own timezone.

Cadence is deliberately slow. Venue and social schedules publish ahead of time,
so a weekly sweep loses nothing a continuous one would catch while keeping the
whole feature inside the free tiers the project commits to.

The slot a run belongs to is part of its identity: a schedule produces at most
one run per slot, which is what stops a restarted producer from queueing the
same sweep twice.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CADENCES = ("daily", "weekly", "weekdays", "once")
MIN_HOUR = 0
MAX_HOUR = 23
# Monday is 0, matching datetime.weekday().
MIN_WEEKDAY = 0
MAX_WEEKDAY = 6
MIN_MINUTE = 0
MAX_MINUTE = 59


@dataclass(frozen=True, slots=True)
class Cadence:
    """How often a user wants a sweep, expressed in their local time."""

    cadence: str
    hour: int
    weekday: int
    timezone: str
    # Minutes past the hour. Any value is accepted rather than only quarters:
    # the interface offers quarter hours, and a stricter domain would reject a
    # schedule someone had already set through the API.
    minute: int = 0
    # The calendar day of a one-time run. Only `once` reads it; every other
    # cadence repeats and has no single day.
    on_date: date | None = None

    def __post_init__(self) -> None:
        if self.cadence not in CADENCES:
            raise ValueError(f"Unsupported cadence: {self.cadence}")
        if not MIN_HOUR <= self.hour <= MAX_HOUR:
            raise ValueError("Hour must be between 0 and 23.")
        if not MIN_MINUTE <= self.minute <= MAX_MINUTE:
            raise ValueError("Minute must be between 0 and 59.")
        if not MIN_WEEKDAY <= self.weekday <= MAX_WEEKDAY:
            raise ValueError("Weekday must be between 0 (Monday) and 6.")
        if self.cadence == "once" and self.on_date is None:
            raise ValueError("A one-time schedule needs its day.")


# Resolve the next slot strictly after `after`. Strictly, so completing a run
# cannot immediately re-arm the same slot and spin.
def next_run_at(cadence: Cadence, after: datetime) -> datetime:
    zone = _zone(cadence.timezone)
    local = after.astimezone(zone)
    candidate = _at_time(local, cadence, zone)

    if cadence.cadence == "once":
        # A single instant, stated by the person; it is what it is even when
        # it has passed, and the caller decides what a past one means.
        moment = datetime.combine(
            cadence.on_date, time(hour=cadence.hour, minute=cadence.minute), tzinfo=zone
        )
        return moment.astimezone(after.tzinfo or zone)

    if cadence.cadence == "daily":
        while candidate <= local:
            candidate = _at_time(candidate + timedelta(days=1), cadence, zone)
        return candidate.astimezone(after.tzinfo or zone)

    if cadence.cadence == "weekdays":
        # Monday to Friday: the next weekday slot strictly after `after`.
        while candidate <= local or candidate.weekday() > 4:
            candidate = _at_time(candidate + timedelta(days=1), cadence, zone)
        return candidate.astimezone(after.tzinfo or zone)

    # Weekly: move to the requested weekday, then forward until it is future.
    days_ahead = (cadence.weekday - candidate.weekday()) % 7
    candidate = _at_time(candidate + timedelta(days=days_ahead), cadence, zone)
    while candidate <= local:
        candidate = _at_time(candidate + timedelta(days=7), cadence, zone)
    return candidate.astimezone(after.tzinfo or zone)


# Rebuild the instant from local calendar fields so a daylight-saving shift
# moves the wall-clock time correctly instead of drifting by the old offset.
def _at_time(moment: datetime, cadence: "Cadence", zone: ZoneInfo) -> datetime:
    return datetime.combine(
        moment.date(), time(hour=cadence.hour, minute=cadence.minute), tzinfo=zone
    )


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown timezone: {name}") from exc
