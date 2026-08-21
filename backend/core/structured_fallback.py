"""The best model answers first; the enforcing engine answers when it can't.

Every schema-shaped call in the sweep used to go straight to the grammar
engine, because grammar is the only guarantee the deployed prose harness
offers none of. The cost was quality: the small enforcing model wrote the
aim, the ordering, and for a day the descriptions, and the first judged real
delivery showed what that reads like. This wrapper inverts the priority
without giving up the guarantee - the strong model is asked for JSON in
words and its answer is checked in code, and only an answer that fails the
check is re-asked of the engine that cannot produce a malformed one.

The check here is deliberately shallow: does it parse, is it an object, are
the schema's required keys present. Field-level meaning stays with the
caller - every caller of TextWriter already validates its payload (pydantic
models, date parses) and falls back deterministically, and duplicating that
here would drift from it.
"""

import json
from typing import Any

from backend.core.interfaces import TextWriter


# The shape, asked for in words, for an engine that enforces nothing. Built
# from the schema so a caller's new field is asked for without anyone
# remembering to update a string here.
def _format_instruction(response_schema: dict[str, Any] | None) -> str:
    if not response_schema:
        return ""
    required = response_schema.get("required")
    fields = ", ".join(str(name) for name in required) if required else "the schema's"
    return (
        "\n\nAnswer with only a JSON object - no code fence, no text around "
        f"it - with exactly these fields: {fields}."
    )


# The JSON object in the reply carrying every required key, re-serialized so
# callers' strict json.loads always succeeds - or None, which means the
# enforcing engine answers instead. A fence or a sentence of preamble around
# the object is tolerated the same way the eval judge tolerates it: an
# otherwise-correct answer must not cost a fallback call. Anything beyond
# presence of the keys is the caller's judgement.
def _extract_required(
    content: str, response_schema: dict[str, Any] | None
) -> str | None:
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        payload = json.loads(content[start : end + 1])
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    required = (response_schema or {}).get("required") or ()
    if not all(name in payload for name in required):
        return None
    return json.dumps(payload)


class JSONFallbackWriter:
    """A TextWriter that prefers the strong model and never returns malformed JSON."""

    def __init__(self, primary: TextWriter, enforced: TextWriter) -> None:
        self.primary = primary
        self.enforced = enforced

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        asked = [dict(message) for message in messages]
        if asked and response_schema is not None:
            asked[-1]["content"] = asked[-1].get("content", "") + _format_instruction(
                response_schema
            )
        try:
            result = self.primary.chat(asked, max_tokens, response_schema, temperature)
            if response_schema is None:
                return result
            extracted = _extract_required(
                str(result.get("content", "")), response_schema
            )
            if extracted is not None:
                return {**result, "content": extracted}
        except Exception:
            # The primary being down is the fallback's oldest reason to exist.
            pass
        return self.enforced.chat(messages, max_tokens, response_schema, temperature)
