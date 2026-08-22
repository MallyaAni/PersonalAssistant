"""The two cadences tasks needed that sweeps never did.

`once` is a single stated instant - it is what it is, even in the past,
and the caller decides what a past one means. `weekdays` is daily minus
the weekend: a Friday-evening "every weekday at 7" resolves to Monday, not
Saturday. Both ride the same DST-correct local-time math as daily/weekly.
"""

from datetime import UTC, date, datetime

import pytest

from backend.discovery.schedule import Cadence, next_run_at


def test_once_is_the_stated_instant_in_the_users_zone():
    cadence = Cadence("once", hour=9, weekday=0, timezone="America/New_York",
                      minute=30, on_date=date(2026, 8, 25))

    when = next_run_at(cadence, datetime(2026, 8, 22, 12, 0, tzinfo=UTC))

    assert when.astimezone(UTC) == datetime(2026, 8, 25, 13, 30, tzinfo=UTC)


def test_once_without_a_day_is_refused():
    with pytest.raises(ValueError, match="needs its day"):
        Cadence("once", hour=9, weekday=0, timezone="UTC")


def test_weekdays_skips_the_weekend():
    cadence = Cadence("weekdays", hour=7, weekday=0, timezone="UTC")
    # Friday 2026-08-21 at 20:00 UTC: the next weekday 07:00 is Monday.
    after = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)

    when = next_run_at(cadence, after)

    assert when == datetime(2026, 8, 24, 7, 0, tzinfo=UTC)
    assert when.weekday() == 0


def test_weekdays_on_a_weekday_morning_is_later_that_day():
    cadence = Cadence("weekdays", hour=7, weekday=0, timezone="UTC")
    after = datetime(2026, 8, 24, 5, 0, tzinfo=UTC)  # Monday, before 07:00

    assert next_run_at(cadence, after) == datetime(2026, 8, 24, 7, 0, tzinfo=UTC)
