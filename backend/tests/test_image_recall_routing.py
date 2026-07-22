import pytest

from backend.artifacts.image_routing import ImageRecallPolicy


@pytest.fixture
def policy() -> ImageRecallPolicy:
    return ImageRecallPolicy()


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ("show me my pictures of a fox", "explicit_recall"),
        ("find the photo with the red car", "explicit_recall"),
        ("do i have any images of butterflies", "ownership_question"),
        ("which image had the wooden table", "which_image"),
        ("the picture of my dog", "descriptive_reference"),
        ("open my photos", "possessive"),
    ],
)
def test_recall_requests_route_to_image_search(policy, query, reason):
    decision = policy.decide(query)

    assert decision.should_search is True
    assert decision.reason == reason


@pytest.mark.parametrize(
    "query",
    [
        "generate a picture of a fox",
        "create an image of a mountain",
        "draw me a photo of a cat",
        "make a picture of the sea",
    ],
)
def test_creation_requests_never_return_an_old_image(policy, query):
    decision = policy.decide(query)

    # A request to produce something new must not be answered with an archive hit.
    assert decision.should_search is False
    assert decision.reason == "creation_request"


@pytest.mark.parametrize(
    "query",
    [
        "what is the capital of France",
        "summarise our last conversation",
        "explain how embeddings work",
    ],
)
def test_unrelated_queries_do_not_search_images(policy, query):
    assert policy.decide(query).should_search is False


def test_blank_and_disabled_paths_never_search():
    enabled = ImageRecallPolicy()
    disabled = ImageRecallPolicy(enabled=False)

    assert enabled.decide("   ").reason == "empty_query"
    assert disabled.decide("show me my pictures").should_search is False
    assert disabled.decide("show me my pictures").reason == "disabled"
