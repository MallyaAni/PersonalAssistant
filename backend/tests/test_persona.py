"""A picture of a person, rebuilt when the person changes and not otherwise.

Twenty interests at equal strength could not say that seven of them meant
"social dancer". These hold the two properties that make a characterization
usable: it costs one model call per distinct interest set, and saving a new
interest is itself what makes the next read regenerate it - so there is no
staleness to manage and no schedule to run.
"""
import asyncio

from backend.core.persona import characterize, forget_personas

ANI = ("salsa", "bachata", "swing dancing", "breweries", "chess")


class _Counting:
    """Stands in for the model, and counts how often it was asked."""

    def __init__(self, says: str = "A social dancer who plays chess.") -> None:
        self.says = says
        self.calls = 0

    def chat(self, messages, max_tokens=160, *args, **kwargs):
        self.calls += 1
        return {"content": self.says}


class _Broken:
    def chat(self, *args, **kwargs):
        raise RuntimeError("the model is down")


def setup_function() -> None:
    forget_personas()


def test_the_same_interests_are_characterized_once():
    llm = _Counting()
    for _ in range(3):
        assert asyncio.run(characterize(llm, ANI)) == "A social dancer who plays chess."
    assert llm.calls == 1


def test_saving_a_new_interest_rebuilds_it():
    llm = _Counting()
    asyncio.run(characterize(llm, ANI))
    asyncio.run(characterize(llm, ANI + ("karaoke",)))
    assert llm.calls == 2, "a changed person is a changed description"


def test_reordering_the_same_interests_does_not_spend_a_call():
    # The order they were saved in is not part of who someone is.
    llm = _Counting()
    asyncio.run(characterize(llm, ANI))
    asyncio.run(characterize(llm, tuple(reversed(ANI))))
    assert llm.calls == 1


def test_two_people_are_two_descriptions():
    llm = _Counting()
    asyncio.run(characterize(llm, ANI))
    asyncio.run(characterize(llm, ("reading", "gardening")))
    assert llm.calls == 2


def test_nothing_known_asks_nothing():
    llm = _Counting()
    assert asyncio.run(characterize(llm, ())) == ""
    assert asyncio.run(characterize(llm, ("", "  "))) == ""
    assert llm.calls == 0


def test_a_model_that_is_down_costs_the_turn_nothing():
    assert asyncio.run(characterize(_Broken(), ANI)) == ""


def test_an_empty_answer_is_not_cached_as_one():
    llm = _Counting(says="")
    assert asyncio.run(characterize(llm, ANI)) == ""
    assert asyncio.run(characterize(llm, ANI)) == ""
    # It tries again rather than remembering the failure.
    assert llm.calls == 2
