"""A failed search is rendered as turn state the reply must lead with."""

from backend.agents.graph import _render_search_state


def test_nothing_is_rendered_when_no_search_failed() -> None:
    assert _render_search_state({}) == ""
    assert _render_search_state({"failed": False}) == ""


def test_a_failed_search_is_rendered_with_its_reason_and_the_ban() -> None:
    text = _render_search_state({"failed": True, "reason": "the key is over its plan limit"})
    assert "the key is over its plan limit" in text
    assert "could not check live sources" in text
    assert "Do not offer, promise, or announce a search" in text


def test_a_search_that_ran_is_rendered_as_live_not_memory() -> None:
    text = _render_search_state({"ran": True})
    assert "ran just now" in text and "do not call them memory" in text
    assert _render_search_state({"ran": True, "failed": True}).startswith("\nThis turn: a live web search was attempted")
