import json

import pytest

from backend.agents.vision.memory import VisualMemorySelector


class FixedWriter:
    """Return one fixed structured selection and record the model contract."""

    def __init__(self, artifact_ids: list[str]) -> None:
        self.artifact_ids = artifact_ids
        self.calls: list[dict] = []

    # Record the grammar-constrained call and return its configured identifiers.
    def chat(self, messages, max_tokens, response_schema, temperature):
        self.calls.append(
            {
                "messages": messages,
                "schema": response_schema,
                "temperature": temperature,
            }
        )
        return {"content": json.dumps({"artifact_ids": self.artifact_ids})}


# The selector may return only identifiers from the user-scoped candidate set.
@pytest.mark.asyncio
async def test_visual_selector_rejects_model_invented_identifiers() -> None:
    writer = FixedWriter(["owned", "invented"])
    selected = await VisualMemorySelector(writer).select(
        "what do you think of my style?",
        [
            {
                "content": "A person in a tailored navy jacket.",
                "extra_data": {"artifact_id": "owned"},
            }
        ],
    )

    assert selected == ("owned",)
    assert writer.calls[0]["temperature"] == 0.0
    assert writer.calls[0]["schema"]["additionalProperties"] is False


# No owned candidates means no model call and no possible visual disclosure.
@pytest.mark.asyncio
async def test_visual_selector_skips_an_empty_candidate_set() -> None:
    writer = FixedWriter(["invented"])
    assert await VisualMemorySelector(writer).select("hello", []) == ()
    assert writer.calls == []
