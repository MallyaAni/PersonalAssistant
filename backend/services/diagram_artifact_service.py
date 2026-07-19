from typing import Any

from backend.agents.diagram import DiagramAgent
from backend.core.interfaces import ArtifactRepository


class DiagramArtifactService:
    # Coordinate diagram generation without giving the model persistence authority.
    def __init__(
        self,
        agent: DiagramAgent,
        repository: ArtifactRepository,
        provider_name: str,
        model_name: str | None,
    ):
        self.agent = agent
        self.repository = repository
        self.provider_name = provider_name
        self.model_name = model_name

    # Persist a pending record before model generation starts.
    async def begin(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return await self.repository.create_pending(
            user_id,
            conversation_id,
            trace_id,
            self.provider_name,
            self.model_name,
        )

    # Generate validated source and atomically mark the pending record ready.
    async def complete(
        self,
        artifact_id: str,
        user_id: str,
        query: str,
    ) -> dict[str, Any]:
        specification = await self.agent.generate(query)
        return await self.repository.mark_ready(
            artifact_id,
            user_id,
            specification,
        )

    # Record a sanitized failure state for a pending diagram artifact.
    async def fail(
        self,
        artifact_id: str,
        user_id: str,
        error_code: str = "generation_failed",
    ) -> dict[str, Any]:
        return await self.repository.mark_failed(
            artifact_id,
            user_id,
            error_code,
        )
