from typing import Any

from backend.artifacts.image_prompt_match import content_terms, prefer_prompt_matches


def _hit(prompt: str, name: str) -> dict[str, Any]:
    return {"id": name, "metadata": {"generation_prompt": prompt}}


def test_content_terms_keep_only_the_distinctive_subject() -> None:
    assert content_terms("show me the porsche i generated") == {"porsche"}
    assert content_terms("show me the red sports car i made") == {
        "red",
        "sports",
        "car",
    }
    # A query with no subject term yields nothing to match on.
    assert content_terms("show me the image i generated") == set()


def test_a_named_subject_narrows_to_its_own_image() -> None:
    ranked = [
        _hit("a red BMW sedan on a city street", "bmw"),
        _hit("a silver Porsche 911 on a coastal road", "porsche"),
    ]

    assert [h["id"] for h in prefer_prompt_matches("show me the porsche", ranked)] == [
        "porsche"
    ]
    assert [h["id"] for h in prefer_prompt_matches("show me the bmw", ranked)] == [
        "bmw"
    ]


def test_uploaded_image_matches_on_its_vision_description() -> None:
    # Uploads have no generation prompt, so the stored analysis provides the text.
    ranked = [
        {
            "id": "chess",
            "metadata": {"analysis": "A chess board mid-game with pieces."},
        },
        {
            "id": "elephant",
            "metadata": {"analysis": "The words PURPLE ELEPHANT on white."},
        },
    ]

    assert [
        h["id"]
        for h in prefer_prompt_matches("show me the chess board i uploaded", ranked)
    ] == ["chess"]


def test_an_uploaded_subject_matches_by_its_user_given_name() -> None:
    # A distinctive name the user supplied lives nowhere in the pixels, so it
    # must be recalled from the stored handle, not from the vision description.
    ranked = [
        {
            "id": "bird",
            "metadata": {
                "analysis": "A small grey-and-white bird on a perch.",
                "analysis_names": ["gubacchi"],
            },
        },
        {
            "id": "other",
            "metadata": {"analysis": "A vase of flowers on a table."},
        },
    ]

    assert [
        h["id"]
        for h in prefer_prompt_matches("do you know gubacchi?", ranked)
    ] == ["bird"]


def test_descriptive_query_without_a_prompt_term_keeps_the_ranking() -> None:
    ranked = [_hit("a red BMW sedan", "bmw"), _hit("a silver Porsche 911", "porsche")]

    # Neither prompt contains "sports" or "car", so the distance order is kept.
    assert prefer_prompt_matches("show me the sports car i made", ranked) == ranked


def test_no_distinctive_terms_returns_input_unchanged() -> None:
    ranked = [_hit("anything at all", "x")]
    assert prefer_prompt_matches("show me the image i generated", ranked) == ranked
