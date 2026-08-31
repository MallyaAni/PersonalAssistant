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


def test_the_opening_of_the_thread_always_survives():
    # Where a thread names its subject. Everything after it is shorthand,
    # and a window that keeps only the tail keeps the shorthand and drops
    # the name: on 2026-08-31 that produced a diagram of a generic
    # "architecture thinking process" in a thread about Roman aqueducts.
    assert "aqueduct" in _recent(HISTORY, "")
    assert "aqueduct" in _recent(HISTORY, "", 3)


def test_the_middle_is_what_gets_elided_not_the_front():
    long_thread = HISTORY + [
        {"query": f"filler question {n}", "response": f"filler answer {n} " + "x" * 400}
        for n in range(20)
    ]
    rendered = _recent(long_thread, "")
    assert "aqueduct" in rendered, "the subject was trimmed away again"
    assert "filler answer 19" in rendered, "the recent end must survive too"
    assert "[...]" in rendered


def test_a_reply_also_opens_the_middle_at_the_turn_it_names():
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


# The matching bug that made all of the above pointless for a while.
def test_a_short_message_does_not_match_any_long_one_containing_its_words():
    # "try again" is a substring of "...please revise the request and try
    # again", so an unguarded containment test matched them - and because
    # the search runs backwards it matched the *newest* such turn. The
    # window then opened at the end of the thread instead of at the message
    # being pointed at, which is the opposite of what a reply means.
    thread = HISTORY + [
        {"query": "try again", "response": "Here it is again."},
    ]
    replied_to = "I couldn't create that diagram. Please revise the request and try again."
    _, index = _answering_line(replied_to, thread)
    assert index == 3, f"matched turn {index}, which is not the one replied to"


def test_a_bubble_that_is_most_of_the_turn_still_matches():
    # The guard must not break the ordinary case: a reply to a turn whose
    # stored text has a little more in it than the bubble carried.
    _, index = _answering_line("They used stacked arches", HISTORY)
    assert index == 1, index


def test_what_came_after_the_replied_to_turn_is_counted_not_quoted():
    # Their wording is the poison - three diagrams called "Try Again" and a
    # reply naming one of them. The model should know retries happened
    # without reading what they were called.
    rendered = _recent(HISTORY, "", 3)
    assert "Try Again Flow" not in rendered
    assert "Simple Flowchart" not in rendered
    assert "later exchange" in rendered
    assert "aqueduct" in rendered
