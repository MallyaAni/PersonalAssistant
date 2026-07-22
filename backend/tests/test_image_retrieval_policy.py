import pytest

from backend.artifacts.image_retrieval import ImageRetrievalPolicy


def _hit(distance: float, name: str = "a") -> dict[str, object]:
    return {"id": name, "distance": distance}


@pytest.fixture
def policy() -> ImageRetrievalPolicy:
    return ImageRetrievalPolicy(max_distance=0.96, min_margin=0.015)


def test_clear_winner_is_returned(policy):
    # Observed shape of a relevant query: best pulls clearly ahead.
    ranked = [_hit(0.9110, "beach"), _hit(0.9685, "car")]

    selected = policy.select(ranked)

    assert [hit["id"] for hit in selected] == ["beach"]


def test_equidistant_results_are_rejected_as_noise(policy):
    # Observed shape of an unrelated query: everything is roughly equidistant,
    # so the nearest image is merely least-bad rather than a real match.
    ranked = [_hit(0.9518, "beach"), _hit(0.9518, "car")]

    assert policy.select(ranked) == []


def test_small_margin_below_the_threshold_is_rejected(policy):
    # 0.0107 was the largest margin any distractor produced.
    ranked = [_hit(0.9593, "city"), _hit(0.9700, "soup")]

    assert policy.select(ranked) == []


def test_genuine_weak_match_survives_on_margin_alone(policy):
    # A true match measured at 0.9531 overlaps the distractor distance band, so
    # only the margin can save it. This is why an absolute cutoff is not enough.
    ranked = [_hit(0.9531, "soup"), _hit(0.9800, "car")]

    assert [hit["id"] for hit in policy.select(ranked)] == ["soup"]


def test_hits_beyond_the_distance_ceiling_are_dropped(policy):
    ranked = [_hit(0.9100, "beach"), _hit(0.9700, "car"), _hit(0.9900, "dog")]

    selected = policy.select(ranked)

    assert [hit["id"] for hit in selected] == ["beach"]


def test_single_stored_image_falls_back_to_the_ceiling(policy):
    # With no runner up there is no margin to measure.
    assert [h["id"] for h in policy.select([_hit(0.9300, "only")])] == ["only"]
    assert policy.select([_hit(0.9900, "only")]) == []


def test_empty_input_is_handled(policy):
    assert policy.select([]) == []


def test_weak_hit_is_rejected_when_the_runner_up_is_beyond_the_ceiling(policy):
    # Regression: a distance pre-filter used to drop the runner up, leaving one
    # row that looked like a lone result and bypassed the margin check.
    ranked = [_hit(0.9593, "city"), _hit(0.9643, "soup")]

    assert policy.select(ranked) == []
