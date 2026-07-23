"""Deterministically remove search-control wording from provider queries."""

import re

_LEADING_CONTROL = re.compile(
    r"^\s*(?:please\s+)?(?:search|browse|google|look\s+up)"
    r"(?:\s+(?:the\s+)?(?:web|internet|online))?(?:\s+for)?\s+",
    re.IGNORECASE,
)
_TRAILING_CONTROL = re.compile(
    r"\s+(?:and\s+)?(?:cite|include|provide)\s+(?:the\s+)?(?:source|sources|links?)"
    r"[.!?]*\s*$",
    re.IGNORECASE,
)


# Remove UI-style search instructions while preserving the factual subject.
def normalize_search_query(query: str) -> str:
    normalized = _LEADING_CONTROL.sub("", query.strip())
    normalized = _TRAILING_CONTROL.sub("", normalized).strip()
    return normalized or query.strip()
