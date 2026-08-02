"""Expose existing visual application services through a FastMCP façade."""

import json
import secrets
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP

from backend.artifacts.types import ImageGenerationRequest
from backend.core.dependencies import (
    get_artifact_repository,
    get_binary_artifact_store,
    get_diagram_agent,
    get_diagram_artifact_service,
    get_diagram_llm_client,
    get_diagram_provider,
    get_embedding_provider,
    get_image_artifact_service,
    get_image_edit_provider,
    get_image_provider,
    get_memory_service,
    get_presentation_agent,
    get_presentation_job_repository,
    get_presentation_job_service,
    get_presentation_llm_client,
    get_presentation_repository,
    get_presentation_service,
    get_vision_analysis_service,
    get_vision_embedding_provider,
    get_vision_provider,
)
from backend.database.session import AsyncSessionLocal
from backend.models.image import ImageGenerationBody, ImageQuestionBody

_MAX_TOOL_RESULT_CHARS = 3_500


@dataclass(frozen=True, slots=True)
class VisualRequestContext:
    """Application-owned identity attached outside the model-visible schema."""

    user_id: str
    conversation_id: str
    trace_id: str


# Read and validate the AniOS identity metadata attached by the MCP client.
def _request_context(ctx: Context[Any, Any, Any]) -> VisualRequestContext:
    meta = ctx.request_context.meta
    extra = (meta.model_extra or {}) if meta is not None else {}
    user_id = str(extra.get("anios_user_id") or "").strip()
    conversation_id = str(extra.get("anios_conversation_id") or "").strip()
    trace_id = str(extra.get("anios_trace_id") or "").strip()
    if not user_id or len(user_id) > 50:
        raise ValueError("AniOS user context is required.")
    try:
        UUID(conversation_id)
        UUID(trace_id)
    except ValueError as exc:
        raise ValueError(
            "Valid AniOS conversation and trace context is required."
        ) from exc
    return VisualRequestContext(user_id, conversation_id, trace_id)


# Return only bounded public artifact metadata, never storage keys or image bytes.
def _artifact_summary(artifact: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "conversation_id",
        "kind",
        "status",
        "title",
        "provider",
        "model",
        "mime_type",
        "width",
        "height",
        "byte_size",
        "sha256",
        "content_available",
        "error_code",
    )
    return {key: artifact.get(key) for key in keys if artifact.get(key) is not None}


# Return bounded deck metadata and slide identities without the full specification.
def _presentation_summary(presentation: dict[str, Any]) -> dict[str, Any]:
    current = presentation.get("current_revision") or {}
    specification = current.get("specification") or {}
    return {
        "id": presentation.get("id"),
        "conversation_id": presentation.get("conversation_id"),
        "title": presentation.get("title"),
        "current_revision_id": presentation.get("current_revision_id"),
        "revision_number": current.get("revision_number"),
        "status": current.get("status"),
        "content_available": current.get("content_available"),
        "slides": [
            {
                "slide_id": slide.get("slide_id"),
                "title": slide.get("title"),
            }
            for slide in specification.get("slides", [])
            if isinstance(slide, dict)
        ],
    }


# Return a bounded durable-job handle without exposing the private deck prompt.
def _presentation_job_summary(job: dict[str, Any]) -> dict[str, Any]:
    return {
        key: job.get(key)
        for key in (
            "id",
            "presentation_id",
            "revision_id",
            "status",
            "expected_slide_count",
            "error_code",
            "created_at",
        )
        if job.get(key) is not None
    }


# Encode a tool result below the generic MCP cap while preserving valid JSON.
def _encode_result(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, default=str)
    if len(encoded) <= _MAX_TOOL_RESULT_CHARS:
        return encoded
    if isinstance(payload.get("analysis"), str):
        payload = {
            **payload,
            "analysis": payload["analysis"][:2_000],
            "truncated": True,
        }
        encoded = json.dumps(payload, ensure_ascii=False, default=str)
    if len(encoded) > _MAX_TOOL_RESULT_CHARS:
        raise ValueError("Visual tool result exceeds the bounded response limit.")
    return encoded


class VisualCapabilityRuntime:
    """Compose FastMCP calls from the same services used by the browser API."""

    # Generate and persist one editable Mermaid diagram through existing services.
    async def generate_diagram(
        self,
        context: VisualRequestContext,
        prompt: str,
    ) -> str:
        normalized_prompt = prompt.strip()
        if not normalized_prompt or len(normalized_prompt) > 10_000:
            raise ValueError("Diagram prompt must contain 1 to 10000 characters.")
        async with AsyncSessionLocal() as session:
            repository = get_artifact_repository(session)
            provider = get_diagram_provider(get_diagram_llm_client())
            service = get_diagram_artifact_service(
                get_diagram_agent(provider),
                repository,
            )
            pending = await service.begin(
                context.user_id,
                context.conversation_id,
                context.trace_id,
            )
            artifact_id = str(pending["id"])
            try:
                ready = await service.complete(
                    artifact_id,
                    context.user_id,
                    normalized_prompt,
                )
            except Exception:
                await service.fail(artifact_id, context.user_id)
                raise
        return _encode_result({"artifact": _artifact_summary(ready)})

    # Generate and persist one image through the existing ComfyUI service boundary.
    async def generate_image(
        self,
        context: VisualRequestContext,
        prompt: str,
        width: int,
        height: int,
        seed: int | None,
    ) -> str:
        body = ImageGenerationBody(
            user_id=context.user_id,
            conversation_id=UUID(context.conversation_id),
            prompt=prompt,
            width=width,
            height=height,
            seed=seed,
        )
        resolved_seed = body.seed if body.seed is not None else secrets.randbelow(2**63)
        async with AsyncSessionLocal() as session:
            repository = get_artifact_repository(session)
            service = get_image_artifact_service(
                get_image_provider(),
                get_image_edit_provider(),
                repository,
                get_binary_artifact_store(),
                get_vision_embedding_provider(),
            )
            ready = await service.generate(
                user_id=context.user_id,
                conversation_id=context.conversation_id,
                trace_id=context.trace_id,
                request=ImageGenerationRequest(
                    prompt=body.prompt,
                    width=body.width,
                    height=body.height,
                    seed=resolved_seed,
                ),
            )
        return _encode_result({"artifact": _artifact_summary(ready)})

    # Ask the existing vision service about a ready image owned by this user.
    async def ask_about_image(
        self,
        context: VisualRequestContext,
        artifact_id: str,
        question: str,
    ) -> str:
        parsed_artifact_id = str(UUID(artifact_id))
        body = ImageQuestionBody(user_id=context.user_id, prompt=question)
        async with AsyncSessionLocal() as session:
            repository = get_artifact_repository(session)
            images = get_image_artifact_service(
                get_image_provider(),
                get_image_edit_provider(),
                repository,
                get_binary_artifact_store(),
                get_vision_embedding_provider(),
            )
            service = get_vision_analysis_service(
                images,
                repository,
                get_vision_provider(),
                get_memory_service(session, get_embedding_provider()),
            )
            answer = await service.ask_about_artifact(
                context.user_id,
                parsed_artifact_id,
                body.prompt,
            )
        return _encode_result(
            {
                "artifact": _artifact_summary(answer["artifact"]),
                "analysis": answer["analysis"],
                "model": answer["model"],
            }
        )

    # Return bounded status metadata for one owned visual artifact.
    async def get_artifact(
        self,
        context: VisualRequestContext,
        artifact_id: str,
    ) -> str:
        parsed_artifact_id = str(UUID(artifact_id))
        async with AsyncSessionLocal() as session:
            repository = get_artifact_repository(session)
            artifact = await repository.get_owned(context.user_id, parsed_artifact_id)
        if artifact is None:
            raise ValueError("Artifact not found.")
        return _encode_result({"artifact": _artifact_summary(artifact)})

    # Queue one editable presentation for the focused local subagent worker.
    async def create_presentation(
        self,
        context: VisualRequestContext,
        prompt: str,
    ) -> str:
        normalized_prompt = prompt.strip()
        if not normalized_prompt or len(normalized_prompt) > 20_000:
            raise ValueError("Presentation prompt must contain 1 to 20000 characters.")
        async with AsyncSessionLocal() as session:
            jobs = get_presentation_job_service(
                get_presentation_job_repository(session),
                get_presentation_repository(session),
            )
            queued = await jobs.enqueue(
                context.user_id,
                context.conversation_id,
                context.trace_id,
                normalized_prompt,
            )
        return _encode_result({"presentation_job": _presentation_job_summary(queued)})

    # Apply feedback to one slide and persist a linked editable revision.
    async def revise_presentation_slide(
        self,
        context: VisualRequestContext,
        presentation_id: str,
        base_revision_id: str,
        slide_id: str,
        feedback: str,
    ) -> str:
        parsed_presentation_id = str(UUID(presentation_id))
        parsed_revision_id = str(UUID(base_revision_id))
        normalized_slide_id = slide_id.strip()
        normalized_feedback = feedback.strip()
        if not normalized_slide_id or len(normalized_slide_id) > 80:
            raise ValueError("A valid presentation slide identifier is required.")
        if not normalized_feedback or len(normalized_feedback) > 10_000:
            raise ValueError(
                "Presentation feedback must contain 1 to 10000 characters."
            )
        async with AsyncSessionLocal() as session:
            repository = get_presentation_repository(session)
            service = get_presentation_service(
                get_presentation_agent(get_presentation_llm_client()),
                repository,
                get_binary_artifact_store(),
                get_artifact_repository(session),
            )
            ready = await service.revise_slide(
                context.user_id,
                parsed_presentation_id,
                parsed_revision_id,
                normalized_slide_id,
                normalized_feedback,
            )
        return _encode_result({"presentation": _presentation_summary(ready)})

    # Return current bounded metadata for one owned presentation.
    async def get_presentation(
        self,
        context: VisualRequestContext,
        presentation_id: str,
    ) -> str:
        parsed_presentation_id = str(UUID(presentation_id))
        async with AsyncSessionLocal() as session:
            presentation = await get_presentation_repository(session).get_owned(
                context.user_id,
                parsed_presentation_id,
            )
        if presentation is None:
            raise ValueError("Presentation not found.")
        return _encode_result({"presentation": _presentation_summary(presentation)})


# Build a FastMCP server whose schemas omit application-owned identity fields.
def create_visual_mcp(runtime: VisualCapabilityRuntime) -> FastMCP:
    server = FastMCP(
        "AniOS Local Visual Capabilities",
        host="0.0.0.0",
        port=8001,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )

    # Generate an editable diagram and return its owned artifact handle.
    @server.tool()
    async def generate_diagram(prompt: str, ctx: Context[Any, Any, Any]) -> str:
        """Create and persist an editable Mermaid diagram from a text request."""
        return await runtime.generate_diagram(_request_context(ctx), prompt)

    # Generate an image and return its owned artifact handle without image bytes.
    @server.tool()
    async def generate_image(
        prompt: str,
        ctx: Context[Any, Any, Any],
        width: int = 2048,
        height: int = 2048,
        seed: int | None = None,
    ) -> str:
        """Create and persist a local generated image from a text description."""
        return await runtime.generate_image(
            _request_context(ctx),
            prompt,
            width,
            height,
            seed,
        )

    # Ask a grounded follow-up question about an already-owned ready image.
    @server.tool()
    async def ask_about_image(
        artifact_id: str,
        question: str,
        ctx: Context[Any, Any, Any],
    ) -> str:
        """Answer a question about a ready generated or uploaded image artifact."""
        return await runtime.ask_about_image(
            _request_context(ctx),
            artifact_id,
            question,
        )

    # Read bounded metadata for an owned artifact without returning binary content.
    @server.tool()
    async def get_artifact(
        artifact_id: str,
        ctx: Context[Any, Any, Any],
    ) -> str:
        """Return status and public metadata for one owned visual artifact."""
        return await runtime.get_artifact(_request_context(ctx), artifact_id)

    # Queue a native editable PowerPoint deck for PresentationAgent.
    @server.tool()
    async def create_presentation(
        prompt: str,
        ctx: Context[Any, Any, Any],
    ) -> str:
        """Queue creation of a native editable PowerPoint presentation."""
        return await runtime.create_presentation(_request_context(ctx), prompt)

    # Revise exactly one slide and keep all sibling slides unchanged.
    @server.tool()
    async def revise_presentation_slide(
        presentation_id: str,
        base_revision_id: str,
        slide_id: str,
        feedback: str,
        ctx: Context[Any, Any, Any],
    ) -> str:
        """Create a linked presentation revision from feedback on one slide."""
        return await runtime.revise_presentation_slide(
            _request_context(ctx),
            presentation_id,
            base_revision_id,
            slide_id,
            feedback,
        )

    # Read bounded current metadata for one owned presentation.
    @server.tool()
    async def get_presentation(
        presentation_id: str,
        ctx: Context[Any, Any, Any],
    ) -> str:
        """Return current metadata and slide identities for one presentation."""
        return await runtime.get_presentation(
            _request_context(ctx),
            presentation_id,
        )

    return server


visual_mcp = create_visual_mcp(VisualCapabilityRuntime())


# Run the persistent local visual-capability server over streamable HTTP.
def main() -> None:
    visual_mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
