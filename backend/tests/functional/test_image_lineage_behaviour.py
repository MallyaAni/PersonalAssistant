"""Does an edited photograph still remember what the user actually gave us?

Editing an uploaded picture produces a `generated_image` titled "Edited image",
and recall collapses the upload it came from so the same picture is not offered
twice. Everything the upload knew went with it. Asked "remember the picture I
gave you of my hat? where can I find that hat?", the assistant answered that the
only image on record was one it had generated from a creative request — about a
photograph the user had supplied twenty minutes earlier, whose stored
description named the hat.

The lineage now travels with the surviving revision. These measure what the
model does with it, because the fields could just as easily be ignored, or read
as describing the edited picture rather than the original.
"""

import pytest

from backend.agents.graph import _build_system_prompt

pytestmark = pytest.mark.asyncio

_ORIGINAL = (
    "The image shows a man standing outdoors, smiling gently at the camera. "
    "He is wearing a wide-brimmed black cowboy hat and a dark blue bomber-style "
    "jacket. Behind him is a calm body of water reflecting the light of sunset."
)
_EDITED = (
    "This picture shows a man standing outdoors near water at sunset. He is "
    "wearing a light-coloured woven straw hat with a wide brim, a dark "
    "bomber-style jacket, and a white crew-neck t-shirt."
)

_CONTEXT = {
    "images": [
        {
            "kind": "generated_image",
            "title": "Edited image",
            "created_at": "2026-08-11T22:46:57",
            "description": _EDITED,
            "generation_prompt": None,
            "freshly_shown": True,
            "edited_from": {
                "supplied_by_user": True,
                "title": "Uploaded image",
                "description": _ORIGINAL,
            },
            "edits_applied": ["edit this to give me a straw hat"],
        }
    ]
}

# Denial is the failure being measured, in the forms it actually took.
_DENIALS = (
    "don't have",
    "do not have",
    "don't see",
    "do not see",
    "not in my memory",
    "no access",
    "cannot find",
    "can't find",
    "i don't recall",
)


def _answer(llm: object, query: str, context: dict | None = None) -> str:
    result = llm.chat(  # type: ignore[attr-defined]
        [
            {"role": "system", "content": _build_system_prompt(context or _CONTEXT)},
            {"role": "user", "content": query},
        ],
        400,
        None,
        0.0,
    )
    return str(result["content"]).casefold()


# The question that exposed this, verbatim. The hat the user is asking about is
# the one in the picture they supplied, which only the lineage still knows.
async def test_it_recalls_the_hat_from_the_photograph_the_user_supplied(
    llm: object,
) -> None:
    answer = _answer(
        llm,
        "remember the picture i gave you of my hat? where can i find that hat?",
    )

    assert "cowboy" in answer or "black" in answer, answer
    assert not any(denial in answer for denial in _DENIALS), answer


# The other half of the same failure: the picture was described as the
# assistant's own invention, to the person who had photographed it.
async def test_it_does_not_call_the_users_photograph_something_it_invented(
    llm: object,
) -> None:
    answer = _answer(llm, "where did that hat picture come from?")

    assert "upload" in answer or "you " in answer or "your" in answer, answer
    assert "creative request" not in answer, answer


# The original's description must not be read as what the picture shows now.
# Both hats are in the context, and only the order of events tells them apart.
async def test_it_keeps_the_original_and_the_edit_distinct(llm: object) -> None:
    answer = _answer(
        llm,
        "what hat was in the photo before you edited it, and what is in it now?",
    )

    cowboy_first = answer.find("cowboy")
    straw_first = answer.find("straw")
    assert cowboy_first != -1, answer
    assert straw_first != -1, answer
    # The original is named before the edit that replaced it, which is the only
    # thing distinguishing "it was, then became" from "it is".
    assert cowboy_first < straw_first, answer


# An ordinary generated image has no lineage, and none should be implied.
async def test_a_plain_generated_image_is_not_described_as_an_edit(
    llm: object,
) -> None:
    answer = _answer(
        llm,
        "what was that car picture?",
        {
            "images": [
                {
                    "kind": "generated_image",
                    "title": "Generated image",
                    "created_at": "2026-08-11T20:00:00",
                    "description": "A cobalt blue sports car on a wet road.",
                    "generation_prompt": "a cobalt blue sports car",
                    "freshly_shown": True,
                }
            ]
        },
    )

    assert "cobalt" in answer or "blue" in answer, answer
    assert "photograph you" not in answer, answer
    assert "you uploaded" not in answer, answer


# A recalled outfit should produce a grounded opinion, not a claim of blindness.
async def test_it_answers_a_style_opinion_from_the_recalled_photo(llm: object) -> None:
    answer = _answer(
        llm,
        "how do you feel about my dress style?",
        {
            "images": [
                {
                    "kind": "uploaded_image",
                    "title": "Uploaded image",
                    "created_at": "2026-08-12T04:10:00",
                    "description": (
                        "The user is wearing a wide-brimmed black cowboy hat, "
                        "a dark blue bomber jacket, and a white T-shirt. The "
                        "outfit has a confident, relaxed Western-casual look."
                    ),
                    "generation_prompt": None,
                    "freshly_shown": True,
                }
            ]
        },
    )

    assert "hat" in answer or "jacket" in answer, answer
    assert any(
        quality in answer
        for quality in ("confident", "relaxed", "western", "casual", "stylish")
    ), answer
    assert not any(denial in answer for denial in _DENIALS), answer


# The application withholds a repeat attachment when the same picture was
# already shown earlier in this conversation - see conversation_service.py's
# `_stream_retrieved_context` dedup. The model still has the description, but
# must not tell the user a picture just appeared when nothing did.
async def test_a_repeated_recall_is_not_announced_as_freshly_shown(
    llm: object,
) -> None:
    answer = _answer(
        llm,
        "remind me what I was wearing in that photo",
        {
            "images": [
                {
                    "kind": "uploaded_image",
                    "title": "Uploaded image",
                    "created_at": "2026-08-12T04:10:00",
                    "description": (
                        "The user is wearing a wide-brimmed black cowboy hat, "
                        "a dark blue bomber jacket, and a white T-shirt. The "
                        "outfit has a confident, relaxed Western-casual look."
                    ),
                    "generation_prompt": None,
                    "freshly_shown": False,
                }
            ]
        },
    )

    assert "hat" in answer or "jacket" in answer, answer
    assert not any(denial in answer for denial in _DENIALS), answer
    claimed_new_attachment = any(
        phrase in answer
        for phrase in (
            "just shown",
            "just attached",
            "just appeared",
            "shown above",
            "shown below",
            "here's the image",
            "here is the image",
            "i've attached",
            "i have attached",
        )
    )
    assert not claimed_new_attachment, answer


# An unobserved edit still carries the explicit delta and unchanged source details.
@pytest.mark.xfail(
    reason=(
        "Qwen can still prefer the origin's black hat over an explicit straw-hat "
        "edit when post-edit vision observation is unavailable"
    ),
    strict=True,
)
async def test_style_opinion_applies_the_edit_to_the_source_description(
    llm: object,
) -> None:
    context = {
        "images": [
            {
                **_CONTEXT["images"][0],
                "description": (
                    "The current image shows these completed edits: edit this "
                    "to give me a straw hat. All unmentioned visible details "
                    "remain as recorded in edited_from.description."
                ),
            }
        ]
    }

    answer = _answer(llm, "how do you feel about my dress style?", context)

    assert "straw" in answer, answer
    assert "jacket" in answer or "shirt" in answer, answer
    assert "please upload" not in answer, answer
    assert "upload an image" not in answer, answer
    assert "share a photo" not in answer, answer
    assert not any(denial in answer for denial in _DENIALS), answer
