"""Refusing a find that names a different place than the one searched.

The asymmetry is the whole design: admitting a find from the wrong state wastes
a slot, while rejecting a local one removes something the user wanted and leaves
no trace. So these cover what it refuses, and — at greater length — everything
it must not.
"""

import os

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.discovery.geography import contradicts_locality, stated_regions


@pytest.mark.parametrize(
    ("title", "summary", "url"),
    [
        # The one that reached a real digest.
        (
            "Ricky Skaggs at Arlington Music Hall",
            "Live in concert.",
            "https://concertfix.com/concerts/arlington-tx",
        ),
        (
            "Barn dance",
            "Held in Arlington, Texas this month.",
            "https://example.org/e/barn-dance",
        ),
        (
            "Book fair",
            "A weekend fair in Springfield, Illinois.",
            "https://example.org/e/book-fair",
        ),
    ],
)
def test_a_find_that_names_another_state_is_refused(title, summary, url):
    assert contradicts_locality(title, summary, url, "Virginia") is True


@pytest.mark.parametrize(
    ("title", "summary", "url"),
    [
        # Names the right state, in each of the places it can be named.
        ("Sunrise hike", "Great Falls, Virginia at dawn.", "https://x.org/e/hike"),
        ("Sunrise hike", "At dawn.", "https://x.org/events/great-falls-va"),
        ("Concert, VA", "An evening show.", "https://x.org/e/show"),
        # Says nothing about where it is. Silence must always pass, because it
        # is the common case and a guess here deletes a real find.
        ("Beginner line dancing", "A drop-in class.", "https://x.org/e/dance"),
        ("Jazz trio", None, None),
        # A long numeric id is not a region, and neither is a random slug.
        ("Barn dance", "Tickets now.", "https://x.org/e/barn-dance-1234567890123"),
    ],
)
def test_a_local_or_silent_find_is_kept(title, summary, url):
    assert contradicts_locality(title, summary, url, "Virginia") is False


def test_nothing_is_refused_without_a_configured_region():
    # Fail open, like the rest of the loop: with no region there is nothing to
    # contradict.
    assert (
        contradicts_locality(
            "Barn dance", "In Arlington, Texas.", "https://x.org/e/d", None
        )
        is False
    )


def test_a_non_us_region_refuses_nothing():
    # London, England names no state, so this stage abstains entirely rather
    # than refusing everything it does not recognise.
    assert (
        contradicts_locality(
            "Salsa in Birmingham", "Across England.", "https://x.org/england", "England"
        )
        is False
    )


def test_both_spellings_of_a_region_are_read():
    assert stated_regions("Show, Texas", None, None) == {"texas"}
    assert stated_regions("Show, TX", None, None) == {"texas"}
    assert stated_regions("Show", None, "https://x.org/c/arlington-tx") == {"texas"}
