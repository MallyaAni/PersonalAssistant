import asyncio
import logging
from typing import Any

from backend.agents.vision.observation import (
    CANONICAL_OBSERVATION_PROMPT,
    DEFAULT_UPLOAD_QUESTION,
)
from backend.core.interfaces import (
    BinaryArtifactRepository,
    SemanticMemoryWriter,
    VisionProvider,
)
from backend.memory.purposes import VISUAL_ANALYSIS_PURPOSE
from backend.services.image_artifact_service import ImageArtifactService
from backend.services.image_intent import (
    ASK,
    EDIT,
    ImageIntentClassifier,
)

logger = logging.getLogger(__name__)

# How much of an analysis is worth keeping to find the image again.
#
# This exists so an image can be retrieved by describing it, and the subject is
# named in the opening sentences; the rest is conversational tail. Stored whole,
# one reply ran to 1,371 characters — of which the useful part was the first
# line — and every image added another paragraph of prose to the database.
MAX_INDEXED_CHARS = 1_200


# The part of an analysis worth embedding, cut at a sentence where possible.
#
# Sentence-aware because a description severed mid-clause embeds worse than a
# shorter complete one, and because the result is read by people in the panel.
def _indexable(analysis_text: str) -> str:
    collapsed = " ".join(analysis_text.split())
    if len(collapsed) <= MAX_INDEXED_CHARS:
        return collapsed
    window = collapsed[:MAX_INDEXED_CHARS]
    cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    # Only respect a sentence break in the last third, or a description whose
    # first sentence is very short would be trimmed to almost nothing.
    if cut > MAX_INDEXED_CHARS // 3:
        return window[: cut + 1]
    return window.rstrip() + "…"


# Avoid a duplicate question call only for the browser's exact neutral default.
def _needs_user_answer(prompt: str, wants_edit: bool) -> bool:
    return not wants_edit and prompt.strip() != DEFAULT_UPLOAD_QUESTION


class VisionAnalysisError(RuntimeError):
    # Retain the valid upload identifier while exposing only a safe public failure.
    def __init__(self, artifact_id: str) -> None:
        super().__init__("Vision analysis failed")
        self.artifact_id = artifact_id


class ArtifactNotFoundError(LookupError):
    """Signals that no ready owned image matched the requested artifact."""


class VisionAnalysisService:
    # Coordinate upload persistence and grounded VLM analysis outside the model.
    def __init__(
        self,
        images: ImageArtifactService,
        repository: BinaryArtifactRepository,
        provider: VisionProvider,
        thread_context_turns: int = 8,
        thread_max_stored: int = 40,
        memory: SemanticMemoryWriter | None = None,
        intent: ImageIntentClassifier | None = None,
    ) -> None:
        self.images = images
        self.repository = repository
        self.provider = provider
        self.thread_context_turns = thread_context_turns
        self.thread_max_stored = thread_max_stored
        self.memory = memory
        self.intent = intent

    # Index one image's description so images become semantically retrievable.
    # Only `content` reaches the assistant prompt, so it must name its own
    # provenance rather than read as a user-stated fact.
    async def _index_analysis(
        self,
        user_id: str,
        artifact: dict[str, Any],
        analysis_text: str,
        model: str,
    ) -> None:
        if self.memory is None or not analysis_text.strip():
            return
        raw_kind = str(artifact.get("kind") or "image")
        kind_label = raw_kind.removesuffix("_image") or "stored"
        artifact_id = str(artifact.get("id"))
        try:
            content = (
                f"Description of an image the user has ({kind_label}):"
                f" {_indexable(analysis_text)}"
            )
            metadata = {
                "artifact_id": artifact_id,
                "conversation_id": str(artifact.get("conversation_id") or ""),
                "kind": str(artifact.get("kind") or ""),
                "source": "vision_analysis",
                "analysis_model": model,
            }
            await self.memory.replace_visual_semantic_memory(
                user_id,
                artifact_id,
                content,
                metadata,
            )
        except Exception:
            # Indexing is an enhancement; a failure must not lose the analysis.
            logger.warning(
                "Failed to index analysis for artifact %s",
                artifact_id,
                exc_info=True,
            )

    # Persist one validated upload and attach its successful grounded analysis.
    async def analyze_upload(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        prompt: str,
        content: bytes,
        declared_mime_type: str | None,
    ) -> dict[str, Any]:
        # Asked before the upload is put to the vision model, because the answer
        # decides what to put to it. An edit request answered as a question is
        # how "I cannot edit images" became a stored image description.
        wants_edit = (
            await self.intent.edits_the_image(prompt)
            if self.intent is not None
            else False
        )
        artifact, validated_content = await self.images.store_upload(
            user_id,
            conversation_id,
            trace_id,
            content,
            declared_mime_type,
        )
        artifact_id = str(artifact["id"])
        requests = [
            self.provider.analyze(
                CANONICAL_OBSERVATION_PROMPT,
                validated_content,
                str(artifact["mime_type"]),
            )
        ]
        needs_user_answer = _needs_user_answer(prompt, wants_edit)
        if needs_user_answer:
            requests.append(
                self.provider.analyze(
                    prompt,
                    validated_content,
                    str(artifact["mime_type"]),
                )
            )
        results = await asyncio.gather(*requests, return_exceptions=True)
        observation = results[0]
        if isinstance(observation, BaseException):
            await self.repository.update_metadata(
                artifact_id,
                user_id,
                {"analysis_status": "failed"},
            )
            raise VisionAnalysisError(artifact_id) from observation

        answer = observation
        answer_status = "ready"
        if needs_user_answer:
            proposed_answer = results[1]
            if isinstance(proposed_answer, BaseException):
                answer_status = "fallback"
                logger.warning(
                    "User-facing image answer failed; using canonical observation",
                    exc_info=(
                        type(proposed_answer),
                        proposed_answer,
                        proposed_answer.__traceback__,
                    ),
                )
            else:
                answer = proposed_answer

        metadata: dict[str, Any] = {
            "analysis_status": "ready",
            "analysis": observation.content,
            "analysis_model": observation.model,
            "analysis_answer_status": answer_status,
            **observation.metadata,
        }
        if needs_user_answer:
            metadata["analysis_thread"] = [
                {
                    "prompt": prompt,
                    "answer": answer.content,
                    "model": answer.model,
                }
            ]
        updated = await self.repository.update_metadata(
            artifact_id,
            user_id,
            metadata,
        )
        await self._index_analysis(
            user_id,
            updated,
            observation.content,
            observation.model,
        )
        return {
            "artifact": updated,
            "analysis": answer.content,
            "model": answer.model,
            # The caller edits the stored upload when this says so. It is
            # reported rather than acted on here because the edit needs the
            # artifact this call is still in the middle of creating.
            "intent": EDIT if wants_edit else ASK,
        }

    # Observe an existing ready image and index what its current pixels show.
    async def observe_artifact(
        self,
        user_id: str,
        artifact_id: str,
    ) -> dict[str, Any]:
        owned = await self.images.read_owned(user_id, artifact_id)
        if owned is None:
            raise ArtifactNotFoundError("No ready owned image matched the request")
        artifact, content = owned
        try:
            analysis = await self.provider.analyze(
                CANONICAL_OBSERVATION_PROMPT,
                content,
                str(artifact["mime_type"]),
            )
        except Exception as exc:
            await self.repository.update_metadata(
                artifact_id,
                user_id,
                {"analysis_status": "failed"},
            )
            raise VisionAnalysisError(artifact_id) from exc
        updated = await self.repository.update_metadata(
            artifact_id,
            user_id,
            {
                "analysis_status": "ready",
                "analysis": analysis.content,
                "analysis_model": analysis.model,
                **analysis.metadata,
            },
        )
        await self._index_analysis(user_id, updated, analysis.content, analysis.model)
        return updated

    # Answer one followup question about an owned image and persist the thread.
    async def ask_about_artifact(
        self,
        user_id: str,
        artifact_id: str,
        prompt: str,
    ) -> dict[str, Any]:
        owned = await self.images.read_owned(user_id, artifact_id)
        if owned is None:
            raise ArtifactNotFoundError("No ready owned image matched the request")
        artifact, content = owned
        metadata = artifact.get("metadata") or {}
        thread = self._existing_thread(metadata)
        recent = thread[-self.thread_context_turns :]
        try:
            analysis = await self.provider.analyze_thread(
                content=content,
                mime_type=str(artifact["mime_type"]),
                history=recent,
                prompt=prompt,
            )
        except Exception as exc:
            raise VisionAnalysisError(artifact_id) from exc
        thread.append(
            {"prompt": prompt, "answer": analysis.content, "model": analysis.model}
        )
        bounded = thread[-self.thread_max_stored :]
        updated = await self.repository.update_metadata(
            artifact_id,
            user_id,
            {
                "analysis_status": "ready",
                "analysis_thread": bounded,
            },
        )
        return {
            "artifact": updated,
            "analysis": analysis.content,
            "model": analysis.model,
        }

    # Recover a prior question/answer thread, seeding it from legacy flat analysis.
    def _existing_thread(self, metadata: dict[str, Any]) -> list[dict[str, str]]:
        raw = metadata.get("analysis_thread")
        if isinstance(raw, list):
            return [
                {
                    "prompt": str(entry.get("prompt", "")),
                    "answer": str(entry.get("answer", "")),
                    "model": str(entry.get("model", "")),
                }
                for entry in raw
                if isinstance(entry, dict)
            ]
        legacy = metadata.get("analysis")
        if isinstance(legacy, str) and legacy.strip():
            return [
                {
                    "prompt": "Describe this image.",
                    "answer": legacy.strip(),
                    "model": str(metadata.get("analysis_model", "")),
                }
            ]
        return []
