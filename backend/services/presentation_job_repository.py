import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.presentation import (
    Presentation,
    PresentationJob,
    PresentationRevision,
)
from backend.presentations.types import DeckSpec


class SQLAlchemyPresentationJobRepository:
    """Persist and lease durable presentation work through PostgreSQL."""

    # Bind job operations to one asynchronous database session.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Atomically create a pending deck, initial revision, and queued job.
    async def enqueue(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        prompt: str,
        provider: str,
        model: str | None,
        expected_slide_count: int | None,
    ) -> dict[str, Any]:
        pending_title = " ".join(prompt.split())[:100] or "Untitled presentation"
        presentation = Presentation(
            user_id=user_id,
            conversation_id=uuid.UUID(conversation_id),
            trace_id=uuid.UUID(trace_id),
            title=pending_title,
        )
        self.session.add(presentation)
        await self.session.flush()
        revision = PresentationRevision(
            presentation_id=presentation.id,
            parent_revision_id=None,
            revision_number=1,
            status="pending",
            specification_json=None,
            target_slide_id=None,
            change_summary="Initial presentation",
            provider=provider,
            model=model,
        )
        self.session.add(revision)
        await self.session.flush()
        job = PresentationJob(
            presentation_id=presentation.id,
            revision_id=revision.id,
            user_id=user_id,
            status="queued",
            prompt=prompt,
            expected_slide_count=expected_slide_count,
        )
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job.to_dict()

    # Return one user-owned job and its latest persisted draft.
    async def get_owned(
        self,
        user_id: str,
        job_id: str,
    ) -> dict[str, Any] | None:
        job = cast(
            PresentationJob | None,
            await self.session.scalar(
                select(PresentationJob)
                .where(
                    PresentationJob.id == uuid.UUID(job_id),
                    PresentationJob.user_id == user_id,
                )
                .execution_options(populate_existing=True)
            ),
        )
        return job.to_dict() if job is not None else None

    # Claim the oldest queued or expired job without colliding with other workers.
    async def claim_next(
        self,
        worker_id: str,
        lease_seconds: float,
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        job = cast(
            PresentationJob | None,
            await self.session.scalar(
                select(PresentationJob)
                .where(
                    or_(
                        PresentationJob.status == "queued",
                        (
                            (PresentationJob.status == "running")
                            & (PresentationJob.lease_expires_at < now)
                        ),
                    ),
                    PresentationJob.cancel_requested.is_(False),
                )
                .order_by(PresentationJob.created_at.asc())
                .with_for_update(skip_locked=True)
                .limit(1)
            ),
        )
        if job is None:
            await self.session.rollback()
            return None
        revision = cast(
            PresentationRevision | None,
            await self.session.get(PresentationRevision, job.revision_id),
        )
        if revision is not None and revision.status in {"ready", "failed"}:
            job.status = revision.status
            job.error_code = revision.error_code
            job.worker_id = None
            job.lease_expires_at = None
            job.completed_at = revision.completed_at or now
            job.updated_at = now
            await self.session.commit()
            await self.session.refresh(job)
            return job.to_dict()
        job.status = "running"
        job.worker_id = worker_id
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        job.attempt_count += 1
        job.started_at = job.started_at or now
        job.updated_at = now
        await self.session.commit()
        await self.session.refresh(job)
        return {
            **job.to_dict(),
            "prompt": job.prompt,
        }

    # Extend one active worker lease while a model or renderer call is in flight.
    async def renew_lease(
        self,
        job_id: str,
        worker_id: str,
        lease_seconds: float,
    ) -> bool:
        job = await self._owned_worker_job(job_id, worker_id)
        if job is None or job.status != "running":
            await self.session.rollback()
            return False
        now = datetime.now(UTC)
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        job.updated_at = now
        await self.session.commit()
        return True

    # Persist the newest validated draft for polling and reconnecting clients.
    async def save_draft(
        self,
        job_id: str,
        worker_id: str,
        specification: DeckSpec,
        expected_slide_count: int,
    ) -> bool:
        job = await self._owned_worker_job(job_id, worker_id)
        if job is None or job.status != "running" or job.cancel_requested:
            await self.session.rollback()
            return False
        job.draft_specification_json = specification.model_dump_json()
        job.expected_slide_count = expected_slide_count
        job.updated_at = datetime.now(UTC)
        await self.session.commit()
        return True

    # Report whether a running worker should stop at its next safe checkpoint.
    async def cancellation_requested(
        self,
        job_id: str,
        worker_id: str,
    ) -> bool:
        job = await self._owned_worker_job(job_id, worker_id)
        return job is None or job.cancel_requested

    # Mark a successfully promoted presentation job ready.
    async def mark_ready(self, job_id: str, worker_id: str) -> None:
        job = await self._owned_worker_job(job_id, worker_id)
        if job is None:
            raise LookupError("Presentation job lease was lost")
        now = datetime.now(UTC)
        job.status = "ready"
        job.error_code = None
        job.worker_id = None
        job.lease_expires_at = None
        job.completed_at = now
        job.updated_at = now
        await self.session.commit()

    # Record one terminal failure on both the job and its pending revision.
    async def mark_failed(
        self,
        job_id: str,
        worker_id: str,
        error_code: str,
    ) -> None:
        job = await self._owned_worker_job(job_id, worker_id)
        if job is None:
            return
        await self._finish_unsuccessfully(job, "failed", error_code)

    # Request cooperative cancellation or immediately cancel queued work.
    async def request_cancel(self, user_id: str, job_id: str) -> bool:
        job = cast(
            PresentationJob | None,
            await self.session.scalar(
                select(PresentationJob)
                .where(
                    PresentationJob.id == uuid.UUID(job_id),
                    PresentationJob.user_id == user_id,
                )
                .with_for_update()
            ),
        )
        if job is None:
            await self.session.rollback()
            return False
        if job.status in {"ready", "failed", "cancelled"}:
            await self.session.rollback()
            return True
        job.cancel_requested = True
        if job.status == "queued":
            await self._finish_unsuccessfully(job, "cancelled", "cancelled")
        else:
            job.updated_at = datetime.now(UTC)
            await self.session.commit()
        return True

    # Finish cooperatively cancelled running work at a safe worker checkpoint.
    async def mark_cancelled(self, job_id: str, worker_id: str) -> None:
        job = await self._owned_worker_job(job_id, worker_id)
        if job is None:
            return
        await self._finish_unsuccessfully(job, "cancelled", "cancelled")

    # Load one job only when it is held by the expected worker lease.
    async def _owned_worker_job(
        self,
        job_id: str,
        worker_id: str,
    ) -> PresentationJob | None:
        return cast(
            PresentationJob | None,
            await self.session.scalar(
                select(PresentationJob).where(
                    PresentationJob.id == uuid.UUID(job_id),
                    PresentationJob.worker_id == worker_id,
                )
            ),
        )

    # Apply one terminal status to a job and its initial revision atomically.
    async def _finish_unsuccessfully(
        self,
        job: PresentationJob,
        status: str,
        error_code: str,
    ) -> None:
        now = datetime.now(UTC)
        job.status = status
        job.error_code = error_code
        job.worker_id = None
        job.lease_expires_at = None
        job.completed_at = now
        job.updated_at = now
        revision = cast(
            PresentationRevision | None,
            await self.session.get(PresentationRevision, job.revision_id),
        )
        if revision is not None and revision.status == "pending":
            revision.status = "failed"
            revision.error_code = error_code
            revision.completed_at = now
        await self.session.commit()
