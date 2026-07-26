import pytest

from backend.artifacts.image_retrieval import ImageRetrievalPolicy


def _hit(distance: float, name: str = "a") -> dict[str, object]:
    return {"id": name, "distance": distance}


@pytest.fixture
def policy() -> ImageRetrievalPolicy:
    return ImageRetrievalPolicy(max_distance=0.96, cluster_delta=0.006)


def test_single_clear_match_is_returned(policy):
    # One image pulls ahead and the rest are beyond the ceiling or the cluster.
    ranked = [_hit(0.9110, "beach"), _hit(0.9685, "car")]

    assert [hit["id"] for hit in policy.select(ranked)] == ["beach"]


def test_multiple_similar_images_all_return(policy):
    # The multi-image case: two red cars sit almost on top of each other, then a
    # gap to the rest. Both must return, where the old margin rejected them.
    ranked = [
        _hit(0.9310, "car_a"),
        _hit(0.9337, "car_b"),
        _hit(0.9411, "sofa"),
        _hit(0.9516, "tree"),
    ]

    assert [hit["id"] for hit in policy.select(ranked)] == ["car_a", "car_b"]


def test_the_field_beyond_the_cluster_is_excluded(policy):
    # Only the leading cluster returns, not every image within the ceiling.
    ranked = [_hit(0.9224, "match"), _hit(0.9570, "other"), _hit(0.9584, "more")]

    assert [hit["id"] for hit in policy.select(ranked)] == ["match"]


def test_hits_beyond_the_distance_ceiling_are_dropped(policy):
    ranked = [_hit(0.9100, "beach"), _hit(0.9700, "car"), _hit(0.9900, "dog")]

    assert [hit["id"] for hit in policy.select(ranked)] == ["beach"]


def test_nothing_within_the_ceiling_returns_empty(policy):
    assert policy.select([_hit(0.9700, "car"), _hit(0.9800, "dog")]) == []


def test_single_stored_image(policy):
    assert [h["id"] for h in policy.select([_hit(0.9300, "only")])] == ["only"]
    assert policy.select([_hit(0.9900, "only")]) == []


def test_cluster_is_capped_at_max_results():
    policy = ImageRetrievalPolicy(max_distance=0.96, cluster_delta=0.006, max_results=3)
    ranked = [_hit(0.930 + i * 0.001, f"img_{i}") for i in range(6)]

    # All six are within the cluster, but only the closest three are returned.
    assert [hit["id"] for hit in policy.select(ranked)] == ["img_0", "img_1", "img_2"]


def test_empty_input_is_handled(policy):
    assert policy.select([]) == []
