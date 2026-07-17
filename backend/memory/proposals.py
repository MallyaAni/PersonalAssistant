import re

_NAME_PATTERNS = (
    re.compile(
        r"\bmy\s+(?:preferred\s+)?name\s+is\s+([^\r\n.!?;,]{1,100})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bcall\s+me\s+([^\r\n.!?;,]{1,100})",
        re.IGNORECASE,
    ),
)


def propose_preferred_name(query: str) -> str | None:
    """Return a narrow preferred-name proposal without persisting it."""

    for pattern in _NAME_PATTERNS:
        match = pattern.search(query)
        if not match:
            continue
        candidate = match.group(1).strip().strip('"')
        if _is_supported_name(candidate):
            return candidate
    return None


def _is_supported_name(value: str) -> bool:
    if not value or len(value) > 100 or len(value.split()) > 6:
        return False
    return all(character.isalnum() or character in " '-" for character in value)
