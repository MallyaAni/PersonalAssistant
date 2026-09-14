"""A bounded model judgement over dated facts, with no sizing authority."""

import json
from pathlib import Path

VERSION = "desk-economist/1"
SYSTEM = Path(__file__).with_suffix(".md").read_text(encoding="utf-8")


# Constrain interpretation and references to the supplied evidence.
def assess(facts: list[dict], writer) -> dict:
    usable = [fact for fact in facts if fact.get("status") == "available"]
    ids = [fact["id"] for fact in usable]
    schema = {
        "title": "InflationContext",
        "type": "object",
        "additionalProperties": False,
        "required": ["pressure", "evidence_ids"],
        "properties": {
            "pressure": {
                "type": "string",
                "enum": ["easing", "building", "mixed", "unknown"],
            },
            "evidence_ids": {
                "type": "array",
                "maxItems": len(ids),
                "items": {"type": "string", "enum": ids or ["none"]},
            },
        },
    }
    fallback = {
        "pressure": "unknown",
        "evidence_ids": [],
        "prompt_version": VERSION,
        "status": "unavailable",
    }
    if writer is None:
        return fallback
    try:
        response = writer.chat(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(usable)},
            ],
            600,
            schema,
            0.0,
        )
        result = json.loads(response["content"])
        if result["pressure"] not in ("easing", "building", "mixed", "unknown"):
            return fallback
        if not isinstance(result["evidence_ids"], list) or not set(
            result["evidence_ids"]
        ).issubset(ids):
            return fallback
        if result["pressure"] != "unknown" and not result["evidence_ids"]:
            return fallback
        result["evidence_ids"] = list(dict.fromkeys(result["evidence_ids"]))
        return {**result, "prompt_version": VERSION, "status": "model_assessment"}
    except Exception as exc:  # noqa: BLE001 - unavailable inference is unknown
        return {**fallback, "failure_type": type(exc).__name__}
