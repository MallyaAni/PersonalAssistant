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

_LOCALITY_PATTERN = re.compile(
    r"\bi\s+live\s+(?:in|near)\s+([^\r\n.!?;]{1,160})",
    re.IGNORECASE,
)

_INTEREST_PATTERN = re.compile(
    r"\b(?:i(?:'m|\s+am)\s+interested\s+in|my\s+interests?\s+include)\s+"
    r"([^\r\n.!?;,]{1,80})",
    re.IGNORECASE,
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

# Unlike the proposers above, this one fires without an explicit "remember"
# trigger: it proactively notices that the user narrated something they did.
# Precision matters more than recall - a noisy proposal is an annoyance - so the
# verbs are a curated set of first-person, past-tense, experiential events, and
# the whole thing is guarded against questions and non-events below. This is the
# only proposer that captures unprompted, so it is also the lowest priority: any
# explicit intent above it wins.
_EPISODIC_TRIGGER = re.compile(
    r"\bI\s+(?:"
    r"went\s+to|visited|traveled\s+to|travelled\s+to|flew\s+to|drove\s+to|"
    r"moved\s+to|relocated\s+to|"
    r"attended|celebrated|"
    r"started\s+(?:a|an|my|working|university|college|school)\b|"
    r"joined|finished|completed|launched|shipped|published|"
    r"graduated|got\s+married|got\s+engaged|adopted|"
    r"met\s+with"
    r")",
    re.IGNORECASE,
)

# A first-person question ("how do I", "should I") is not a narrated event even
# when it contains a trigger word, so it is excluded.
_EPISODIC_QUESTION_GUARD = re.compile(
    r"\b(?:how|should|shall|can|could|would|will|do|did|when|where|why|what)\s+I\b",
    re.IGNORECASE,
)

_EPISODIC_MIN_CHARS = 15
_EPISODIC_MAX_CHARS = 300


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


# Extract an explicit home locality without persisting it.
def propose_locality(query: str) -> dict[str, str | None] | None:
    if query.strip().endswith("?"):
        return None
    match = _LOCALITY_PATTERN.search(query)
    if match is None:
        return None
    label, separator, region = match.group(1).partition(",")
    label = label.strip().strip('"')
    region = region.strip().strip('"') if separator else ""
    if not label or len(label) > 80 or len(region) > 80:
        return None
    return {"label": label, "region": region or None}


# Extract one explicitly stated interest without persisting it.
def propose_interest(query: str) -> str | None:
    match = _INTEREST_PATTERN.search(query)
    if match is None:
        return None
    label = match.group(1).strip().strip('"')
    return label if label else None


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


# Proactively propose a narrated first-person event as episodic memory, keeping
# the user's own sentence as the content, without persisting anything.
def propose_episodic(query: str) -> str | None:
    match = _EPISODIC_TRIGGER.search(query)
    if match is None:
        return None
    sentence = _sentence_around(query, match.start()).strip()
    if not _EPISODIC_MIN_CHARS <= len(sentence) <= _EPISODIC_MAX_CHARS:
        return None
    # A question that merely contains a trigger word is not a narrated event.
    if sentence.endswith("?") or _EPISODIC_QUESTION_GUARD.search(sentence):
        return None
    return sentence


# Return the single sentence of `text` that contains `index`, including its
# terminal punctuation, so an approved memory reads as the user phrased it.
def _sentence_around(text: str, index: int) -> str:
    start = 0
    for boundary in re.finditer(r"[.!?]\s+", text[:index]):
        start = boundary.end()
    tail = re.search(r"[.!?]", text[index:])
    end = index + tail.start() + 1 if tail else len(text)
    return text[start:end]


def _is_supported_name(value: str) -> bool:
    if not value or len(value) > 100 or len(value.split()) > 6:
        return False
    return all(character.isalnum() or character in " '-" for character in value)
