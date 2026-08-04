"""Telling a happening apart from a page that lists happenings.

Every case here is a real result from a live sweep for "hiking" near Arlington,
Virginia, labelled by hand. An embedding cannot make this call — "Events in
Arlington, Virginia | Meetup" is a genuinely excellent semantic match for someone
interested in local events, and it is not something you can go to.
"""

import os

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.discovery.listing_filter import looks_like_a_directory


@pytest.mark.parametrize(
    ("title", "url"),
    [
        (
            "Best Hiking Trails Near Arlington, Virginia | Maps, Ratings & Info | onX",
            "https://www.onxmaps.com/hiking/near/arlington-va",
        ),
        (
            "Events in Arlington, Virginia | Meetup",
            "https://www.meetup.com/find/us--va--arlington",
        ),
        (
            "Hiking Events & Tickets in Arlington, VA - Travel & Outdoor",
            "https://www.eventbrite.com/b/va--arlington/travel-and-outdoor/hiking",
        ),
        (
            "Arlington Events & Event Calendar | Arlington Convention & Visitors",
            "https://www.stayarlington.com/events",
        ),
        (
            "Camping And Hiking Classes & Events near Arlington, VA | REI",
            "https://www.rei.com/events/p/us-va-arlington/a/camping-and-hiking",
        ),
        ("Top 10 things to do in Arlington", "https://example.org/guide"),
        ("Hiking trails near me", "https://example.org/trails"),
    ],
)
def test_directory_pages_are_recognized(title: str, url: str):
    assert looks_like_a_directory(title, url) is True


@pytest.mark.parametrize(
    ("title", "url"),
    [
        (
            "Hike & Pray: Boulder River Trail (easy/moderate - just long)",
            "https://www.meetup.com/trails-and-tribulations/events/307791319",
        ),
        (
            "Free Hike with a Naturalist | River Legacy Foundation",
            "https://riverlegacy.org/event/hike-with-a-naturalist-march-21",
        ),
        (
            "Nature and History Events",
            "https://www.arlingtonva.us/Parks-Recreation/Parks-Events/nature-events",
        ),
        ("Guided Nature Walk at Long Branch", "https://arlingtonva.us/e/guided-walk"),
    ],
)
def test_real_happenings_survive(title: str, url: str):
    assert looks_like_a_directory(title, url) is False


def test_a_specific_event_path_beats_a_generic_title():
    # A page at /events/<id> is a specific event however it is titled, and the
    # URL is the harder signal to fake.
    assert (
        looks_like_a_directory(
            "Best events in Arlington", "https://www.meetup.com/group/events/12345"
        )
        is False
    )


def test_a_missing_url_still_judges_the_title():
    assert looks_like_a_directory("Things to do in Arlington", None) is True
    assert looks_like_a_directory("Guided Nature Walk", None) is False


# A query that names no interest returns these, and they scored well against
# "hiking" because an embedding thinks a page about local events is an excellent
# match for someone interested in local events. Structural, not semantic.
@pytest.mark.parametrize(
    "title",
    [
        "Events Arlington, Virginia",
        "Arlington, VA Events, Calendar & Tickets | Eventbrite",
    ],
)
def test_a_broad_query_s_directory_pages_are_refused(title):
    assert looks_like_a_directory(title, None) is True


# The plural rule must not swallow a happening whose name begins with "Event".
@pytest.mark.parametrize(
    "title",
    [
        "Event Horizon Film Festival",
        "Eventide Concert Series Opening Night",
    ],
)
def test_a_happening_named_event_something_survives(title):
    assert looks_like_a_directory(title, None) is False
