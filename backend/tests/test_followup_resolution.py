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
