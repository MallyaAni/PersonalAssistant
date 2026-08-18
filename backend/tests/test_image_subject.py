"""The provider gets the subject, not the sentence.

A diffusion model draws every token it is given. "generate an image of a car"
spends most of its length on words describing nothing, the subject lands weak,
and a photoreal checkpoint fills the slack with its strongest prior — which is
how a request for a car came back as a woman leaning out of one.
"""

import pytest

from backend.artifacts.image_subject import subject_of


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("generate an image of a car", "a car"),
        ("please generate an image of a car", "a car"),
        ("Draw me a picture of a sunset", "a sunset"),
        ("make an illustration showing a dog", "a dog"),
        # Noun-led, no verb at all.
        ("image of a car", "a car"),
        ("a photo of the Golden Gate Bridge", "the Golden Gate Bridge"),
        # Bare verb, no noun.
        ("draw a car", "a car"),
        ("could you paint a stormy sea", "a stormy sea"),
    ],
)
def test_the_preamble_is_removed(typed: str, expected: str):
    assert subject_of(typed) == expected


def test_a_description_is_left_alone():
    # Already a subject: touching it would only risk losing detail the model
    # wants.
    described = "a red ferrari on a wet mountain road at dusk, cinematic"
    assert subject_of(described) == described


@pytest.mark.parametrize(
    "typed", ["draw me a picture", "generate an image", "make something", "draw"]
)
def test_a_request_naming_no_subject_still_sends_something(typed: str):
    # These name nothing to depict, so no stripping can find a subject. What
    # matters is that the provider never receives an empty prompt — that would
    # sample pure noise, which is worse than an unhelpfully vague request.
    assert subject_of(typed).strip() != ""


def test_the_subject_keeps_its_own_detail():
    assert subject_of("generate an image of a car in the rain, 35mm") == (
        "a car in the rain, 35mm"
    )


def test_human_detail_follows_the_models_own_answer():
    from backend.artifacts.image import ComfyUIImageProvider

    # Skin and hair wording in the global style suffix put a person in every
    # image, which is how a request for a car returned a woman leaning out of
    # one, so it has to be conditional on the subject. It used to be decided by
    # a word list that matched "my", "me", "i" and "her" among others, so "draw
    # me a picture of my car" was a person. The model that wrote the prompt now
    # states the answer and this reads it.
    provider = ComfyUIImageProvider(
        base_url="http://localhost:8188",
        model="m",
        timeout_seconds=1,
        poll_seconds=0.1,
        max_concurrency=1,
        max_output_bytes=1,
        max_pixels=1,
        text_encoder="e",
        vae="v",
        steps=4,
        style_suffix="candid snapshot",
        portrait_suffix="natural unretouched skin",
    )

    assert "natural unretouched skin" in provider._positive_prompt(
        "a woman leaning out of a car", True
    )
    assert "natural unretouched skin" not in provider._positive_prompt(
        "my car on a mountain road", False
    )
    # The style suffix is unconditional; only the human detail is not.
    assert "candid snapshot" in provider._positive_prompt("my car", False)


def test_the_style_suffix_names_no_body_parts():
    # A regression guard on configuration rather than code: this string is
    # appended to every prompt, so anything here describing a body describes a
    # subject the request may not have asked for.
    from backend.config.settings import settings

    for banned in ("skin", "hair", "pores", "face", "eyes", "smile"):
        assert banned not in settings.IMAGE_STYLE_SUFFIX.lower()
