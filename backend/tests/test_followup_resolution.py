"""The follow-up resolver's parsing and its line for the router."""

from __future__ import annotations

import json

from backend.services.followup import Resolution, describe, parse_resolution


def test_a_reading_is_parsed_and_normalised():
    answer = {"content": json.dumps({"self_contained": "  does only one person win at the end of  Surviving Paradise? ", "refers_to": "subject", "subject": "Surviving Paradise"})}
    resolution = parse_resolution(answer, "does only one person win at the end?")
    assert resolution == Resolution("does only one person win at the end of Surviving Paradise?", "subject", "Surviving Paradise")
    assert resolution.changes("does only one person win at the end?")


def test_an_unreadable_answer_is_none_and_an_unknown_kind_is_none_kind():
    assert parse_resolution({"content": "not json"}, "x") is None
    assert parse_resolution({"content": json.dumps({"self_contained": "", "refers_to": "weird", "subject": ""})}, "x") == Resolution("x", "none", "")


def test_a_message_that_stands_alone_adds_no_line():
    plain = Resolution("what is the capital of Peru?", "none", "")
    assert not plain.changes("what is the capital of Peru?")
    assert describe(plain, "what is the capital of Peru?") == ""
    picture = Resolution("which hat do you like better for the outfit in the picture you made?", "picture", "")
    line = describe(picture, "which hat do you like better for this outfit?")
    assert line.startswith("Read in context as: which hat") and "a picture the assistant made" in line


# The failure that reaches people most is a tool that ran, returned the wrong
# content, and recorded a success. The person asking again is the only
# evidence, and it was being discarded - which would also have taught a
# corpus built from outcomes that the turn went well.
def test_a_message_asking_again_is_read_as_redoing_the_previous_turn():
    from backend.services.followup import parse_resolution

    resolution = parse_resolution(
        {
            "refers_to": "subject",
            "self_contained": "show me what is on in Arlington this weekend again",
            "subject": "Arlington events this weekend",
            "accepts_offer": False,
            "redoes_previous": True,
        },
        "no, I meant the Arlington one",
    )
    assert resolution is not None and resolution.redoes_previous is True
    # It travels in the trace, so the turn before it can be found later.
    assert resolution.as_dict()["redoes_previous"] is True


def test_an_ordinary_follow_up_is_not_read_as_redoing_anything():
    from backend.services.followup import parse_resolution

    resolution = parse_resolution(
        {
            "refers_to": "subject",
            "self_contained": "what is on in Arlington on Saturday",
            "subject": "Arlington events",
            "accepts_offer": False,
            "redoes_previous": False,
        },
        "and what about Saturday?",
    )
    assert resolution is not None and resolution.redoes_previous is False
    # Absent from the trace entirely rather than present and false: the trace
    # is read by a person, and a line that only appears when something
    # happened is worth more than one that is almost always False.
    assert "redoes_previous" not in resolution.as_dict()


def test_a_missing_field_does_not_accuse_the_previous_turn():
    from backend.services.followup import parse_resolution

    resolution = parse_resolution(
        {
            "refers_to": "none",
            "self_contained": "what is the weather",
            "subject": "",
            "accepts_offer": False,
        },
        "what is the weather",
    )
    assert resolution is not None and resolution.redoes_previous is False
