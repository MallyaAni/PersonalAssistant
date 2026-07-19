import re
from typing import Any

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

_RESPONSE_STYLE_PATTERNS = (
    (
        re.compile(
            r"\b(?:please\s+)?(?:be|keep\s+(?:your\s+)?responses?)\s+concise\b",
            re.IGNORECASE,
        ),
        "concise",
    ),
    (
        re.compile(
            r"\bi\s+prefer\s+(?:your\s+)?(?:responses?\s+to\s+be\s+)?concise\b",
            re.IGNORECASE,
        ),
        "concise",
    ),
    (
        re.compile(
            r"\b(?:please\s+)?(?:be|make\s+(?:your\s+)?responses?)\s+detailed\b",
            re.IGNORECASE,
        ),
        "detailed",
    ),
    (
        re.compile(
            r"\bi\s+prefer\s+(?:your\s+)?(?:responses?\s+to\s+be\s+)?detailed\b",
            re.IGNORECASE,
        ),
        "detailed",
    ),
)

_ENTITY_PATTERN = re.compile(
    r"\bremember\s+that\s+([^\r\n.!?;]{1,300})\s+is\s+my\s+" r"([^\r\n.!?;]{1,100})",
    re.IGNORECASE,
)

_PROCEDURE_PATTERN = re.compile(
    r"\bremember\s+(?:this\s+)?(?:workflow|procedure)\s*:\s*"
    r"([^\r\n.!?;]{1,200})[.!]?\s+steps?\s*:\s*([^\r\n]{1,5000})",
    re.IGNORECASE,
)

_KNOWLEDGE_PATTERN = re.compile(
    r"\bremember\s+(?:this\s+)?(?:reference|knowledge)\s*:\s*"
    r"([^\r\n|]{1,500})\|\s*([^\r\n]{1,10000})",
    re.IGNORECASE,
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


# Extract an explicit response-style preference without persisting it.
def propose_response_style(query: str) -> str | None:
    """Return a narrow response-style proposal without persisting it."""

    for pattern, style in _RESPONSE_STYLE_PATTERNS:
        if pattern.search(query):
            return style
    return None


# Extract an explicitly stated person or organization without persisting it.
def propose_entity(query: str) -> dict[str, Any] | None:
    match = _ENTITY_PATTERN.search(query)
    if match is None:
        return None
    name = match.group(1).strip().strip('"')
    relationship = match.group(2).strip().strip('"')
    if not name or not relationship:
        return None
    return {
        "entity_type": "person",
        "canonical_name": name,
        "attributes": {"relationship": relationship},
    }


# Extract an explicit semicolon-delimited workflow without persisting it.
def propose_procedure(query: str) -> dict[str, Any] | None:
    match = _PROCEDURE_PATTERN.search(query)
    if match is None:
        return None
    name = match.group(1).strip().strip('"')
    instructions = [part.strip() for part in match.group(2).split(";")]
    instructions = [part.rstrip(". ") for part in instructions if part.strip()]
    if not name or len(instructions) < 2:
        return None
    return {
        "name": name,
        "description": f"User-approved workflow: {name}",
        "steps": [
            {"order": index, "instruction": instruction}
            for index, instruction in enumerate(instructions, start=1)
        ],
    }


# Extract an explicit titled reference without persisting it.
def propose_knowledge(query: str) -> dict[str, str] | None:
    match = _KNOWLEDGE_PATTERN.search(query)
    if match is None:
        return None
    title = match.group(1).strip().strip('"')
    content = match.group(2).strip().strip('"')
    if not title or not content:
        return None
    return {"title": title, "content": content}


def _is_supported_name(value: str) -> bool:
    if not value or len(value) > 100 or len(value.split()) > 6:
        return False
    return all(character.isalnum() or character in " '-" for character in value)
