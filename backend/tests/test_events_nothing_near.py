"""Finding things and finding nothing worth going to are different answers.

On 2026-09-04 an Arlington "fun things to do this week" was answered with a
family festival and a lake paddle in Colonial Heights, two hours south. The
distance judgement had worked perfectly - it marked every result far - and
then `render_listing` returned "" for having nothing to list, the caller read
that as "no typed listing available", and handed the model the same raw
results to write up itself. The filter ran and the fallback undid it.
"""
from datetime import UTC, datetime

from backend.core.event_window import window_for
from backend.core.events_listing import render_listing
from backend.core.event_extraction import Extraction, ListedEvent

NOW = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)


def _event(name: str, near: bool, day: int = 5) -> ListedEvent:
    return ListedEvent(
        name=name, venue="A park", area="Colonial Heights" if not near else "Arlington",
        artist="", what="Something on.", when_text="Sat 5 Sep", recurring=False,
        starts_at=datetime(2026, 9, day, 15, 0, tzinfo=UTC), start_time=None,
        price_text="", source_url="http://example.test", source_title="listing",
        near=near,
    )


def test_everything_too_far_says_so_instead_of_returning_nothing():
    found = Extraction(events=(_event("Africa Fest", near=False), _event("Paddle", near=False)))
    listing = render_listing(found, NOW)
    # The failure was an empty string here, which the caller reads as "no
    # typed listing" and answers by letting the model write these same two up.
    assert listing, "an empty listing hands the far events back to the model"
    assert "close enough" in listing and "2 listings" in listing
    # It must not name them: naming is recommending, and that is the bug.
    assert "Africa Fest" not in listing and "Colonial Heights" not in listing


def test_one_far_listing_reads_as_one():
    listing = render_listing(Extraction(events=(_event("Africa Fest", near=False),)), NOW)
    assert "1 listing," in listing and "1 listings" not in listing


def test_something_near_is_still_listed_normally():
    found = Extraction(
        events=(_event("Africa Fest", near=False), _event("Rosslyn Jazz", near=True))
    )
    listing = render_listing(found, NOW)
    assert "Rosslyn Jazz" in listing
    assert "close enough" not in listing
    # The far one is counted, not listed - the behaviour that already worked.
    assert "Africa Fest" not in listing
    assert "too far from you" in listing


def test_finding_nothing_at_all_still_returns_nothing_to_render():
    # A genuinely empty extraction keeps the old behaviour: the caller's prose
    # fallback is right when there is nothing to be right about.
    assert render_listing(Extraction(events=()), NOW) == ""


def test_the_window_is_named_when_there_is_one():
    found = Extraction(events=(_event("Africa Fest", near=False),))
    listing = render_listing(found, NOW, window=window_for("things to do this week", NOW))
    assert "close enough" in listing
    assert "week" in listing
