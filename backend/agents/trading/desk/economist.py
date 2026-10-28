"""A bounded model judgement over dated facts, with no sizing authority."""

import json
from pathlib import Path

from backend.core.llm import StrictSchema
from backend.market.labels import InflationPressure, values

VERSION = "desk-economist/1"
SYSTEM = Path(__file__).with_suffix(".md").read_text(encoding="utf-8")


# Constrain interpretation and references to the supplied evidence.
def assess(facts: list[dict], writer) -> dict:
    usable = [fact for fact in facts if fact.get("status") == "available"]
    ids = [fact["id"] for fact in usable]
    # Sent strict: the engine can only answer one of the pressure words.
    schema = StrictSchema(
        {
            "title": "InflationContext",
            "type": "object",
            "additionalProperties": False,
            "required": ["pressure", "evidence_ids"],
            "properties": {
                "pressure": {
                    "type": "string",
                    "enum": values(InflationPressure),
                },
                "evidence_ids": {
                    "type": "array",
                    "maxItems": len(ids),
                    "items": {"type": "string", "enum": ids or ["none"]},
                },
            },
        }
    )
    fallback = {
        "pressure": InflationPressure.UNKNOWN,
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
        # A pressure outside the vocabulary is not a reading: the fallback, as before.
        if result["pressure"] not in InflationPressure:
            return fallback
        result["pressure"] = InflationPressure(result["pressure"])
        if not isinstance(result["evidence_ids"], list) or not set(
            result["evidence_ids"]
        ).issubset(ids):
            return fallback
        if (
            result["pressure"] is not InflationPressure.UNKNOWN
            and not result["evidence_ids"]
        ):
            return fallback
        result["evidence_ids"] = list(dict.fromkeys(result["evidence_ids"]))
        return {**result, "prompt_version": VERSION, "status": "model_assessment"}
    except Exception as exc:  # noqa: BLE001 - unavailable inference is unknown
        return {**fallback, "failure_type": type(exc).__name__}
