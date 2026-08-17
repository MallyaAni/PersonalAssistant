import asyncio
import logging
from typing import Any

from backend.agents.vision.observation import (
    CANONICAL_OBSERVATION_PROMPT,
    DEFAULT_UPLOAD_QUESTION,
    build_visual_question_prompt,
)
from backend.agents.vision.reasoning import build_reasoning_messages
from backend.artifacts.types import VisionUploadInspection
from backend.core.interfaces import (
    BinaryArtifactRepository,
    SemanticMemoryWriter,
    VisionProvider,
)
from backend.core.llm import LLMClient
from backend.services.image_artifact_service import ImageArtifactService
from backend.services.image_intent import ASK, EDIT
from backend.services.visual_search_grounding import VisualSearchGrounding

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


# Present each supported identification at its own evidence level.
def _unsupported_answer(inspection: VisionUploadInspection) -> str:
    if inspection.unsupported_reason == "safety_sensitive":
        return (
            "I can’t safely confirm the exact identity from this image alone. "
            "Please use a qualified source or clearer identifying evidence before "
            "acting on it."
        )
    high = [item for item in inspection.identified_items if item.confidence == "high"]
    medium = [
        item for item in inspection.identified_items if item.confidence == "medium"
    ]
    # Shown, clearly hedged, rather than dropped. Asked to identify fish in a
    # photograph of prepared seafood the model returned three low-confidence
    # readings - one of them "likely mackerel or sardine" for a whole fish that
    # is a mackerel - and every one was discarded, so a partial success was
    # reported as "I can't reliably identify the exact name from this image".
    # A hedged best reading with its visible basis is more use than silence and
    # no less honest; `safety_sensitive` above still refuses outright, which is
    # where withholding a guess actually matters.
    low = [item for item in inspection.identified_items if item.confidence == "low"]
    sections: list[str] = []
    if high:
        lines = "\n".join(f"- **{item.label}** — {item.basis}" for item in high)
        sections.append(f"**High confidence**\n\n{lines}")
    if medium:
        lines = "\n".join(f"- **{item.label}** — {item.basis}" for item in medium)
        sections.append(f"**Possible, but not confirmed**\n\n{lines}")
    if low:
        lines = "\n".join(f"- **{item.label}** — {item.basis}" for item in low)
        sections.append(f"**Best guess only — treat as unconfirmed**\n\n{lines}")
    if sections:
        return (
            "I can identify some visible items with different confidence levels:\n\n"
            + "\n\n".join(sections)
            + "\n\nI couldn’t confidently identify every item. A clearer view of "
            "distinctive features or a label would narrow down the rest."
        )
    return (
        "I can’t reliably identify the exact name from this image. The visible "
        "pixels do not contain enough diagnostic evidence. A clearer image showing "
        "an intact subject, distinctive features, or a label would be needed."
    )


# Keep only high-confidence image evidence in durable semantic memory.
def _unsupported_observation(
    prompt: str,
    inspection: VisionUploadInspection,
) -> str:
    high = [item for item in inspection.identified_items if item.confidence == "high"]
    confirmed = "; ".join(f"{item.label} ({item.basis})" for item in high)
    prefix = f"High-confidence visible items: {confirmed}. " if confirmed else ""
    return (
        f"{prefix}An uploaded image was discussed with this user request: {prompt}. "
        "Some requested identities could not be reliably determined from the "
        "available pixels."
    )


# What a search may be given about an image whose identities are unconfirmed.
#
# Every `basis` is the visible evidence the model cited, never the name it
# guessed - "Visible silvery scales, fins" rather than "mackerel" - so this can
# be handed to a web search without asserting an identity anywhere. It exists
# because the sanitized observation above deliberately keeps none of that, and
# a search given only "some requested identities could not be reliably
# determined" has nothing to identify from.
def _visible_evidence(items: list[dict[str, Any]] | tuple[Any, ...]) -> str:
    seen: list[str] = []
    for item in items:
        basis = (
            item.get("basis") if isinstance(item, dict) else getattr(item, "basis", "")
        )
        text = str(basis or "").strip()
        if text and text not in seen:
            seen.append(text)
    return "; ".join(seen)


# Render one stored locality as a short phrase for the reasoning prompt.
def _describe_locality(locality: Any) -> str:
    label = str(getattr(locality, "label", "") or "").strip()
    region = str(getattr(locality, "region", "") or "").strip()
    if not label:
        return ""
    return f"{label}, {region}" if region else label


# Give a specialist the unresolved task while preserving confirmed primary items.
def _specialist_question(
    prompt: str,
    inspection: VisionUploadInspection,
) -> str:
    confirmed = [
        item.label for item in inspection.identified_items if item.confidence == "high"
    ]
    context = ", ".join(confirmed) if confirmed else "none"
    return (
        f"{prompt}\n\nA primary vision pass confirmed these high-confidence items: "
        f"{context}. Re-evaluate the unresolved or lower-confidence items. Preserve "
        "confirmed items unless the pixels clearly contradict them."
    )


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
        reasoner: LLMClient | None = None,
        reasoning_max_tokens: int = 1024,
        grounding: VisualSearchGrounding | None = None,
        escalation_provider: VisionProvider | None = None,
        # Reads the user's own stated home locality, which is a strong prior
        # for identifying anything regional. Optional: without it the answer
        # is exactly what it was, and a failure here never costs the answer.
        profile: Any | None = None,
    ) -> None:
        self.images = images
        self.repository = repository
        self.provider = provider
        self.thread_context_turns = thread_context_turns
        self.thread_max_stored = thread_max_stored
        self.memory = memory
        # Optional on purpose: unset, every answer is the vision model's own,
        # exactly as before. The reindexing path constructs this service without
        # a reasoner because it never answers anyone.
        self.reasoner = reasoner
        self.reasoning_max_tokens = reasoning_max_tokens
        # Also optional: unset, reasoning happens on model knowledge alone,
        # which is why an unfamiliar device could be described accurately and
        # still not named.
        self.grounding = grounding
        self.escalation_provider = escalation_provider
        self.profile = profile

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

    # Answer an image question with the main model, grounded in what was seen.
    #
    # Returns the vision model's own answer unchanged when no reasoner is
    # configured or the reasoning call fails: a reasoning outage must degrade to
    # the previous behaviour, never to an error, because the user already has a
    # usable answer in hand by this point and losing it to a second model's
    # unavailability would be strictly worse than not reasoning at all.
    async def _reason_about(
        self,
        question: str,
        observation: str,
        direct_answer: str,
        grounding_decided: bool = False,
        search_query: str = "",
        candidates: list[dict[str, str]] | None = None,
        stated_locality: str = "",
    ) -> tuple[str, bool]:
        if self.reasoner is None or not question.strip():
            return direct_answer, False
        search_results = None
        if self.grounding is not None:
            if grounding_decided:
                if search_query.strip():
                    search_results = await self.grounding.ground_query(search_query)
            else:
                search_results = await self.grounding.ground(question, observation)
        messages = build_reasoning_messages(
            question,
            observation,
            search_results,
            candidates,
            stated_locality,
        )
        try:
            result = await asyncio.to_thread(
                self.reasoner.chat,
                messages,
                self.reasoning_max_tokens,
            )
        except Exception:
            logger.warning(
                "Visual reasoning pass failed; using the vision model's answer",
                exc_info=True,
            )
            return direct_answer, False
        reasoned = str(result.get("content") or "").strip()
        if not reasoned:
            return direct_answer, False
        return reasoned, True

    # Obtain one upload result, retaining a one-call compatibility path for
    # older custom providers that only implement plain image analysis.
    # Describe where the user has said they live, or nothing at all.
    #
    # Their own stated locality, never a guess. It weights which regionally
    # common candidates to consider first, which is most of the distance
    # between "some silvery fish" and a name - the same pixels are a different
    # shortlist in Mumbai and in Maine. It says nothing about who they are, and
    # the reasoning prompt is explicit that it must not be read that way.
    async def _stated_locality(self, user_id: str) -> str:
        if self.profile is None:
            return ""
        try:
            profile = await self.profile.get_profile(user_id)
        except Exception:
            logger.warning("Locality unavailable for visual reasoning", exc_info=True)
            return ""
        localities = getattr(profile, "localities", ()) or ()
        for locality in localities:
            if getattr(locality, "is_primary", False):
                described = _describe_locality(locality)
                if described:
                    return described
        for locality in localities:
            described = _describe_locality(locality)
            if described:
                return described
        return ""

    async def _inspect_upload(
        self,
        question: str,
        content: bytes,
        mime_type: str,
    ) -> VisionUploadInspection:
        inspect = getattr(self.provider, "inspect_upload", None)
        if callable(inspect):
            inspected = await inspect(question, content, mime_type)
            if not isinstance(inspected, VisionUploadInspection):
                raise ValueError("Vision provider returned an invalid inspection")
            return inspected
        legacy = await self.provider.analyze(question, content, mime_type)
        return VisionUploadInspection(
            intent=ASK,
            observation=legacy.content,
            answer=legacy.content,
            grounding="not_needed",
            search_query="",
            needs_reasoning=False,
            unsupported_reason="not_applicable",
            model=legacy.model,
            metadata=legacy.metadata,
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
        defer_reasoning: bool = False,
    ) -> dict[str, Any]:
        artifact, validated_content = await self.images.store_upload(
            user_id,
            conversation_id,
            trace_id,
            content,
            declared_mime_type,
        )
        artifact_id = str(artifact["id"])
        try:
            inspection = await self._inspect_upload(
                prompt,
                validated_content,
                str(artifact["mime_type"]),
            )
        except Exception as exc:
            await self.repository.update_metadata(
                artifact_id,
                user_id,
                {"analysis_status": "failed"},
            )
            raise VisionAnalysisError(artifact_id) from exc

        initial_model = inspection.model
        escalated = False
        if (
            inspection.grounding == "unsupported"
            and inspection.unsupported_reason == "model_uncertain"
            and self.escalation_provider is not None
        ):
            try:
                inspection = await self.escalation_provider.inspect_upload(
                    _specialist_question(prompt, inspection),
                    validated_content,
                    str(artifact["mime_type"]),
                )
                escalated = True
            except Exception:
                logger.warning(
                    "Specialist vision escalation failed; retaining primary result",
                    exc_info=True,
                )

        wants_edit = inspection.intent == EDIT
        needs_user_answer = _needs_user_answer(prompt, wants_edit)
        observation_text = inspection.observation
        immediate_answer = inspection.answer
        if inspection.grounding == "unsupported" and not wants_edit:
            # The constrained enum is the application decision; free text can
            # still contradict it. Do not store or show guessed identities once
            # the same inspection says the pixels lack diagnostic evidence.
            observation_text = _unsupported_observation(prompt, inspection)
            immediate_answer = _unsupported_answer(inspection)

        # The vision model has now seen the pixels; the reasoning about them is
        # the main model's job. Only for a real question - the canonical
        # description is an index entry, not an answer to anyone.
        # Deferred, the caller gets the vision model's answer now and the
        # reasoned one is written to this artifact afterwards. The whole chain
        # - search decision, search, then the main model - runs to about
        # seventeen seconds, and this endpoint sends nothing until it returns;
        # a phone that locks or backgrounds during that silence drops the
        # connection and the user sees a failure for work that fully succeeded.
        answer_text = immediate_answer
        answer_model = inspection.model
        reasoning_pending = False
        # An identification the pixels cannot settle is exactly the case a web
        # search exists to rescue, and it was the one case that never reached
        # one: the model answered `model_uncertain` with no search query, the
        # specialist escalation is unconfigured on this install, and
        # `needs_reasoning` came back false - so asked to identify fish the
        # reply was "could not be reliably determined" while the observation
        # naming silvery scales and pale elongated fillets sat unused. Let the
        # grounding step decide from that observation rather than dead-ending.
        unresolved_identity = (
            inspection.grounding == "unsupported"
            and inspection.unsupported_reason == "model_uncertain"
            and not escalated
        )
        should_reason = (
            needs_user_answer
            and (inspection.needs_reasoning or unresolved_identity)
            and self.reasoner is not None
        )
        if should_reason and defer_reasoning:
            reasoning_pending = True
        elif should_reason:
            answer_text, reasoned = await self._reason_about(
                prompt,
                (
                    _visible_evidence(inspection.identified_items) or observation_text
                    if unresolved_identity
                    else observation_text
                ),
                immediate_answer,
                # An uncertain inspection produced no query of its own, so let
                # the grounding step read the evidence and write one.
                grounding_decided=not unresolved_identity,
                search_query=inspection.search_query,
                candidates=[
                    {
                        "label": item.label,
                        "confidence": item.confidence,
                        "basis": item.basis,
                    }
                    for item in inspection.identified_items
                ],
                stated_locality=await self._stated_locality(user_id),
            )
            if reasoned:
                answer_model = (
                    f"{inspection.model}+{getattr(self.reasoner, 'model', 'reasoner')}"
                )

        metadata: dict[str, Any] = {
            "analysis_status": "ready",
            "analysis": observation_text,
            "analysis_model": inspection.model,
            "analysis_answer_status": "ready",
            "analysis_grounding": inspection.grounding,
            # The upload endpoint defers reasoning, so this flag is what the
            # background pass reads. Recorded as decided only when the
            # inspection actually decided: left hardcoded true, an uncertain
            # identification asked the grounding step to reuse a query it never
            # produced, which searched for nothing at all.
            "analysis_grounding_decided": not unresolved_identity,
            "analysis_search_query": inspection.search_query,
            "analysis_needs_reasoning": (
                inspection.needs_reasoning or unresolved_identity
            ),
            "analysis_unsupported_reason": inspection.unsupported_reason,
            "analysis_escalated": escalated,
            "analysis_initial_model": initial_model,
            "analysis_identified_items": [
                {
                    "label": item.label,
                    "confidence": item.confidence,
                    "basis": item.basis,
                }
                for item in inspection.identified_items
            ],
            **inspection.metadata,
        }
        if needs_user_answer:
            metadata["analysis_thread"] = [
                {
                    "prompt": prompt,
                    "answer": answer_text,
                    "model": answer_model,
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
            observation_text,
            inspection.model,
        )
        return {
            "artifact": updated,
            "analysis": answer_text,
            "model": answer_model,
            # Tells the caller a better answer is coming for this artifact, so
            # it knows to look again rather than poll something already final.
            "reasoning_pending": reasoning_pending,
            # The caller edits the stored upload when this says so. It is
            # reported rather than acted on here because the edit needs the
            # artifact this call is still in the middle of creating.
            "intent": EDIT if wants_edit else ASK,
        }

    # Replace a deferred answer with the reasoned one, after the reply was sent.
    #
    # Reads the grounding back off the artifact rather than taking it as
    # arguments, because this runs in a different task from the request that
    # stored it and the stored copy is the only thing guaranteed to still be
    # true. Answers False when there was nothing to improve.
    async def finish_deferred_reasoning(
        self,
        user_id: str,
        artifact_id: str,
    ) -> bool:
        artifact = await self.repository.get_owned(user_id, artifact_id)
        if artifact is None:
            return False
        metadata = artifact.get("metadata") or {}
        thread = self._existing_thread(metadata)
        if not thread:
            return False
        last = thread[-1]
        stored_analysis = str(metadata.get("analysis") or "")
        # The stored analysis deliberately withholds unconfirmed identities, so
        # for those it says almost nothing a search could use. The recorded
        # evidence does, and names nothing.
        grounding_decided = bool(metadata.get("analysis_grounding_decided"))
        observation = stored_analysis
        if not grounding_decided:
            items = metadata.get("analysis_identified_items") or []
            observation = _visible_evidence(items) or stored_analysis
        answer_text, reasoned = await self._reason_about(
            last.get("prompt", ""),
            observation,
            last.get("answer", ""),
            grounding_decided=grounding_decided,
            search_query=str(metadata.get("analysis_search_query") or ""),
            candidates=[
                item
                for item in (metadata.get("analysis_identified_items") or [])
                if isinstance(item, dict)
            ],
            stated_locality=await self._stated_locality(user_id),
        )
        if not reasoned:
            return False
        thread[-1] = {
            **last,
            "answer": answer_text,
            "model": (
                f"{last.get('model', '')}+{getattr(self.reasoner, 'model', 'reasoner')}"
            ),
        }
        await self.repository.update_metadata(
            artifact_id,
            user_id,
            {
                "analysis_status": "ready",
                "analysis_thread": thread,
                # An explicit flag rather than leaving the client to infer this
                # from the model string: a poll needs one unambiguous thing to
                # wait for, and the answer text alone cannot say whether the
                # reasoning ran or merely returned the same words.
                "analysis_reasoned": True,
            },
        )
        return True

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
                # This re-describes an edit's current pixels only so the result
                # stays semantically findable - unlike the upload flow, nothing
                # ever shows this text to the user, so the frontend's legacy
                # analysis-thread fallback must not surface it as if it were an
                # answer to a question nobody asked.
                "analysis_user_facing": False,
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
                prompt=build_visual_question_prompt(prompt),
            )
        except Exception as exc:
            raise VisionAnalysisError(artifact_id) from exc
        # Ground the reasoning in the stored description as well as this turn's
        # look at the pixels, so a follow-up keeps the detail the original
        # observation captured rather than only what this answer happened to
        # mention.
        answer_text, reasoned = await self._reason_about(
            prompt,
            str(metadata.get("analysis") or analysis.content),
            analysis.content,
        )
        answer_model = (
            f"{analysis.model}+{getattr(self.reasoner, 'model', 'reasoner')}"
            if reasoned
            else analysis.model
        )
        thread.append({"prompt": prompt, "answer": answer_text, "model": answer_model})
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
            "analysis": answer_text,
            "model": answer_model,
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
