"""Reasoning pass that answers an image question with the main model.

The vision model is the only thing here that can see pixels, but it is chosen
for describing them, not for reasoning about them - so a question that needs
judgement, comparison, or inference was previously answered at whatever
reasoning ability the VLM happened to have. This module keeps the VLM as the
eyes and hands the reasoning to the main conversational model, which is the
strongest model configured.

Nothing here looks at the image. The neutral observation comes from the vision
model, and the prompt forbids going beyond it, so the reasoning step cannot
promote the VLM's separate question-specific guesses into visual facts.
"""

from backend.core.prompts import load

VISUAL_REASONING_PROMPT = load("vision/reason").strip()


# Assemble the reasoning turn from neutral visual and optional web evidence.
#
# Kept as a function so the exact wording is testable without a live model, and
# so question-specific VLM guesses never become evidence for a second model.
# The service may still return that answer as a resilience fallback when the
# reasoner is unavailable, but the normal final answer starts from the durable
# neutral observation and independently sourced web evidence only.
def build_reasoning_messages(
    question: str,
    observation: str,
    search_results: str | None = None,
    # Each candidate the vision pass proposed, with the confidence it assigned.
    # Passed separately from the neutral description because these are readings
    # rather than observations, and the answer must keep that distinction while
    # still reporting them.
    candidates: list[dict[str, str]] | None = None,
    # Where the user has said they live, when they have said it. A regional
    # prior is most of what separates "some silvery fish" from a name: the same
    # pixels are a different shortlist in Mumbai and in Maine.
    stated_locality: str = "",
) -> list[dict[str, str]]:
    sections = [f"Notes describing the image:\n{observation.strip()}"]
    if stated_locality.strip():
        sections.append(
            "Where this user has told the application they live. This is "
            "where they are, not where they are from, and says nothing about "
            "their cuisine or background - a weak hint about local "
            f"availability only, never a reason to rule a candidate out:\n"
            f"{stated_locality.strip()}"
        )
    if candidates:
        listed = "\n".join(
            f"- {item.get('label', '')} (confidence: {item.get('confidence', '')})"
            f" - basis: {item.get('basis', '')}"
            for item in candidates
            if str(item.get("label") or "").strip()
        )
        if listed:
            sections.append(
                "Candidate identifications proposed by the model that saw the "
                f"image, with its own confidence in each:\n{listed}"
            )
        else:
            sections.append(
                "Candidate identifications proposed by the model that saw the "
                "image: NONE. Do not name any candidate."
            )
    else:
        sections.append(
            "Candidate identifications proposed by the model that saw the image: "
            "NONE. Do not name any species, breed, person, place, make, model, or "
            "other identity from general knowledge."
        )
    if search_results and search_results.strip():
        # Labelled unambiguously as outside evidence. Presented as another kind
        # of note, the model starts reporting search findings as things it saw.
        sections.append(
            "Web search results about the wider world, NOT observations of this "
            f"image:\n{search_results.strip()}"
        )
    sections.append(
        f"The user's question:\n{question.strip()}\n\n"
        "Now answer from the neutral description first. If candidate "
        "identifications are listed above, give the supported ones at the "
        "confidence assigned by the visual inspection, most confident first. "
        "If the candidate section says NONE, name none. Never present an "
        "uncertain candidate as settled. If any reported candidate is still "
        "unsettled, finish with a single direct question whose answer would "
        "most narrow it - where it came from, where it was bought, or the "
        "cuisine or region it is for. Ask that question outright as your last "
        "line; do not merely say a clearer photograph would help."
    )
    return [
        {"role": "system", "content": VISUAL_REASONING_PROMPT},
        {"role": "user", "content": "\n\n".join(sections)},
    ]
