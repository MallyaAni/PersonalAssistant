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

from backend.agents.graph import _build_system_prompt, turn_context_messages

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
            "edited_from": {
                "supplied_by_user": True,
                "title": "Uploaded image",
                "description": _ORIGINAL,
            },
            "edits_applied": ["edit this to give me a straw hat"],
        }
    ]
}

# Denial is the failure being measured, in the forms it actually took. Scoped
# to the picture/memory itself - a bare "don't have" also matches an honest,
# unrelated hedge ("I don't have information about your current location"),
# which read as a false failure on a query that also asks where a physical
# object ended up, something no photo can answer.
_DENIALS = (
    "don't have that image",
    "don't have the image",
    "do not have that image",
    "do not have the image",
    "don't see",
    "do not see",
    "not in my memory",
    "no access",
    "cannot find",
    "can't find",
    "i don't recall",
)


def _answer(llm: object, query: str, context: dict | None = None) -> str:
    chosen = context or _CONTEXT
    result = llm.chat(  # type: ignore[attr-defined]
        [
            {"role": "system", "content": _build_system_prompt(chosen)},
            # Under cache-aware ordering the recalled-images block travels in
            # its own message after the history; without it the model never
            # sees the lineage these tests exist to exercise.
            *turn_context_messages(chosen),
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


# The reported failure, verbatim: asked for beach recommendations with a
# recalled outfit but no location anywhere in context (no profile, no
# memory, no search results, nothing earlier in the conversation), the
# assistant answered "Do you have a preferred proximity to a city (like
# Milwaukee, where you seem based)" - a specific, confident claim about
# where the user lives that had no source anywhere in its context.
async def test_it_does_not_invent_the_users_location(llm: object) -> None:
    answer = _answer(
        llm,
        "based on my style do you have beach recommendations?",
        {
            "images": [
                {
                    "kind": "uploaded_image",
                    "title": "Uploaded image",
                    "created_at": "2026-08-13T17:41:00",
                    "description": (
                        "The user is wearing a dark zip-up bomber jacket over "
                        "a white t-shirt, paired with a black cowboy hat, "
                        "suggesting a rugged, outdoorsy style."
                    ),
                    "generation_prompt": None,
                }
            ]
        },
    )

    assertive_location_claims = (
        "where you seem based",
        "where you live",
        "where you're based",
        "where you are based",
        "since you're in",
        "since you live in",
        "you're based in",
        "you live in",
    )
    assert not any(phrase in answer for phrase in assertive_location_claims), answer


# An unobserved edit still carries the explicit delta and unchanged source
# details. Originally xfailed for exactly the reason below, then passing
# consistently (3/3 real-model runs) once an anti-hallucination instruction was
# added alongside it. It has regressed since the chat role moved to DeepSeek:
# 5/5 runs on 2026-08-17 answered with the origin's black cowboy hat, ignoring
# the straw-hat edit the description states, and the same 5/5 reproduce on an
# unmodified tree. Marked expected-to-fail rather than deleted, so the day a
# model gets this right the run reports it as an unexpected pass instead of
# silently keeping a green tick nobody earned.
@pytest.mark.xfail(
    reason=(
        "The chat model prefers the origin's black hat over an explicit "
        "straw-hat edit when post-edit vision observation is unavailable"
    ),
    strict=False,
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
