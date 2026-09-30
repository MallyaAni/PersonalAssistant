"""Structural guards for an offline extractor; model meaning is tested separately."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError

from backend.agents.trading import grounded_release as grounded
from backend.agents.trading.grounded_release_cases import CASES


# Make a valid response with explicit absence rather than an invented neutral score.
def absent():
    return {key: {"value": "not_stated", "quote": None} for key in grounded.VALUES}


# Mimic the inference transport, including its completion and model evidence.
def writer(payload, finish="stop", model="fixture"):
    return SimpleNamespace(
        chat=lambda *args: {
            "content": json.dumps(payload),
            "choices": [{"finish_reason": finish}],
            "model": model,
        }
    )


# A supported feature preserves exact offsets and cannot predate its extraction.
def test_quote_offsets_and_usable_time():
    text = "We raise full-year revenue guidance from $100 million to $120 million."
    payload = absent()
    payload["guidance"] = {"value": "raised", "quote": text}
    result = grounded.extract(
        writer(payload),
        text,
        published_at=datetime(2018, 1, 1, tzinfo=UTC),
        model="fixture",
    )
    fact = result["features"]["guidance"]
    assert text[fact["start"] : fact["end"]] == fact["quote"]
    assert result["usable_after"] == result["extracted_at"]
    assert result["source_sha256"] == grounded.text_hash(text)
    assert result["model_checkpoint_sha"] is None


# Invented quotes, missing quotes and citation-bearing absent facts all fail closed.
@pytest.mark.parametrize(
    ("value", "quote"),
    [
        ("raised", "This sentence is not in the document."),
        ("raised", None),
        ("not_stated", "This sentence is in the document."),
    ],
)
def test_unsupported_feature_is_rejected(value, quote):
    payload = absent()
    payload["guidance"] = {"value": value, "quote": quote}
    with pytest.raises(ValueError, match="Missing facts|Evidence quotation"):
        grounded.grounded_features(payload, "This sentence is in the document.")


# Unknown or omitted fields do not silently become valid features.
def test_schema_requires_all_and_only_declared_fields():
    payload = absent()
    payload["recommendation"] = "BUY"
    with pytest.raises(ValidationError):
        grounded.grounded_features(payload, "document")
    with pytest.raises(ValidationError):
        grounded.grounded_features({}, "document")


# Partial model output and mismatched model identity are never scored as evidence.
@pytest.mark.parametrize(
    ("finish", "model"), [("length", "fixture"), ("stop", "other")]
)
def test_incomplete_output_and_wrong_model_are_rejected(finish, model):
    with pytest.raises(ValueError, match="Model output|Response model"):
        grounded.extract(
            writer(absent(), finish, model),
            "a public release",
            published_at=datetime(2020, 1, 1, tzinfo=UTC),
            model="fixture",
        )


# Oversize inputs fail before inference instead of dropping a late risk disclosure.
def test_oversize_input_is_not_silently_truncated():
    with pytest.raises(ValueError, match="character bound"):
        grounded.extract(
            None,
            "x" * (grounded.MAX_CHARS + 1),
            published_at=datetime.now(UTC),
            model="fixture",
        )
    late = next(case for case in CASES if case["id"] == "late_evidence")
    assert 24_000 < late["text"].index("We lower") < grounded.MAX_CHARS
    assert len(CASES) == 8
