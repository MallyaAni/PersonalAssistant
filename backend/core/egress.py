import re
from dataclasses import dataclass, field

# Values that must never reach a third party under any circumstance. These
# cannot be made safe by rewording, so a query carrying one is not sent at all.
_SECRETS: tuple[tuple[str, str], ...] = (
    (r"\b(sk|pk|rk)-[A-Za-z0-9_-]{16,}\b", "credential"),
    (r"\btvly-[A-Za-z0-9_-]{8,}\b", "credential"),
    (r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{16,}\b", "credential"),
    (r"\bAKIA[0-9A-Z]{16}\b", "credential"),
    (r"\bey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "credential"),
    (r"\b(api[\s_-]?key|password|passwd|secret|bearer token)\b", "credential"),
    # Account identifiers that single out one person.
    (r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b", "account_identifier"),
    (
        r"\b(?:\+\d{1,3}[\s-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b",
        "account_identifier",
    ),
    (r"\b\d{3}-\d{2}-\d{4}\b", "account_identifier"),
    (r"\b(?:\d[ -]?){13,19}\b", "account_identifier"),
    # Precise location, as distinct from naming a city.
    (
        r"\b\d{1,5}\s+[A-Z][a-z]+\s+(street|st|avenue|ave|road|rd|lane|ln|drive|dr)\b",
        "precise_location",
    ),
    (r"\b\d{1,3}\.\d{4,},\s*-?\d{1,3}\.\d{4,}\b", "precise_location"),
)

# Personal framing around a sensitive domain. The topic itself is public
# knowledge; what identifies the user is attaching it to themselves, so these
# are minimized rather than blocked.
_PERSONAL_SENSITIVE: tuple[tuple[str, str], ...] = (
    (
        r"\b(my|our|my wife's|my husband's|my child's|my son's|my daughter's)\s+"
        # Generic clinical nouns, then named conditions: "my psoriasis" is as
        # identifying as "my diagnosis", and it is the commoner phrasing.
        r"(diagnosis|symptoms?|prescription|medication|dose|dosage|treatment|"
        r"condition|illness|disease|surgery|therapy|test results?|"
        r"cancer|diabetes|depression|anxiety|psoriasis|eczema|asthma|adhd|hiv|"
        r"migraines?|arthritis|insomnia|infection|injury|rash|pain)\b",
        "medical",
    ),
    (
        r"\b(i|we)\s+(have|has|had|was diagnosed with|am taking|take)\s+"
        r"(a\s+|an\s+|my\s+)?(diagnosis|cancer|diabetes|depression|anxiety|"
        r"psoriasis|asthma|hiv|adhd)\b",
        "medical",
    ),
    (
        r"\b(my|our)\s+(mortgage|salary|income|debt|loan|credit score|"
        r"bank|savings|pension|401k|portfolio|net worth)\b",
        "financial",
    ),
    (
        r"\b(my|our)\s+(lawsuit|case|divorce|custody|visa|immigration|"
        r"criminal record|settlement)\b",
        "legal",
    ),
)

_SECRET_PATTERNS = tuple((re.compile(p, re.IGNORECASE), c) for p, c in _SECRETS)
_PERSONAL_PATTERNS = tuple(
    (re.compile(p, re.IGNORECASE), c) for p, c in _PERSONAL_SENSITIVE
)

# First-person framing carries no search value and is what makes an otherwise
# public question identifying.
_POSSESSIVE = re.compile(
    r"\b(my|our|my wife's|my husband's|my child's)\s+", re.IGNORECASE
)
_SELF_REFERENCE = re.compile(
    r"^\s*(what should i do about|should i|do i need to|can i|how do i treat|"
    r"what can i do about|help me with)\s+",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SanitizedQuery:
    """Outcome of screening one query before it leaves the machine."""

    allowed: bool
    query: str
    categories: tuple[str, ...] = field(default=())
    minimized: bool = False

    # True when the text sent differs from what the user typed.
    @property
    def was_rewritten(self) -> bool:
        return self.minimized


class OutboundPrivacyPolicy:
    """Screens and minimizes text before it leaves the machine.

    Applies to any outbound request, not only web search: a tool argument sent
    to a third-party MCP server carries the same disclosure risk as a search
    query, and both must pass the same gate.

    Two outcomes are possible. A query containing a secret or an account
    identifier is blocked outright: no rewrite makes an API key safe to send.
    A query that merely attaches a sensitive topic to the user is minimized -
    the personal framing is removed, leaving the public question - because the
    search value lives in the topic, not in whose topic it is.

    Screening is deterministic and runs outside the model. A model asked to
    redact its own prompt can be talked out of it; a pattern cannot.
    """

    # Screen one query and return the text that may be sent, if any.
    def sanitize(self, query: str) -> SanitizedQuery:
        text = (query or "").strip()
        if not text:
            return SanitizedQuery(allowed=False, query="", categories=("empty",))

        blocked: list[str] = []
        for pattern, category in _SECRET_PATTERNS:
            if pattern.search(text):
                blocked.append(category)
        if blocked:
            # Nothing is sent, and the caller must not log the original text.
            return SanitizedQuery(
                allowed=False,
                query="",
                categories=tuple(sorted(set(blocked))),
            )

        found: list[str] = []
        for pattern, category in _PERSONAL_PATTERNS:
            if pattern.search(text):
                found.append(category)

        if not found:
            return SanitizedQuery(allowed=True, query=text)

        minimized = _SELF_REFERENCE.sub("", text)
        minimized = _POSSESSIVE.sub("", minimized)
        minimized = " ".join(minimized.split()).strip(" ?.")
        if not minimized:
            return SanitizedQuery(
                allowed=False,
                query="",
                categories=tuple(sorted(set(found))),
            )
        return SanitizedQuery(
            allowed=True,
            query=minimized,
            categories=tuple(sorted(set(found))),
            minimized=minimized != text,
        )
