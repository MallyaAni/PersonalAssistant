import re
from typing import Any

# Words that describe recalling or creating an image rather than its subject;
# they must not be treated as content to match against a stored prompt.
_GENERIC_TERMS = frozenset(
    {
        "show",
        "see",
        "view",
        "display",
        "open",
        "find",
        "pull",
        "bring",
        "get",
        "give",
        "recall",
        "remember",
        "want",
        "please",
        "can",
        "could",
        "would",
        "generate",
        "generated",
        "generating",
        "create",
        "created",
        "creating",
        "make",
        "made",
        "making",
        "draw",
        "drew",
        "drawn",
        "paint",
        "painted",
        "render",
        "rendered",
        "design",
        "designed",
        "image",
        "images",
        "picture",
        "pictures",
        "photo",
        "photos",
        "pic",
        "pics",
        "visual",
        "visuals",
        "the",
        "that",
        "this",
        "these",
        "those",
        "and",
        "for",
        "with",
        "was",
        "were",
        "did",
        "does",
        "you",
        "your",
        "our",
        "one",
        "some",
        "any",
        "earlier",
        "previously",
        "previous",
        "last",
        "again",
        "now",
        "here",
    }
)


# Distinctive subject words in a recall query, such as a brand or subject name.
def content_terms(query: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", query.lower())
        if len(word) >= 3 and word not in _GENERIC_TERMS
    }


# Prefer candidates whose generation prompt contains a distinctive query term.
#
# The cross-modal image embedding clusters by broad category - every car scores
# as "a car" - so a specific query like "the porsche" cannot be resolved by
# visual distance alone. The generation prompt names the subject, so when the
# query carries distinctive terms present in some candidates' prompts, restrict
# to those; a purely descriptive query with no such term keeps the distance
# ranking unchanged.
def prefer_prompt_matches(
    query: str, ranked: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    terms = content_terms(query)
    if not terms:
        return ranked
    matched = [hit for hit in ranked if _prompt_matches(hit, terms)]
    return matched if matched else ranked


def _prompt_matches(hit: dict[str, Any], terms: set[str]) -> bool:
    prompt = str((hit.get("metadata") or {}).get("generation_prompt") or "").lower()
    return any(term in prompt for term in terms)
