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


# Three of the five entries in the first digest Scout actually delivered were
# not happenings: a ticketing aggregator, a month-scoped concert listing, and an
# Instagram profile. These are the exact titles and URLs that were sent.
@pytest.mark.parametrize(
    ("title", "url"),
    [
        (
            "Arlington, Virginia Concert Tickets 2026 - 2027 | JamBase",
            "https://www.jambase.com/arlington",
        ),
        (
            "Arlington Concerts in August 2026 - American Arenas",
            "https://americanarenas.com/arlington",
        ),
        (
            "Clarendon / Arlington, VA (@therenegadeva)",
            "https://www.instagram.com/therenegadeva/",
        ),
    ],
)
def test_the_junk_from_the_first_delivered_digest_is_refused(title, url):
    assert looks_like_a_directory(title, url) is True


# A social profile is never one happening, whatever it is called. Its title is
# an account name plus a date, which is the same shape a real listing has, so
# the URL is the only reliable signal.
@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/somevenue/",
        "https://facebook.com/somevenue",
        "https://x.com/somevenue",
        "https://www.tiktok.com/@somevenue",
    ],
)
def test_a_social_profile_is_never_a_happening(url):
    assert looks_like_a_directory("Some Venue · August 3, 2026", url) is True


# The widened rules must not start eating real events. A concert with a name is
# a concert; a film festival called "Event Horizon" is a happening.
@pytest.mark.parametrize(
    ("title", "url"),
    [
        ("Arlington County Fair", "https://arlingtoncountyfair.us/"),
        (
            "Lubber Run Amphitheater - Free Concert Series",
            "https://parks.arlingtonva.us/lubber-run",
        ),
        (
            "Concert in the Park: The Nighthawks",
            "https://parks.arlingtonva.us/events/12",
        ),
        ("Event Horizon Film Festival", "https://ehff.org/2026"),
        ("2026 NOVA Running Club 5K", "https://runsignup.com/Race/VA/Arlington/NOVA5K"),
    ],
)
def test_a_real_happening_still_survives(title, url):
    assert looks_like_a_directory(title, url) is False


# Both of these reached the digest Scout sent at 14:20, so they are shapes taken
# from real delivered output rather than imagined.
@pytest.mark.parametrize(
    ("title", "url"),
    [
        # The giveaway sits in the middle segment, and anchoring the
        # place-scoped rule at the start of the whole title missed it.
        (
            "Free Concerts | Upcoming Events near Arlington, VA | Live Music Project",
            "https://www.livemusicproject.org/events/free?near=arlington-va",
        ),
        # An advertisement, titled to sound like an offer worth taking. Only the
        # destination gives it away.
        (
            "Join now and get 50% off a Club membership",
            "https://click.linksynergy.com/fs-bin/click?id=5lRxBRhs1h0",
        ),
    ],
)
def test_the_junk_from_the_second_delivered_digest_is_refused(title, url):
    assert looks_like_a_directory(title, url) is True


# Judging each segment must not start eating events whose titles carry a venue
# or a series after a separator, which is how many of them are written.
@pytest.mark.parametrize(
    ("title", "url"),
    [
        ("Water Lantern Festival", "https://www.waterlanternfestival.com/events/dc"),
        (
            "Concert in the Park - The Nighthawks",
            "https://parks.arlingtonva.us/events/12",
        ),
        (
            "Jazz Soiree | The Phillips Collection",
            "https://phillipscollection.org/event/1",
        ),
        ("Hillwood After Hours Garden Party", "https://hillwoodmuseum.org/events/hah"),
    ],
)
def test_a_segmented_title_is_not_assumed_to_be_a_listing(title, url):
    assert looks_like_a_directory(title, url) is False
