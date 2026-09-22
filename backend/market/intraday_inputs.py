"""Calendar and dated-input gates for the experimental entry comparison.

No cache reads, scoring, orders or production wiring. The caller must retain
unavailable opportunities rather than deleting them after these gates fail.
"""

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from backend.market.intraday_comparison import DailyRow, Eligibility
from backend.market.intraday_entry import NEW_YORK

DATA = Path(__file__).parent / "data"


# Represent explicitly covered exchange years and their exceptional sessions.
@dataclass(frozen=True)
class ResearchCalendar:
    years: frozenset[int]
    holidays: frozenset[date]
    early_closes: frozenset[date]

    # Distinguish closed, early and full sessions without inferring from bars.
    def close_time(self, day: date) -> time | None:
        if day.year not in self.years:
            raise ValueError(f"calendar coverage unavailable: {day.year}")
        if day.weekday() >= 5 or day in self.holidays:
            return None
        return time(13) if day in self.early_closes else time(16)

    # Count exchange sessions, including early closes, on either side of a date.
    def offset(self, day: date, count: int) -> date:
        if self.close_time(day) is None:
            raise ValueError("offset requires a trading session")
        step = 1 if count >= 0 else -1
        for _ in range(abs(count)):
            day += timedelta(days=step)
            while self.close_time(day) is None:
                day += timedelta(days=step)
        return day

    # Enumerate known trading dates and close times for caller-supplied replay.
    def sessions(self, start: date, end: date) -> dict[date, time]:
        if start > end:
            raise ValueError("calendar range is reversed")
        out = {}
        day = start
        while day <= end:
            close = self.close_time(day)
            if close is not None:
                out[day] = close
            day += timedelta(days=1)
        return out


# Read the reviewed historical and current schedules, rejecting inconsistent data.
def load_calendar(directory: Path = DATA) -> ResearchCalendar:
    historical = json.loads((directory / "nyse_historical_sessions.json").read_text())[
        "years"
    ]
    current = json.loads((directory / "nyse_holidays.json").read_text())["years"]
    early = json.loads((directory / "nyse_early_closes.json").read_text())
    if set(historical) & set(current) or set(current) != set(early["years"]):
        raise ValueError("calendar coverage overlaps or lacks early-close coverage")
    if early["close_time"] != "13:00":
        raise ValueError("unsupported early close time")
    holidays: set[date] = set()
    half_days: set[date] = set()
    for year in set(historical) | set(current):
        if year in historical:
            full = historical[year]["full_closures"]
            half = historical[year]["early_closes"]
            if set(half.values()) - {"13:00"}:
                raise ValueError("unsupported historical early close time")
        else:
            full, half = current[year], early["years"][year]
        for target, values in ((holidays, full), (half_days, half)):
            for value in values:
                day = date.fromisoformat(value)
                if day.year != int(year) or day.weekday() >= 5 or day in target:
                    raise ValueError("invalid or duplicate calendar date")
                target.add(day)
    if holidays & half_days:
        raise ValueError("full and early closures overlap")
    return ResearchCalendar(
        frozenset(int(y) for y in set(historical) | set(current)),
        frozenset(holidays),
        frozenset(half_days),
    )


# Require the actual preceding twenty exchange sessions, not twenty arbitrary rows.
def prior_daily(
    history: list[DailyRow], session: date, calendar: ResearchCalendar
) -> list[DailyRow]:
    expected = {calendar.offset(session, -n) for n in range(1, 21)}
    selected = [row for row in history if row.date in expected]
    if len(selected) != 20 or {row.date for row in selected} != expected:
        raise ValueError("missing or duplicate prior daily session")
    if any(
        not math.isfinite(value) or value <= 0
        for row in selected
        for value in (row.close, row.adj_close)
    ):
        raise ValueError("invalid prior daily price")
    return sorted(selected, key=lambda row: row.date)


# Bind an archived grade and rejection flag to its original dated publication.
@dataclass(frozen=True)
class RecordedEligibility:
    session: date
    written_at: datetime
    grade: str | None
    rejecting_band: bool | None


# Treat naive timestamps consistently with the reviewed comparison adapter.
def _ny(stamp: datetime) -> datetime:
    return (
        stamp.replace(tzinfo=NEW_YORK)
        if stamp.tzinfo is None
        else stamp.astimezone(NEW_YORK)
    )


# Select only published, current records; a missing new grade cannot revive an old one.
def recorded_eligibility(
    records: list[RecordedEligibility],
    as_of: datetime,
    calendar: ResearchCalendar,
) -> Eligibility:
    now = _ny(as_of)
    unknown = Eligibility(None, None, None, None)
    if calendar.close_time(now.date()) is None:
        return unknown
    available = [record for record in records if _ny(record.written_at) <= now]
    if not available:
        return unknown
    latest_key = max((record.session, _ny(record.written_at)) for record in available)
    latest = [r for r in available if (r.session, _ny(r.written_at)) == latest_key]
    if len(latest) != 1:
        raise ValueError("ambiguous recorded eligibility publication")
    record = latest[0]
    if record.session not in (now.date(), calendar.offset(now.date(), -1)):
        return unknown
    # Archived records describe a completed daily session. An impossible early
    # publication cannot make a same-day final grade point-in-time evidence.
    close = calendar.close_time(record.session)
    if close is None or _ny(record.written_at) < datetime.combine(
        record.session, close, NEW_YORK
    ):
        return unknown
    return Eligibility(
        record.grade,
        _ny(record.written_at),
        record.rejecting_band,
        _ny(record.written_at),
    )
