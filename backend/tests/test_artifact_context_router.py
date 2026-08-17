import json

import pytest

from backend.agents.memory.artifact_context import ArtifactContextRouter


class FixedWriter:
    """Return fixed modalities and record the constrained model request."""

    # Configure one deterministic router response.
    def __init__(self, modalities: list[str]) -> None:
        self.modalities = modalities
        self.calls: list[dict] = []

    # Record the semantic contract and return the configured decision.
    def chat(self, messages, max_tokens, response_schema, temperature):
        self.calls.append(
            {
                "messages": messages,
                "schema": response_schema,
                "temperature": temperature,
            }
        )
        return {"content": json.dumps({"modalities": self.modalities})}


# Keep only modalities backed by a source in the running application.
@pytest.mark.asyncio
async def test_artifact_context_router_filters_unavailable_modalities() -> None:
    writer = FixedWriter(["image", "document"])
    router = ArtifactContextRouter(writer, ("image",))

    assert await router.required_modalities("what was I wearing?") == ("image",)
    assert writer.calls[0]["temperature"] == 0.0
    assert writer.calls[0]["schema"]["required"] == ["modalities"]


# An installation with no artifact sources skips the model entirely.
@pytest.mark.asyncio
async def test_artifact_context_router_skips_when_no_modality_is_available() -> None:
    writer = FixedWriter(["image"])
    router = ArtifactContextRouter(writer, ())

    assert await router.required_modalities("what was I wearing?") == ()
    assert writer.calls == []
