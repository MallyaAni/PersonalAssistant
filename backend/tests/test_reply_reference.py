"""A long-press reply says which message is being answered.

iMessage lets a person reply to a specific bubble, and that reference is
worth more than anything a resolver can infer from the words. On
2026-08-30 the operator did exactly that, repeatedly, in a group thread
where a diagram of Roman aqueducts had failed - and the reference was read
off the wire, used for nothing but pinning a picture, and thrown away. The
retries ("you try again bruh", "try again!", "Try Again") were each
resolved against the most recent message, which during a run of failures
is the failure, and the thread ended holding a diagram titled "Try Again".

These cover the parts that must hold without a model: that a reply is
matched to the exchange it names, that the transcript opens at that point
rather than at the last few turns, and that nothing changes when there is
no reply.
"""

from __future__ import annotations

from backend.services.followup import _answering_line, _recent

HISTORY = [
    {"query": "what is an aqueduct?", "response": "A channel that carries water."},
    {"query": "how did they build it that high", "response": "They used stacked arches."},
    {"query": "generate a picture of the architecture thinking process",
     "response": "Here's the image you asked for."},
    {"query": "can you draw it as a diagram instead?",
     "response": "I couldn't create that diagram. Please revise the request and try again."},
    {"query": "you try again bruh", "response": "Created an editable diagram: Simple Flowchart."},
    {"query": "try again!", "response": "Created an editable diagram: Try Again Flow."},
]


def test_a_reply_is_matched_to_the_exchange_it_names():
    # Both halves are shown, because the bubble replied to is often the
    # answer and the subject lives in the question that produced it.
    line, index = _answering_line(
        "I couldn't create that diagram. Please revise the request and try again.", HISTORY
    )
    assert index == 3, index
    assert "can you draw it as a diagram instead?" in line
    assert "replied directly" in line


def test_a_reply_to_the_persons_own_message_is_matched_too():
    # People reply to their own earlier request at least as often as to ours.
    line, index = _answering_line("can you draw it as a diagram instead?", HISTORY)
    assert index == 3, index
    assert "diagram" in line


def test_one_bubble_of_a_long_reply_still_finds_its_turn():
    # A long answer is delivered as several bubbles and the person replies to
    # one of them, so the match is by containment rather than equality.
    _, index = _answering_line("They used stacked arches.", HISTORY)
    assert index == 1, index


def test_an_unrecognised_reply_is_still_shown_rather_than_dropped():
    # A bubble older than the stored history, or from a thread we did not
    # write. There is no turn to open the window at, but what they pointed
    # at is still the best evidence there is.
    line, index = _answering_line("something from last week", HISTORY)
    assert index is None
    assert "something from last week" in line


def test_no_reply_changes_nothing():
    line, index = _answering_line("", HISTORY)
    assert line == "" and index is None


def test_the_transcript_opens_at_the_replied_to_turn():
    # The subject of "can you draw it as a diagram instead?" is two turns
    # further back, outside the four-turn window the resolver normally uses.
    # A reply reopens the conversation at the point it names.
    narrow = _recent(HISTORY, "")
    assert "aqueduct" not in narrow, "the default window should not reach that far"
    # Opened one turn before the match, which is where "it" was last named -
    # "can you draw it as a diagram instead?" says nothing about what "it"
    # is, and the turn before it does.
    opened = _recent(HISTORY, "", 3)
    assert "picture of the architecture thinking process" in opened
    assert "can you draw it as a diagram instead?" in opened


def test_opening_at_the_first_turn_is_not_an_index_error():
    assert "aqueduct" in _recent(HISTORY, "", 0)


def test_an_out_of_range_index_is_clamped():
    assert _recent(HISTORY, "", 99)


def test_the_schema_asks_for_each_field_after_what_it_is_derived_from():
    # Measured 2026-08-30 on the operator's own thread. With self_contained
    # first the model restated "try again" as "try again" and had nothing
    # left to name a subject from; with subject first it came back empty 3/3
    # while the restatement carried the subject perfectly well. The order is
    # the fix, so it is asserted rather than left to a comment.
    from backend.services.followup import _SCHEMA

    fields = list(_SCHEMA["properties"])
    assert fields.index("refers_to") < fields.index("self_contained")
    assert fields.index("self_contained") < fields.index("subject")
