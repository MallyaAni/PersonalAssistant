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
