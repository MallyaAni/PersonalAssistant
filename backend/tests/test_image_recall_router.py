import pytest

from backend.artifacts.image_recall_classifier import ImageRecallClassifier
from backend.artifacts.image_recall_router import CascadingImageRecallRouter
from backend.artifacts.image_routing import ImageRecallPolicy


class StubClassifier(ImageRecallClassifier):
    def __init__(self, answer: bool | None) -> None:
        self.answer = answer
        self.calls: list[str] = []

    async def references_stored_image(self, query: str) -> bool | None:
        self.calls.append(query)
        return self.answer


def _router(answer: bool | None) -> tuple[CascadingImageRecallRouter, StubClassifier]:
    classifier = StubClassifier(answer)
    return CascadingImageRecallRouter(ImageRecallPolicy(), classifier), classifier


@pytest.mark.asyncio
async def test_a_deterministic_match_never_consults_the_classifier() -> None:
    router, classifier = _router(True)
    decision = await router.decide("show me the car i generated earlier")
    assert decision.should_search is True
    assert decision.reason == "created_reference"
    assert classifier.calls == []


@pytest.mark.asyncio
async def test_a_creation_request_never_consults_the_classifier() -> None:
    router, classifier = _router(True)
    decision = await router.decide("generate an image of a cat")
    assert decision.should_search is False
    assert classifier.calls == []


@pytest.mark.asyncio
async def test_an_unrelated_query_is_gated_out_before_the_classifier() -> None:
    router, classifier = _router(True)
    decision = await router.decide("my name is Ani")
    assert decision.should_search is False
    assert decision.reason == "no_signal"
    assert classifier.calls == []


@pytest.mark.asyncio
async def test_a_novel_reference_defers_and_the_classifier_confirms() -> None:
    router, classifier = _router(True)
    decision = await router.decide("show me the sunset")
    assert classifier.calls == ["show me the sunset"]
    assert decision.should_search is True
    assert decision.reason == "classifier_yes"


@pytest.mark.asyncio
async def test_a_gated_query_the_classifier_rejects_does_not_search() -> None:
    router, classifier = _router(False)
    decision = await router.decide("show me the weather forecast")
    assert classifier.calls == ["show me the weather forecast"]
    assert decision.should_search is False
    assert decision.reason == "classifier_no"


@pytest.mark.asyncio
async def test_an_unavailable_classifier_falls_back_to_no_search() -> None:
    router, _ = _router(None)
    decision = await router.decide("show me the sunset")
    assert decision.should_search is False
    assert decision.reason == "no_signal"


@pytest.mark.asyncio
async def test_without_a_classifier_only_patterns_decide() -> None:
    router = CascadingImageRecallRouter(ImageRecallPolicy(), None)
    decision = await router.decide("show me the sunset")
    assert decision.should_search is False
    assert decision.reason == "no_signal"
