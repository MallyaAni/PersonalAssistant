"""A date without its year is still a stated date: it resolves to the next
such day. Event calendars write them that way, and ten of twelve extracted
Arlington events were dropped as undated on 2026-09-02 because of it."""
from datetime import UTC, datetime

from backend.core.dates import extract_explicit_date, stated_date

NOW = datetime(2026, 9, 2, 20, 0, tzinfo=UTC)


def test_calendar_phrasings_without_a_year_resolve_to_the_next_such_day():
    for phrase, expected in [
        ("Saturday, September 5", "2026-09-05"),
        ("Sep 5", "2026-09-05"),
        ("Sunday, Sep 13", "2026-09-13"),
        ("Fri, Sep 5 · 7:00 PM", "2026-09-05"),
        ("Friday September 5th", "2026-09-05"),
        ("5 September", "2026-09-05"),
        ("9/5", "2026-09-05"),
        ("9/5/2026", "2026-09-05"),
        ("January 3", "2027-01-03"),
    ]:
        parsed = stated_date(phrase, NOW)
        assert parsed is not None and parsed.date().isoformat() == expected, (phrase, parsed)


def test_a_year_when_written_still_wins_and_a_past_date_is_not_an_event():
    assert stated_date("September 4, 2026", NOW).date().isoformat() == "2026-09-04"
    assert stated_date("5 September 2026", NOW).date().isoformat() == "2026-09-05"
    assert extract_explicit_date("Trail cleanup March 3, 2026", now=NOW) is None
    assert extract_explicit_date("September 1", now=NOW) is not None, "next September, not last week"
    assert extract_explicit_date("September 1", now=NOW).year == 2027


def test_without_a_reference_only_year_bearing_dates_are_read():
    assert stated_date("Saturday, September 5") is None
    assert stated_date("September 5, 2026") is not None
