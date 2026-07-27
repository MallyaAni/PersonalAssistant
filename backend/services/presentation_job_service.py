from typing import Any

from backend.presentations.planner import requested_slide_count
from backend.services.presentation_job_repository import (
    SQLAlchemyPresentationJobRepository,
)
from backend.services.presentation_repository import (
    SQLAlchemyPresentationRepository,
)


class PresentationJobService:
    """Create and inspect durable presentation work without running the model."""

    # Bind job lifecycle operations to presentation persistence.
    def __init__(
        self,
        jobs: SQLAlchemyPresentationJobRepository,
        presentations: SQLAlchemyPresentationRepository,
        provider_name: str,
        model_name: str | None,
    ) -> None:
        self.jobs = jobs
        self.presentations = presentations
        self.provider_name = provider_name
        self.model_name = model_name

    # Queue one deck and return before the presentation subagent starts.
    async def enqueue(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        prompt: str,
    ) -> dict[str, Any]:
        return await self.jobs.enqueue(
            user_id,
            conversation_id,
            trace_id,
            prompt,
            self.provider_name,
            self.model_name,
            requested_slide_count(prompt),
        )

    # Return one job plus its ready presentation when promotion has completed.
    async def get(
        self,
        user_id: str,
        job_id: str,
    ) -> dict[str, Any] | None:
        job = await self.jobs.get_owned(user_id, job_id)
        if job is None:
            return None
        job["presentation"] = (
            await self.presentations.get_owned(
                user_id,
                str(job["presentation_id"]),
            )
            if job["status"] == "ready"
            else None
        )
        return job

    # Request cooperative cancellation without touching completed work.
    async def cancel(self, user_id: str, job_id: str) -> bool:
        return await self.jobs.request_cancel(user_id, job_id)
