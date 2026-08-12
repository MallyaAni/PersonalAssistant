"""Routing an upload on what the words meant, without calling a model.

The functional suite measures whether the model classifies English correctly.
This measures the wiring around it: that the answer changes what the vision
model is asked, that it reaches the caller, and that losing the classifier
degrades to the behaviour this path had before it existed.
"""

import json
from typing import Any

import pytest

from backend.artifacts.types import VisionAnalysis
from backend.agents.vision.observation import CANONICAL_OBSERVATION_PROMPT
from backend.services.image_intent import ImageIntentClassifier
from backend.services.vision_analysis_service import VisionAnalysisService


class FakeWriter:
    """Answer with a fixed intent, or fail, without reaching a runtime."""

    def __init__(self, intent: str | None = "ask", fail: bool = False) -> None:
        self.intent = intent
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, max_tokens=1024, response_schema=None, temperature=None):
        self.calls.append(
            {
                "prompt": messages[0]["content"],
                "schema": response_schema,
                "temperature": temperature,
            }
        )
        if self.fail:
            raise RuntimeError("inference runtime unreachable")
        return {"content": json.dumps({"intent": self.intent})}


class StubImages:
    async def store_upload(self, user_id, conversation_id, trace_id, content, mime):
        artifact = {
            "id": "11111111-1111-4111-8111-111111111111",
            "conversation_id": conversation_id,
            "kind": "uploaded_image",
            "mime_type": "image/png",
        }
        return artifact, content


class StubRepository:
    async def update_metadata(self, artifact_id, user_id, metadata):
        return {"id": artifact_id, "kind": "uploaded_image", "metadata": metadata}


class RecordingVision:
    """Remember what question the upload was actually put to."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    async def analyze(self, prompt, content, mime_type):
        self.asked.append(prompt)
        content = (
            "A person wearing a navy jacket and white shirt outdoors."
            if prompt != "what is written on the sign?"
            else "The sign says DANCE TONIGHT."
        )
        return VisionAnalysis(content=content, model="test", metadata={})


async def _analyze(prompt: str, intent: str | None, fail: bool = False):
    vision = RecordingVision()
    service = VisionAnalysisService(
        StubImages(),
        StubRepository(),
        vision,
        intent=ImageIntentClassifier(FakeWriter(intent, fail)),
    )
    result = await service.analyze_upload(
        user_id="u",
        conversation_id="22222222-2222-4222-8222-222222222222",
        trace_id="t",
        prompt=prompt,
        content=b"bytes",
        declared_mime_type="image/png",
    )
    return vision, result


pytestmark = pytest.mark.asyncio


# The edit request must not be put to the vision model. Asked as a question it
# answers that it cannot edit images, and that refusal was then stored as the
# description of the picture the user had just uploaded.
async def test_an_edit_request_is_not_the_question_put_to_the_vision_model() -> None:
    vision, result = await _analyze("give me a straw hat", "edit")
    assert len(vision.asked) == 1
    assert vision.asked[0] == CANONICAL_OBSERVATION_PROMPT
    assert result["intent"] == "edit"


# A genuine question still reaches the vision model as the user wrote it.
async def test_a_question_is_put_to_the_vision_model_unchanged() -> None:
    vision, result = await _analyze("what is written on the sign?", "ask")
    assert len(vision.asked) == 2
    assert vision.asked[0] == CANONICAL_OBSERVATION_PROMPT
    assert vision.asked[1] == "what is written on the sign?"
    assert result["analysis"] == "The sign says DANCE TONIGHT."
    assert result["artifact"]["metadata"]["analysis"] == (
        "A person wearing a navy jacket and white shirt outdoors."
    )
    assert result["artifact"]["metadata"]["analysis_thread"] == [
        {
            "prompt": "what is written on the sign?",
            "answer": "The sign says DANCE TONIGHT.",
            "model": "test",
        }
    ]
    assert result["intent"] == "ask"


# The upload is what the user is waiting on. An unreachable classifier must
# still store and describe the picture rather than fail the request.
async def test_a_classifier_failure_still_analyzes_the_upload() -> None:
    vision, result = await _analyze("give me a straw hat", None, fail=True)
    assert len(vision.asked) == 2
    assert vision.asked[0] == CANONICAL_OBSERVATION_PROMPT
    assert vision.asked[1] == "give me a straw hat"
    assert result["intent"] == "ask"
    assert result["artifact"]["metadata"]["analysis"] == (
        "A person wearing a navy jacket and white shirt outdoors."
    )


# No classifier still separates reusable observation from the immediate answer.
async def test_no_classifier_keeps_the_question_out_of_canonical_memory() -> None:
    vision = RecordingVision()
    service = VisionAnalysisService(StubImages(), StubRepository(), vision)
    result = await service.analyze_upload(
        user_id="u",
        conversation_id="22222222-2222-4222-8222-222222222222",
        trace_id="t",
        prompt="describe this",
        content=b"bytes",
        declared_mime_type="image/png",
    )
    assert len(vision.asked) == 2
    assert vision.asked[0] == CANONICAL_OBSERVATION_PROMPT
    assert vision.asked[1] == "describe this"
    assert result["intent"] == "ask"


# Greedy, and constrained to two words. A classifier that could answer anything
# else would put unvalidated model output into a routing decision.
async def test_the_call_is_greedy_and_constrained_to_the_two_answers() -> None:
    writer = FakeWriter("edit")
    assert await ImageIntentClassifier(writer).edits_the_image("a straw hat") is True
    call = writer.calls[0]
    assert call["temperature"] == 0.0
    assert call["schema"]["properties"]["intent"]["enum"] == ["edit", "ask"]
    assert call["schema"]["additionalProperties"] is False


# A short reply is interpreted using the bounded conversation about this image.
async def test_recent_image_context_is_included_for_ambiguous_followups() -> None:
    writer = FakeWriter("edit")
    assert await ImageIntentClassifier(writer).edits_the_image(
        "yes id like a straw hat instead",
        "User: Would a straw hat work?\nAssistant: It would suit the outfit.",
    ) is True

    prompt = writer.calls[0]["prompt"]
    assert "yes id like a straw hat instead" in prompt
    assert "Would a straw hat work?" in prompt
    assert "Classify the newest text" in prompt


# Empty text is not a request for anything, and must not spend an inference call.
async def test_blank_text_is_not_classified() -> None:
    writer = FakeWriter("edit")
    assert await ImageIntentClassifier(writer).edits_the_image("   ") is False
    assert writer.calls == []


# An answer outside the enum cannot arrive through the grammar, but a provider
# that ignored it must not be read as an edit.
async def test_an_unexpected_answer_is_not_an_edit() -> None:
    writer = FakeWriter("maybe")
    assert await ImageIntentClassifier(writer).edits_the_image("a straw hat") is False
