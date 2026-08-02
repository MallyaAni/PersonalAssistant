"""Stage 5: the calendar file a phone actually imports.

These are pure-function tests on purpose. A calendar client that dislikes a file
usually declines it without saying why, and one it accepts but misreads produces
an appointment at the wrong time, so the format's rules are asserted directly
rather than inferred from a successful-looking import.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.discovery.calendar import (
    MAX_LINE_OCTETS,
    build_calendar,
    build_vevent,
    calendar_filename,
    escape_text,
    event_uid,
    fold_line,
    format_utc,
)
from backend.discovery.events import DiscoveredEvent


def _event(**overrides: object) -> DiscoveredEvent:
    base: dict[str, object] = {
        "source_id": "src-1",
        "external_id": "evt-1",
        "title": "Jazz at the Green",
        "starts_at": datetime(2026, 8, 14, 23, 0, tzinfo=UTC),
        "ends_at": datetime(2026, 8, 15, 1, 0, tzinfo=UTC),
        "place": "New Haven, CT",
        "url": "https://example.org/jazz",
        "summary": "An evening set.",
    }
    base.update(overrides)
    return DiscoveredEvent(**base)  # type: ignore[arg-type]


def _unfold(document: str) -> list[str]:
    # Reverse RFC 5545 folding so a property can be asserted as one value.
    return document.replace("\r\n ", "").split("\r\n")


def test_reserved_characters_are_escaped_in_order():
    # Backslash must be escaped first, or the escapes introduced for the
    # separators below get escaped a second time and reach the client doubled.
    assert escape_text("a\\b;c,d\ne") == "a\\\\b\\;c\\,d\\ne"


def test_carriage_returns_collapse_to_a_single_escape():
    assert escape_text("one\r\ntwo") == "one\\ntwo"


def test_lines_fold_on_octets_not_characters():
    # A multi-byte character split across the fold boundary would corrupt the
    # document, so folding counts bytes.
    line = "SUMMARY:" + "é" * 80
    folded = fold_line(line)

    for segment in folded.split("\r\n "):
        assert len(segment.encode("utf-8")) <= MAX_LINE_OCTETS
    assert folded.replace("\r\n ", "") == line


def test_naive_timestamps_are_refused():
    # A naive timestamp has no defensible interpretation here: guessing the zone
    # produces an appointment at a confidently wrong time.
    with pytest.raises(ValueError, match="timezone-aware"):
        format_utc(datetime(2026, 8, 14, 19, 0))


def test_local_times_convert_to_utc():
    eastern = datetime(2026, 8, 14, 19, 0, tzinfo=ZoneInfo("America/New_York"))
    assert format_utc(eastern) == "20260814T230000Z"


def test_uid_is_stable_across_renders():
    # Re-importing must update the existing appointment rather than create a
    # second one, which only holds if the UID does not change per render.
    assert event_uid(_event()) == event_uid(_event())
    assert event_uid(_event(external_id="evt-2")) != event_uid(_event())


def test_vevent_carries_the_required_properties():
    document = build_vevent(_event())
    lines = _unfold(document)

    assert lines[0] == "BEGIN:VCALENDAR"
    assert "VERSION:2.0" in lines
    assert "METHOD:PUBLISH" in lines
    assert "BEGIN:VEVENT" in lines
    assert "DTSTART:20260814T230000Z" in lines
    assert "DTEND:20260815T010000Z" in lines
    assert "SUMMARY:Jazz at the Green" in lines
    assert "LOCATION:New Haven\\, CT" in lines
    assert "URL:https://example.org/jazz" in lines
    assert document.endswith("END:VCALENDAR\r\n")
    # Every line must be CRLF-terminated; a bare LF makes some clients reject
    # the whole document.
    assert "\n" not in document.replace("\r\n", "")


def test_missing_end_becomes_a_default_duration():
    document = build_vevent(_event(ends_at=None))
    assert "DTEND:20260815T000000Z" in _unfold(document)


def test_end_before_start_is_corrected_rather_than_emitted():
    document = build_vevent(
        _event(ends_at=datetime(2026, 8, 14, 22, 0, tzinfo=UTC)),
    )
    lines = _unfold(document)
    start = lines[lines.index("DTSTART:20260814T230000Z")]
    assert start
    assert "DTEND:20260815T000000Z" in lines


def test_a_url_that_would_break_parsing_is_dropped():
    # URI values are not escaped, so a separator inside one cannot be emitted
    # safely; dropping it beats shipping a document the client mis-parses.
    document = build_vevent(_event(url="https://example.org/a,b"))
    assert "URL:" not in document


def test_an_event_without_a_start_is_refused():
    with pytest.raises(ValueError, match="without a start"):
        build_vevent(_event(starts_at=None))


def test_a_collection_holds_every_schedulable_event():
    events = (
        _event(),
        _event(external_id="evt-2", title="Second", starts_at=None),
        _event(
            external_id="evt-3",
            title="Third",
            starts_at=datetime(2026, 8, 20, 18, 0, tzinfo=UTC),
            ends_at=None,
        ),
    )

    document = build_calendar(events, calendar_name="AniOS Discoveries")
    lines = _unfold(document)

    # The unschedulable one is skipped rather than emitted without a DTSTART.
    assert lines.count("BEGIN:VEVENT") == 2
    assert "X-WR-CALNAME:AniOS Discoveries" in lines
    assert "SUMMARY:Third" in lines
    assert "SUMMARY:Second" not in lines


def test_filenames_stay_safe_and_never_empty():
    assert calendar_filename(_event()) == "Jazz-at-the-Green.ics"
    assert calendar_filename(_event(title="///")) == "event.ics"
    assert len(calendar_filename(_event(title="x" * 500))) <= 64


def test_dtstamp_is_present_and_current():
    stamp = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    document = build_vevent(_event(), now=stamp)
    assert "DTSTAMP:20260801T120000Z" in _unfold(document)
    assert stamp - timedelta(days=1) < stamp
