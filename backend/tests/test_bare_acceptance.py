"""A bare "yes" is an instruction only when something was offered.

Measured on the real routing model 2026-08-29: "yes" following a plain weather
answer routed a fresh seven-day weather call. Agreeing with a statement sent
the assistant off doing work, and the same shape after a bubble about booking
would be worse than wasteful.

The guard is deliberately narrow, and these tests are mostly about that
narrowness: the only message it can refuse is one carrying no content of its
own. Everything else routes exactly as it did.
"""

from __future__ import annotations

import pytest

from backend.services.followup import Resolution, is_bare_acceptance


@pytest.mark.parametrize(
    "message",
    [
        "yes", "Yes!", "  YES. ", "yes please", "yep", "yeah", "sure", "ok",
        "okay", "do it", "go ahead", "go for it", "please do", "sounds good",
        "ok, do it", "Let's do it!", "alright", "yes, thanks",
    ],
)
def test_these_are_nothing_but_assent(message):
    assert is_bare_acceptance(message), message


@pytest.mark.parametrize(
    "message",
    [
        # Carries its own instruction, so the offer question is irrelevant.
        "yes and find parking too",
        "yes, book the later one",
        "do it for friday instead",
        "sure, but make it 8pm",
        # Not assent at all.
        "no", "no thanks", "not yet", "maybe later",
        # The word appears, but the message is about something else.
        "yesterday", "can you say yes for me", "did she say yes?",
        "what does yes mean in dutch",
        # Nothing.
        "", "   ", "?",
    ],
)
def test_these_are_not(message):
    assert not is_bare_acceptance(message), message


def test_a_refusal_is_never_treated_as_acceptance():
    # The direction that matters most: "no" must not reach a guard whose job
    # is deciding whether a *yes* may act.
    for refusal in ("no", "no thanks", "nope", "don't", "stop"):
        assert not is_bare_acceptance(refusal), refusal


def test_the_resolution_defaults_to_refusing_to_act():
    # An unreadable or absent judgement leaves the assistant answering in
    # words, never acting. Safe direction by construction.
    assert Resolution("yes", "none", "").accepts_offer is False


def test_the_parser_reads_the_field_and_defaults_it_false():
    from backend.services.followup import parse_resolution

    offered = parse_resolution(
        {"self_contained": "find thai", "refers_to": "subject", "subject": "thai",
         "accepts_offer": True},
        "yes",
    )
    assert offered is not None and offered.accepts_offer is True

    missing = parse_resolution(
        {"self_contained": "yes", "refers_to": "none", "subject": ""}, "yes"
    )
    assert missing is not None and missing.accepts_offer is False


def test_every_referent_category_has_a_reading_and_none_can_raise():
    """A category added to the enum and forgotten in describe() took the turn down.

    Measured 2026-08-30: adding "diagram" to REFERS_TO raised KeyError inside
    the router for every message the resolver put in it. The reading is worth
    less than the turn, so an unknown category now degrades to a general phrase.
    """
    from backend.services.followup import REFERS_TO, Resolution, describe

    for kind in REFERS_TO:
        reading = describe(Resolution("restated differently", kind, "x"), "original")
        assert "It refers to" in reading, (kind, reading)

    # And a category this function has never heard of does not raise.
    invented = describe(Resolution("restated differently", "hologram", ""), "original")
    assert "something earlier in the conversation" in invented, invented


def test_a_diagram_is_not_described_as_a_picture():
    from backend.services.followup import Resolution, describe

    reading = describe(Resolution("make the aqueduct diagram simpler", "diagram", "aqueduct"), "simpler")
    assert "not a picture" in reading, reading
