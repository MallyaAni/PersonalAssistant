"""The strong model answers first, and malformed JSON never reaches a caller.

The wrapper exists so the sweep's judgement calls could leave the small
grammar engine without losing its guarantee. What these pin is the contract:
a good primary answer passes through (fences and preamble tolerated, content
re-serialized so strict json.loads works), anything less - markdown, missing
keys, an exception - is re-asked of the enforcing engine with the original
untouched messages, and the format instruction reaches only the engine that
needs to be asked in words.
"""

import json
import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.core.structured_fallback import JSONFallbackWriter

_SCHEMA = {"required": ["name", "ok"], "properties": {}}
_MESSAGES = [{"role": "user", "content": "describe the thing"}]


class _Writer:
    def __init__(self, replies=None, error=None):
        self.replies = list(replies or [])
        self.error = error
        self.calls: list[list[dict]] = []

    def chat(self, messages, max_tokens=1024, response_schema=None, temperature=None):
        self.calls.append([dict(m) for m in messages])
        if self.error is not None:
            raise self.error
        return {"content": self.replies.pop(0)}


def test_a_valid_primary_answer_is_used_and_the_engine_never_called():
    primary = _Writer(['{"name": "Jazz night", "ok": true}'])
    enforced = _Writer()

    result = JSONFallbackWriter(primary, enforced).chat(_MESSAGES, 64, _SCHEMA, 0.0)

    assert json.loads(result["content"]) == {"name": "Jazz night", "ok": True}
    assert enforced.calls == []


def test_a_fenced_answer_is_extracted_rather_than_costing_a_fallback():
    primary = _Writer(['```json\n{"name": "Jazz night", "ok": true}\n```'])
    enforced = _Writer()

    result = JSONFallbackWriter(primary, enforced).chat(_MESSAGES, 64, _SCHEMA, 0.0)

    assert json.loads(result["content"]) == {"name": "Jazz night", "ok": True}
    assert enforced.calls == []


def test_markdown_prose_falls_back_to_the_enforcing_engine():
    primary = _Writer(["**Name:** Jazz night\n**Ok:** true"])
    enforced = _Writer(['{"name": "Jazz night", "ok": true}'])

    result = JSONFallbackWriter(primary, enforced).chat(_MESSAGES, 64, _SCHEMA, 0.0)

    assert json.loads(result["content"])["name"] == "Jazz night"
    assert len(enforced.calls) == 1


def test_a_missing_required_key_falls_back():
    primary = _Writer(['{"name": "Jazz night"}'])
    enforced = _Writer(['{"name": "Jazz night", "ok": true}'])

    JSONFallbackWriter(primary, enforced).chat(_MESSAGES, 64, _SCHEMA, 0.0)

    assert len(enforced.calls) == 1


def test_a_primary_exception_falls_back():
    primary = _Writer(error=RuntimeError("down"))
    enforced = _Writer(['{"name": "Jazz night", "ok": true}'])

    result = JSONFallbackWriter(primary, enforced).chat(_MESSAGES, 64, _SCHEMA, 0.0)

    assert json.loads(result["content"])["ok"] is True


# The instruction is plumbing for the engine that needs asking in words; the
# grammar engine gets the caller's messages exactly as written, or the
# instruction would double up with the grammar and drift the answer.
def test_the_format_instruction_reaches_only_the_primary():
    primary = _Writer(["not json"])
    enforced = _Writer(['{"name": "Jazz night", "ok": true}'])

    JSONFallbackWriter(primary, enforced).chat(_MESSAGES, 64, _SCHEMA, 0.0)

    assert "exactly these fields: name, ok" in primary.calls[0][-1]["content"]
    assert enforced.calls[0][-1]["content"] == "describe the thing"


# Without a schema there is no shape to ask for or check; the wrapper is a
# pass-through and the caller's prose arrives exactly as the primary wrote it.
def test_no_schema_passes_through_untouched():
    primary = _Writer(["plain prose answer"])
    enforced = _Writer()

    result = JSONFallbackWriter(primary, enforced).chat(_MESSAGES, 64, None, 0.0)

    assert result["content"] == "plain prose answer"
    assert "exactly these fields" not in primary.calls[0][-1]["content"]
    assert enforced.calls == []
