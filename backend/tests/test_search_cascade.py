import pytest

from backend.search.cascade import CascadingSearchRouter
from backend.search.classifier import LMStudioFreshnessClassifier
from backend.search.routing import SearchRoutingPolicy


class StubLLM:
    """Return a scripted reply and record how the model was called."""

    def __init__(self, reply: str = "YES", fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.calls: list[tuple[str, int]] = []

    def generate_text(self, prompt: str, max_tokens: int = 1024) -> str:
        self.calls.append((prompt, max_tokens))
        if self.fail:
            raise RuntimeError("model unavailable")
        return self.reply


class CountingClassifier:
    """Track whether the fallback was consulted at all."""

    def __init__(self, answer: bool | None) -> None:
        self.answer = answer
        self.calls = 0

    async def requires_current_information(self, query: str) -> bool | None:
        self.calls += 1
        return self.answer


def _router(classifier=None) -> CascadingSearchRouter:
    return CascadingSearchRouter(
        patterns=SearchRoutingPolicy(current_year=2026),
        classifier=classifier,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("YES", True),
        ("yes", True),
        ("Yes.", True),
        ("NO", False),
        ("no", False),
        (" no\n", False),
    ],
)
@pytest.mark.asyncio
async def test_classifier_reads_a_single_word_answer(reply, expected):
    classifier = LMStudioFreshnessClassifier(StubLLM(reply))  # type: ignore[arg-type]

    assert await classifier.requires_current_information("q") is expected


@pytest.mark.parametrize("reply", ["maybe", "", "I think it depends", "42"])
@pytest.mark.asyncio
async def test_unusable_answers_are_reported_as_undecided(reply):
    classifier = LMStudioFreshnessClassifier(StubLLM(reply))  # type: ignore[arg-type]

    # None means "no judgement", which the caller must handle explicitly.
    assert await classifier.requires_current_information("q") is None


@pytest.mark.asyncio
async def test_model_failure_is_undecided_rather_than_fatal():
    classifier = LMStudioFreshnessClassifier(StubLLM(fail=True))  # type: ignore[arg-type]

    assert await classifier.requires_current_information("q") is None


@pytest.mark.asyncio
async def test_classifier_reply_is_bounded_to_a_few_tokens():
    llm = StubLLM("YES")
    classifier = LMStudioFreshnessClassifier(llm, max_tokens=4)  # type: ignore[arg-type]

    await classifier.requires_current_information("who won today")

    prompt, max_tokens = llm.calls[0]
    # Only one word is ever needed, so the reply stays cheap.
    assert max_tokens == 4
    assert "who won today" in prompt


@pytest.mark.asyncio
async def test_pattern_match_skips_the_classifier_entirely():
    classifier = CountingClassifier(True)

    decision = await _router(classifier).decide("what is the latest python version")

    # The free path must not pay for a model call.
    assert decision.should_search is True
    assert decision.reason == "recency_term"
    assert classifier.calls == 0


@pytest.mark.asyncio
async def test_unmatched_query_is_referred_to_the_classifier():
    classifier = CountingClassifier(True)

    decision = await _router(classifier).decide("did the merger go through")

    assert decision.should_search is True
    assert decision.reason == "classifier_yes"
    assert classifier.calls == 1


@pytest.mark.asyncio
async def test_classifier_can_decline_to_search():
    classifier = CountingClassifier(False)

    decision = await _router(classifier).decide("rewrite this paragraph for me")

    assert decision.should_search is False
    assert decision.reason == "classifier_no"


@pytest.mark.asyncio
async def test_unavailable_classifier_does_not_start_searching_everything():
    classifier = CountingClassifier(None)

    decision = await _router(classifier).decide("did the merger go through")

    # An outage must not silently turn every turn into a search.
    assert decision.should_search is False
    assert decision.reason == "classifier_unavailable"


@pytest.mark.asyncio
async def test_router_without_a_classifier_falls_back_to_patterns():
    decision = await _router().decide("did the merger go through")

    assert decision.should_search is False
    assert decision.reason == "no_signal"


@pytest.mark.asyncio
async def test_settled_decisions_never_reach_the_classifier():
    classifier = CountingClassifier(True)
    disabled = CascadingSearchRouter(
        patterns=SearchRoutingPolicy(current_year=2026, enabled=False),
        classifier=classifier,  # type: ignore[arg-type]
    )

    assert (await disabled.decide("anything")).reason == "disabled"
    assert (await _router(classifier).decide("   ")).reason == "empty_query"
    assert classifier.calls == 0
