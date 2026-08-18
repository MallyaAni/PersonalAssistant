"""Routing an upload on what the words meant, without calling a model.

The functional suite measures whether the model classifies English correctly.
This measures the wiring around it: that the answer changes what the vision
model is asked, that it reaches the caller, and that losing the classifier
degrades to the behaviour this path had before it existed.
"""

import json
from typing import Any

import pytest

from backend.artifacts.types import (
    VisionAnalysis,
    VisionUploadInspection,
    VisualIdentification,
)
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
    """Return one deterministic structured inspection and count image calls."""

    def __init__(self, intent: str = "ask", fail: bool = False) -> None:
        self.intent = intent
        self.fail = fail
        self.asked: list[str] = []

    # Return routing, durable observation, and answer from one image request.
    async def inspect_upload(self, question, content, mime_type):
        self.asked.append(question)
        if self.fail:
            raise RuntimeError("inference runtime unreachable")
        answer = (
            "I will add a straw hat."
            if self.intent == "edit"
            else "The sign says DANCE TONIGHT."
        )
        return VisionUploadInspection(
            intent=self.intent,
            observation="A person wearing a navy jacket beside a sign.",
            answer=answer,
            grounding="not_needed",
            search_query="",
            needs_reasoning=False,
            unsupported_reason="not_applicable",
            model="test",
            metadata={},
        )

    # Retain plain analysis for existing-artifact observation tests.
    async def analyze(self, prompt, content, mime_type):
        self.asked.append(prompt)
        return VisionAnalysis(
            content="A person wearing a navy jacket beside a sign.",
            model="test",
            metadata={},
        )


class UnsupportedVision:
    """Return a contradictory unsupported decision with guessed identities."""

    # Simulate a model whose enum is safe but whose prose still hallucinates.
    async def inspect_upload(self, question, content, mime_type):
        return VisionUploadInspection(
            intent="ask",
            observation="These are Rohu, Catla, and Hilsa.",
            answer="The exact fish are Rohu, Catla, and Hilsa.",
            grounding="unsupported",
            search_query="",
            needs_reasoning=False,
            unsupported_reason="missing_visual_evidence",
            model="test",
            metadata={},
            identified_items=(
                VisualIdentification(
                    label="Shrimp",
                    confidence="high",
                    basis="whole peeled shrimp are visibly recognizable",
                ),
                VisualIdentification(
                    label="Rohu",
                    confidence="medium",
                    basis="plausible from the cut and Indian-market context",
                ),
            ),
        )


class ModelUncertainVision:
    """Report visible diagnostic evidence that needs a stronger VLM."""

    # Ask for specialist escalation without proposing a final identity.
    async def inspect_upload(self, question, content, mime_type):
        return VisionUploadInspection(
            intent="ask",
            observation="An intact device has several distinctive controls.",
            answer="I cannot interpret the visible controls reliably.",
            grounding="unsupported",
            search_query="",
            needs_reasoning=False,
            unsupported_reason="model_uncertain",
            model="primary-vision",
            metadata={},
        )


class SpecialistVision:
    """Return one stronger interpretation and count escalation calls."""

    def __init__(self) -> None:
        self.calls = 0
        self.questions: list[str] = []

    # Resolve the diagnostic evidence during one specialist inspection.
    async def inspect_upload(self, question, content, mime_type):
        self.calls += 1
        self.questions.append(question)
        return VisionUploadInspection(
            intent="ask",
            observation="An intact labelled oscilloscope with two channels.",
            answer="This is a two-channel oscilloscope.",
            grounding="not_needed",
            search_query="",
            needs_reasoning=False,
            unsupported_reason="not_applicable",
            model="specialist-vision",
            metadata={},
        )


class ForbiddenReasoner:
    """Fail if an evidence-free uncertainty spends a main-model call."""

    # Surface any accidental synchronous reasoning invocation immediately.
    def chat(self, messages, max_tokens=512):
        raise AssertionError("evidence-free uncertainty reached the reasoner")


async def _analyze(prompt: str, intent: str | None, fail: bool = False):
    vision = RecordingVision(intent or "ask", fail)
    service = VisionAnalysisService(
        StubImages(),
        StubRepository(),
        vision,
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


# One pixel-facing inspection routes an upload edit without a classifier call.
async def test_an_edit_request_is_not_the_question_put_to_the_vision_model() -> None:
    vision, result = await _analyze("give me a straw hat", "edit")
    assert len(vision.asked) == 1
    assert vision.asked[0] == "give me a straw hat"
    assert result["intent"] == "edit"


# One inspection returns separately persisted observation and visible answer.
async def test_a_question_is_put_to_the_vision_model_unchanged() -> None:
    vision, result = await _analyze("what is written on the sign?", "ask")
    assert vision.asked == ["what is written on the sign?"]
    assert result["analysis"] == "The sign says DANCE TONIGHT."
    assert result["artifact"]["metadata"]["analysis"] == (
        "A person wearing a navy jacket beside a sign."
    )
    assert result["artifact"]["metadata"]["analysis_thread"] == [
        {
            "prompt": "what is written on the sign?",
            "answer": "The sign says DANCE TONIGHT.",
            "model": "test",
        }
    ]
    assert result["intent"] == "ask"


# A failed single inspection leaves the upload in its retryable failure state.
async def test_a_classifier_failure_still_analyzes_the_upload() -> None:
    with pytest.raises(Exception, match="Vision analysis failed"):
        await _analyze("give me a straw hat", None, fail=True)


# A structured provider needs exactly one image call.
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
    assert vision.asked == ["describe this"]
    assert result["intent"] == "ask"


# Unsupported identification must preserve confidence per visible item.
async def test_unsupported_identification_keeps_item_level_confidence() -> None:
    specialist = SpecialistVision()
    service = VisionAnalysisService(
        StubImages(),
        StubRepository(),
        UnsupportedVision(),
        escalation_provider=specialist,
    )

    result = await service.analyze_upload(
        "u",
        "22222222-2222-4222-8222-222222222222",
        "t",
        "Identify the exact Indian fish names",
        b"bytes",
        "image/png",
        defer_reasoning=True,
    )

    assert result["reasoning_pending"] is False
    assert "High confidence" in result["analysis"]
    assert "Possible, but not confirmed" in result["analysis"]
    assert "Shrimp" in result["analysis"]
    assert "Rohu" in result["analysis"]
    assert "Rohu" not in result["artifact"]["metadata"]["analysis"]
    assert "Shrimp" in result["artifact"]["metadata"]["analysis"]
    items = result["artifact"]["metadata"]["analysis_identified_items"]
    assert items[0]["confidence"] == "high"
    assert items[1]["confidence"] == "medium"
    assert specialist.calls == 0


# Genuine model uncertainty gets exactly one configured specialist inspection.
async def test_model_uncertainty_escalates_once_to_specialist() -> None:
    specialist = SpecialistVision()
    service = VisionAnalysisService(
        StubImages(),
        StubRepository(),
        ModelUncertainVision(),
        escalation_provider=specialist,
    )

    result = await service.analyze_upload(
        "u",
        "22222222-2222-4222-8222-222222222222",
        "t",
        "What device is this?",
        b"bytes",
        "image/png",
    )

    assert specialist.calls == 1
    assert "Re-evaluate the unresolved" in specialist.questions[0]
    assert result["analysis"] == "This is a two-channel oscilloscope."
    assert result["model"] == "specialist-vision"
    metadata = result["artifact"]["metadata"]
    assert metadata["analysis_escalated"] is True
    assert metadata["analysis_initial_model"] == "primary-vision"


# An uncertain inspection with no candidate cannot be rescued by web prose.
async def test_candidate_free_uncertainty_skips_background_reasoning() -> None:
    service = VisionAnalysisService(
        StubImages(),
        StubRepository(),
        ModelUncertainVision(),
        reasoner=ForbiddenReasoner(),
    )

    result = await service.analyze_upload(
        "u",
        "22222222-2222-4222-8222-222222222222",
        "t",
        "What device is this?",
        b"bytes",
        "image/png",
        defer_reasoning=True,
    )

    assert result["reasoning_pending"] is False


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
    assert (
        await ImageIntentClassifier(writer).edits_the_image(
            "yes id like a straw hat instead",
            "User: Would a straw hat work?\nAssistant: It would suit the outfit.",
        )
        is True
    )

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


class LowConfidenceOnlyVision:
    """Return only low-confidence readings, as a hard subject really does."""

    # Mirror the reported case: prepared seafood, three hedged readings, no
    # confident one, and no search query of the model's own.
    async def inspect_upload(self, question, content, mime_type):
        return VisionUploadInspection(
            intent="ask",
            observation="Raw fish in containers and cut pieces on a board.",
            answer="I cannot reliably identify the exact species.",
            grounding="unsupported",
            search_query="",
            needs_reasoning=False,
            unsupported_reason="model_uncertain",
            model="primary-vision",
            metadata={},
            identified_items=(
                VisualIdentification(
                    label="Whole silvery fish (likely mackerel)",
                    confidence="low",
                    basis="visible silvery scales, fins and body shape",
                ),
                VisualIdentification(
                    label="Pink-fleshed steaks",
                    confidence="low",
                    basis="visible pinkish-red flesh and dark skin",
                ),
            ),
        )


# A partial identification must read as partial, not as total failure.
#
# Asked to identify fish, every reading came back low-confidence and all of
# them were dropped, so a usable hedged answer was reported as "I can't
# reliably identify the exact name from this image".
@pytest.mark.asyncio
async def test_low_confidence_readings_are_offered_rather_than_dropped() -> None:
    service = VisionAnalysisService(
        StubImages(),
        StubRepository(),
        LowConfidenceOnlyVision(),
        reasoner=ForbiddenReasoner(),
    )

    result = await service.analyze_upload(
        "u",
        "33333333-3333-4333-8333-333333333333",
        "t",
        "identify and label the fish in this image",
        b"bytes",
        "image/png",
        defer_reasoning=True,
    )

    answer = result["analysis"]
    assert result["reasoning_pending"] is True
    assert "mackerel" in answer.lower()
    assert "Pink-fleshed steaks" in answer
    # Offered, but never as settled fact.
    assert "unconfirmed" in answer.lower()
    # The durable record still withholds every unconfirmed name.
    stored = result["artifact"]["metadata"]["analysis"]
    assert "mackerel" not in stored.lower()


# Withholding a guess is still right where acting on a wrong one causes harm.
@pytest.mark.asyncio
async def test_a_safety_sensitive_identification_still_refuses() -> None:
    class SafetySensitiveVision:
        # Report the same uncertainty under the safety-sensitive reason.
        async def inspect_upload(self, question, content, mime_type):
            return VisionUploadInspection(
                intent="ask",
                observation="Pale mushrooms with domed caps at the base of a tree.",
                answer="I cannot confirm whether these are edible.",
                grounding="unsupported",
                search_query="",
                needs_reasoning=False,
                unsupported_reason="safety_sensitive",
                model="primary-vision",
                metadata={},
                identified_items=(
                    VisualIdentification(
                        label="Field mushroom",
                        confidence="low",
                        basis="pale domed cap and white gills",
                    ),
                ),
            )

    service = VisionAnalysisService(
        StubImages(),
        StubRepository(),
        SafetySensitiveVision(),
    )

    result = await service.analyze_upload(
        "u",
        "44444444-4444-4444-8444-444444444444",
        "t",
        "are these safe to eat?",
        b"bytes",
        "image/png",
        defer_reasoning=True,
    )

    assert "Field mushroom" not in result["analysis"]
    assert "safely confirm" in result["analysis"]
