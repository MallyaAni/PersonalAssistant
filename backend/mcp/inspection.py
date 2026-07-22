import re

# Instruction-shaped text has no legitimate place in a tool description. A
# description exists to say what a tool does so it can be discovered; a server
# writing imperatives aimed at the reading model is attempting tool poisoning,
# where the payload travels in metadata rather than in a result.
_INJECTION_MARKERS: tuple[tuple[str, str], ...] = (
    (
        r"\bignore\s+(all\s+|any\s+)?(previous|prior|earlier|above)\b",
        "override_attempt",
    ),
    (
        r"\bdisregard\s+(all\s+|any\s+)?(previous|prior|instructions?)\b",
        "override_attempt",
    ),
    (r"\b(system|developer)\s+prompt\b", "prompt_reference"),
    (r"<\s*/?\s*(system|assistant|user|im_start|im_end)\b", "role_marker"),
    (
        r"\byou\s+(must|should|will|are required to)\s+(always|never|call|use|run)\b",
        "imperative",
    ),
    (
        r"\b(do not|don't|never)\s+(tell|mention|inform|reveal|show)\s+the\s+user\b",
        "concealment",
    ),
    (r"\bbefore\s+(using|calling)\s+(any\s+)?other\s+tools?\b", "precedence_claim"),
    (
        r"\b(read|send|exfiltrate|upload)\s+.{0,24}(\.env|credential|secret|token|password)\b",
        "exfiltration",
    ),
)

_COMPILED = tuple(
    (re.compile(p, re.IGNORECASE), label) for p, label in _INJECTION_MARKERS
)


# Report instruction-shaped patterns found in untrusted server metadata.
# Detection is advisory: it flags a descriptor for attention rather than
# proving intent, because ordinary prose can occasionally match.
def inspect_untrusted_text(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    found = {label for pattern, label in _COMPILED if pattern.search(text)}
    return tuple(sorted(found))
