"""Reduce a typed request to the subject a diffusion model should depict.

A diffusion model has no notion of instructions. Every token is content to be
drawn, so "generate an image of a car" asks for six tokens of which only two
describe the subject. The imperative words compete for attention, the subject
lands weak, and a photoreal checkpoint resolves the slack toward its strongest
prior — which for stock-photography training data is a person. That is how a
request for a car returned a woman leaning out of one.

Stripping the preamble is not cosmetic: it changes what the sampler is asked
for. "a car" is entirely about a car.

The stored `generation_prompt` deliberately keeps the original wording. It is
the recorded intent a later refinement builds on, and it is what the person
actually said; only the provider request is narrowed.
"""

import re

# Optional politeness and framing before the real request.
_LEAD_IN = (
    r"(?:please\s+)?"
    r"(?:can\s+you\s+|could\s+you\s+|i\s+want\s+|i'd\s+like\s+"
    r"|i\s+would\s+like\s+)?"
    r"(?:please\s+)?(?:you\s+to\s+)?"
)

# "generate an image of", "draw me a picture of", "make a photo showing".
_VERB_LED = re.compile(
    rf"^\s*{_LEAD_IN}"
    r"(?:generate|create|draw|make|paint|render|design|produce|give|show)\s+"
    r"(?:me\s+)?(?:an?\s+|the\s+|some\s+)?"
    r"(?:image|picture|photo|photograph|illustration|artwork|drawing"
    r"|render|sketch|painting)s?\s*"
    r"(?:of|showing|depicting|with|for)?\s*",
    re.IGNORECASE,
)

# "image of a car" — the noun leads and no verb is present at all.
_NOUN_LED = re.compile(
    r"^\s*(?:an?\s+|the\s+)?"
    r"(?:image|picture|photo|photograph|illustration|artwork|drawing"
    r"|render|sketch|painting)s?\s+"
    r"(?:of|showing|depicting|with)\s+",
    re.IGNORECASE,
)

# A bare verb with no noun: "draw a car", "paint a sunset".
_BARE_VERB = re.compile(
    rf"^\s*{_LEAD_IN}"
    r"(?:generate|create|draw|paint|render|design|sketch)\s+"
    r"(?:me\s+)?",
    re.IGNORECASE,
)


# Return what the model should depict, or the original when nothing is left.
#
# Falling back to the original matters: "draw me a picture" names no subject, and
# an empty prompt would generate noise. A request that is only a preamble is
# better sent whole than emptied.
def subject_of(prompt: str) -> str:
    for pattern in (_VERB_LED, _NOUN_LED, _BARE_VERB):
        stripped = pattern.sub("", prompt, count=1).strip()
        if stripped and stripped != prompt.strip():
            return stripped
    return prompt.strip()
