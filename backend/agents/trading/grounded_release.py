"""Research-only source-grounded text features; never imported by live trading."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import validate

from backend.core.interfaces import TextWriter
from backend.core.llm import StrictSchema
from backend.market.labels import DemandTrend, FinancingRisk, GuidanceChange, values

VERSION = "grounded_release/1"
MAX_CHARS = 48_000
MAX_TOKENS = 1_200
PROMPT = Path(__file__).with_suffix(".md").read_text(encoding="utf-8")
# Each field's closed vocabulary; every one of them has a NOT_STATED word.
LABELS = {
    "guidance": GuidanceChange,
    "demand": DemandTrend,
    "financing_risk": FinancingRisk,
}
VALUES = {field: values(kind) for field, kind in LABELS.items()}


# Hash the exact UTF-8 text, including whitespace and any untrusted instructions.
def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Require all fields so the grammar cannot silently skip a hard question.
def schema() -> dict[str, Any]:
    # Sent strict, so each value is one of its field's words.
    return StrictSchema(
        {
            "title": "GroundedRelease",
            "type": "object",
            "additionalProperties": False,
            "required": list(VALUES),
            "properties": {
                field: {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["value", "quote"],
                    "properties": {
                        "value": {"type": "string", "enum": choices},
                        "quote": {
                            "type": ["string", "null"],
                            "minLength": 12,
                            "maxLength": 900,
                        },
                    },
                }
                for field, choices in VALUES.items()
            },
        }
    )


# Validate shape and exact source spans; this proves citation presence, not its meaning.
def grounded_features(payload: dict, text: str) -> dict:
    validate(payload, schema())
    features = {}
    for field, fact in payload.items():
        quote = fact["quote"]
        kind = LABELS[field]
        if kind(fact["value"]) is kind.NOT_STATED:
            if quote is not None:
                raise ValueError("Missing facts cannot carry a claimed citation")
            features[field] = {**fact, "start": None, "end": None}
            continue
        if quote is None or quote not in text:
            raise ValueError("Evidence quotation is absent from the source")
        start = text.index(quote)
        features[field] = {**fact, "start": start, "end": start + len(quote)}
    return features


# Extract once with no retries, preserving provenance and refusing silent truncation.
def extract(
    writer: TextWriter, text: str, *, published_at: datetime, model: str
) -> dict:
    if not text.strip() or len(text) > MAX_CHARS:
        raise ValueError(
            "Provide a nonempty document within the explicit character bound"
        )
    if published_at.tzinfo is None or published_at.utcoffset() is None:
        raise ValueError("Publication instant must be timezone-aware")
    if not model.strip():
        raise ValueError("A model identity is required")
    started = time.monotonic()
    result = writer.chat(
        [{"role": "system", "content": PROMPT}, {"role": "user", "content": text}],
        MAX_TOKENS,
        schema(),
        0.0,
    )
    choices = result.get("choices") or []
    if not choices or choices[0].get("finish_reason") != "stop":
        raise ValueError("Model output did not finish within the extraction bound")
    served_model = result.get("model")
    if served_model and served_model != model:
        raise ValueError("Response model differs from the requested identity")
    features = grounded_features(json.loads(result["content"]), text)
    extracted_at = datetime.now(UTC)
    return {
        "version": VERSION,
        "model": model,
        "model_checkpoint_sha": None,
        "model_training_cutoff": None,
        "source_sha256": text_hash(text),
        "prompt_sha256": text_hash(PROMPT),
        "schema_sha256": text_hash(json.dumps(schema(), sort_keys=True)),
        "extractor_sha256": text_hash(Path(__file__).read_text(encoding="utf-8")),
        "source_chars": len(text),
        "truncated": False,
        "published_at": published_at.astimezone(UTC).isoformat(),
        "extracted_at": extracted_at.isoformat(),
        "usable_after": max(published_at, extracted_at).astimezone(UTC).isoformat(),
        "features": features,
        "elapsed_seconds": time.monotonic() - started,
        "usage": result.get("usage"),
    }
