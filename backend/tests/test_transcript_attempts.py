"""An attempt that did not deliver says so in the history a model reads.

A turn whose search failed, was refused, came back empty, or came back about
something else reads exactly like one that worked: the assistant's prose is
there either way, and the failure lives only in the trace nobody shows the
model. So "try again" reaches a router that cannot see there was anything to
try again, and it decides the same way a second time. These hold the note to
being read off the trace rather than the reply's words, and to carrying no
subject of its own.
"""
from backend.services.transcript import transcript_lines


def _turn(query: str, response: str, search: str | None = None, **trace) -> dict:
    if search is not None:
        trace["search"] = search
    return {
        "query": query,
        "response": response,
        "metadata": {"trace": trace} if trace else {},
    }


def _assistant(turn: dict) -> str:
    return next(line for line in transcript_lines([turn]) if line.startswith("Assistant:"))


def test_a_search_that_found_nothing_is_marked_as_an_attempt():
    line = _assistant(_turn("what's on in Arlington?", "I couldn't find much.", "ran:0"))
    assert "found nothing" in line
    # The reply's own words stay: they carry the subject, and dropping them is
    # how a receipt became what the conversation appeared to be about.
    assert "I couldn't find much." in line


def test_results_about_a_different_subject_are_marked_even_though_there_were_results():
    line = _assistant(_turn("who won?", "Here is what I found.", "ran:7 off-subject"))
    assert "different subject" in line, line


def test_a_search_that_did_not_run_and_one_that_was_refused_read_differently():
    failed = _assistant(_turn("what's on?", "Something went wrong.", "failed"))
    refused = _assistant(_turn("what's on?", "Not right now.", "limit"))
    assert "did not run" in failed
    assert "not allowed to run" in refused
    assert failed != refused


def test_a_search_that_worked_is_left_alone():
    line = _assistant(_turn("what's on?", "Three things this weekend.", "ran:7"))
    assert line == "Assistant: Three things this weekend."


def test_a_turn_with_no_trace_at_all_is_left_alone():
    assert _assistant(_turn("hello", "Hi.")) == "Assistant: Hi."
    plain = {"query": "hello", "response": "Hi."}
    assert transcript_lines([plain]) == ["User: hello", "Assistant: Hi."]


def test_the_note_names_no_subject_of_its_own():
    # The 2026-08-30 failure was a receipt carrying a title, which the
    # follow-up resolver then read as the conversation's subject.
    line = _assistant(_turn("aqueducts?", "Here.", "ran:0", route={"detail": "Try Again Flow"}))
    assert "Try Again Flow" not in line


def test_an_attempt_with_no_reply_still_leaves_a_line():
    # Nothing was said back, and a retry still refers to it.
    line = _assistant(_turn("what's on?", "", "failed"))
    assert line == "Assistant: [the web search did not run]"
