"""The link fence: an address survives only when the application can vouch for it.

The case these tests exist for went to a real phone on 2026-08-29:
`https://maps.app.goo.gl/xyz`, `/abc`, `/def`, `/ghi`, `/jkl` and
`https://youtu.be/xyz` - shortened links with placeholder ids, invented by
the model because the events prompt asked it to write links and nothing
checked them.
"""

from backend.core.links import (
    LinkFence,
    allowed_urls,
    canonical,
    fence_text,
    template_is_grounded,
)

# Eight results, as the turn actually had them.
EVIDENCE_SOURCES = [
    {"url": "https://www.thelawncanggu.com/events", "title": "The Lawn Canggu"},
    {"url": "https://labrisabali.com/whats-on", "title": "La Brisa"},
]
EVIDENCE_TEXT = (
    "The Lawn Canggu hosts a Sunday session at Batu Bolong. "
    "La Brisa runs sunset sessions on the beach in Canggu."
)
ALLOWED = allowed_urls(EVIDENCE_SOURCES)


def test_the_arsalon_reply_loses_every_invented_address():
    reply = (
        "**1. The Lawn Canggu – Sunday Social**\n"
        "Map link: [Google Maps](https://maps.app.goo.gl/xyz)\n"
        "Time: Sundays, 4 PM – 10 PM\n"
        "YouTube: [Deep house set](https://youtu.be/xyz)\n"
        "Instagram: [@thelawncanggu](https://www.instagram.com/thelawncanggu)\n"
        "Details: https://www.thelawncanggu.com/events\n"
    )
    fenced, dropped = fence_text(reply, ALLOWED, EVIDENCE_TEXT)

    for invented in ("maps.app.goo.gl", "youtu.be", "instagram.com"):
        assert invented not in fenced, fenced
    # The source's own link is untouched.
    assert "https://www.thelawncanggu.com/events" in fenced
    # The words survive; only the addresses go.
    assert "The Lawn Canggu – Sunday Social" in fenced
    assert "Sundays, 4 PM – 10 PM" in fenced
    # Lines that were nothing but an address are gone, not left dangling.
    assert "Map link:" not in fenced
    assert "YouTube:" not in fenced
    assert sorted(set(dropped)) == ["maps.app.goo.gl", "www.instagram.com", "youtu.be"]


def test_a_search_template_survives_when_its_subject_came_from_the_evidence():
    grounded = "Map: https://maps.google.com/?q=La+Brisa+Canggu"
    fenced, dropped = fence_text(grounded, ALLOWED, EVIDENCE_TEXT)
    assert fenced.strip() == grounded.strip() and dropped == []

    invented = "Map: https://maps.google.com/?q=Made+Up+Beach+Club+Nowhere"
    fenced, dropped = fence_text(invented, ALLOWED, EVIDENCE_TEXT)
    assert "maps.google.com" not in fenced, fenced
    assert dropped == ["maps.google.com"]


def test_a_youtube_search_is_a_template_but_a_watch_link_is_a_claim():
    assert template_is_grounded(
        "https://www.youtube.com/results?search_query=La+Brisa", EVIDENCE_TEXT
    )
    assert not template_is_grounded("https://youtu.be/abc", EVIDENCE_TEXT)
    assert not template_is_grounded(
        "https://www.youtube.com/watch?v=abc", EVIDENCE_TEXT
    )


def test_an_evidence_url_survives_however_the_sentence_punctuates_it():
    text = "It is listed here (https://labrisabali.com/whats-on), worth a look."
    fenced, dropped = fence_text(text, ALLOWED, EVIDENCE_TEXT)
    assert "https://labrisabali.com/whats-on" in fenced and dropped == []
    assert fenced.strip().endswith("worth a look.")


def test_the_same_reply_fences_identically_however_the_stream_splits_it():
    # A fence that depends on where the model's chunks happen to break is
    # not a fence: the URL arrives in pieces.
    reply = (
        "Two spots:\n"
        "- La Brisa — https://labrisabali.com/whats-on\n"
        "- Somewhere else — https://maps.app.goo.gl/jkl\n"
        "That is all.\n"
    )
    whole, _ = fence_text(reply, ALLOWED, EVIDENCE_TEXT)
    for size in (1, 2, 3, 5, 7, 13, 29):
        fence = LinkFence(allowed=ALLOWED, evidence=EVIDENCE_TEXT)
        streamed = "".join(
            fence.feed(reply[index : index + size])
            for index in range(0, len(reply), size)
        ) + fence.flush()
        assert streamed == whole, (size, streamed, whole)


def test_indentation_and_blank_lines_are_kept():
    # Scout's stripper collapses whitespace, which would fuse a listing into
    # one paragraph on a phone. This one must not.
    text = "Friday\n\n  - The Lawn, Batu Bolong\n  - La Brisa\n"
    fenced, dropped = fence_text(text, ALLOWED, EVIDENCE_TEXT)
    assert fenced == text.rstrip("\n") + "\n" or fenced == text, repr(fenced)
    assert dropped == []


def test_addresses_are_compared_by_what_makes_them_the_same_address():
    assert canonical("https://www.Example.com/a/") == canonical("http://example.com/a")
    assert canonical("https://x.test/a?b=1") != canonical("https://x.test/a")
    assert canonical("  ") == ""
    assert canonical("www.example.com/a") == "example.com/a"


def test_nothing_is_dropped_from_a_reply_that_says_no_addresses():
    text = "Thai on Friday sounds good — I'll remind you at 6."
    fenced, dropped = fence_text(text, ALLOWED, EVIDENCE_TEXT)
    assert fenced.strip() == text and dropped == []


def test_the_dropped_log_names_hosts_and_never_the_address():
    fence = LinkFence(allowed=ALLOWED, evidence=EVIDENCE_TEXT)
    fence.line("see https://maps.app.goo.gl/secret-token-abc")
    assert fence.dropped == ["maps.app.goo.gl"]
    assert not any("secret-token" in host for host in fence.dropped)


def test_a_turn_with_no_evidence_keeps_no_model_written_address():
    # The strictest case the operator chose: sourced or templated only.
    fenced, dropped = fence_text(
        "Try https://some-blog.example/post for more.", frozenset(), ""
    )
    assert "some-blog.example" not in fenced
    assert dropped == ["some-blog.example"]


def test_a_venue_with_an_apostrophe_still_grounds_its_map_link():
    # A search box spells "Old Man's Beach Bar" as "Old+Mans+Beach+Bar". A
    # fence that called that invented would strip the links this system
    # builds correctly - the opposite failure, and just as bad.
    evidence = "Old Man's Beach Bar in Canggu runs a Wednesday night."
    assert template_is_grounded(
        "https://maps.google.com/?q=Old+Mans+Beach+Bar+Canggu", evidence
    )
    assert not template_is_grounded(
        "https://maps.google.com/?q=Invented+Sky+Lounge+Canggu", evidence
    )
