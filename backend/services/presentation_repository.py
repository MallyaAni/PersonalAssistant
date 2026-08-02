import uuid
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.artifacts.types import StoredBinary
from backend.models.presentation import Presentation, PresentationRevision
from backend.presentations.types import DeckSpec


class PresentationConflictError(RuntimeError):
    """Signals that slide feedback targeted a stale base revision."""


class SQLAlchemyPresentationRepository:
    """Persist owned decks and append-only revisions in the request transaction."""

    # Bind repository operations to one asynchronous request session.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Create one owned deck and its first pending revision before model work.
    async def create_pending(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        provider: str,
        model: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        presentation = Presentation(
            user_id=user_id,
            conversation_id=uuid.UUID(conversation_id),
            trace_id=uuid.UUID(trace_id),
            title="Untitled presentation",
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
        await self.session.commit()
        await self.session.refresh(presentation)
        await self.session.refresh(revision)
        return presentation.to_dict(), revision.to_dict()

    # Store a validated canonical specification before rendering begins.
    async def set_specification(
        self,
        user_id: str,
        presentation_id: str,
        revision_id: str,
        specification: DeckSpec,
    ) -> None:
        presentation, revision = await self._owned_revision(
            user_id, presentation_id, revision_id
        )
        if presentation is None or revision is None:
            raise LookupError("Presentation revision was not found")
        revision.specification_json = specification.model_dump_json()
        if revision.revision_number == 1:
            presentation.title = specification.title
        await self.session.commit()

    # Mark one rendered revision ready and promote it as the current deck.
    async def mark_ready(
        self,
        user_id: str,
        presentation_id: str,
        revision_id: str,
        stored: StoredBinary,
        renderer: str,
        renderer_version: str,
    ) -> dict[str, Any]:
        presentation, revision = await self._owned_revision(
            user_id, presentation_id, revision_id
        )
        if presentation is None or revision is None:
            raise LookupError("Presentation revision was not found")
        revision.status = "ready"
        revision.storage_key = stored.storage_key
        revision.byte_size = stored.byte_size
        revision.sha256 = stored.sha256
        revision.renderer = renderer
        revision.renderer_version = renderer_version
        revision.error_code = None
        revision.completed_at = func.now()
        presentation.current_revision_id = revision.id
        await self.session.commit()
        await self.session.refresh(presentation)
        await self.session.refresh(revision)
        revisions = list(
            (
                await self.session.scalars(
                    select(PresentationRevision)
                    .where(PresentationRevision.presentation_id == presentation.id)
                    .order_by(PresentationRevision.revision_number.desc())
                )
            ).all()
        )
        return self._detail(presentation, revision, revisions)

    # Record one sanitized failure without replacing the last ready revision.
    async def mark_failed(
        self,
        user_id: str,
        presentation_id: str,
        revision_id: str,
        error_code: str,
    ) -> None:
        presentation, revision = await self._owned_revision(
            user_id, presentation_id, revision_id
        )
        if presentation is None or revision is None:
            return
        revision.status = "failed"
        revision.error_code = error_code
        revision.completed_at = func.now()
        await self.session.commit()

    # Append a pending child revision only when the supplied base is still current.
    async def create_revision_pending(
        self,
        user_id: str,
        presentation_id: str,
        base_revision_id: str,
        # None when the revision adds a slide rather than editing one.
        target_slide_id: str | None,
        change_summary: str,
        provider: str,
        model: str | None,
    ) -> tuple[DeckSpec, dict[str, Any]]:
        presentation = cast(
            Presentation | None,
            await self.session.scalar(
                select(Presentation)
                .where(
                    Presentation.id == uuid.UUID(presentation_id),
                    Presentation.user_id == user_id,
                )
                .with_for_update()
            ),
        )
        if presentation is None:
            raise LookupError("Presentation was not found")
        if str(presentation.current_revision_id) != base_revision_id:
            raise PresentationConflictError(
                "Presentation changed; reload before applying feedback"
            )
        base = cast(
            PresentationRevision | None,
            await self.session.scalar(
                select(PresentationRevision).where(
                    PresentationRevision.id == uuid.UUID(base_revision_id),
                    PresentationRevision.presentation_id == presentation.id,
                    PresentationRevision.status == "ready",
                )
            ),
        )
        if base is None or not base.specification_json:
            raise LookupError("Base presentation revision was not found")
        latest_number = int(
            await self.session.scalar(
                select(func.max(PresentationRevision.revision_number)).where(
                    PresentationRevision.presentation_id == presentation.id
                )
            )
            or 0
        )
        revision = PresentationRevision(
            presentation_id=presentation.id,
            parent_revision_id=base.id,
            revision_number=latest_number + 1,
            status="pending",
            specification_json=None,
            target_slide_id=target_slide_id,
            change_summary=change_summary,
            provider=provider,
            model=model,
        )
        self.session.add(revision)
        await self.session.commit()
        await self.session.refresh(revision)
        return (
            DeckSpec.model_validate_json(base.specification_json),
            revision.to_dict(),
        )

    # Point a revision at the slide it produced. An addition has no slide id
    # until the model has planned it, so the revision is created without one and
    # claims it afterwards; without this the new slide's follow-up history is
    # empty even though a revision created it.
    async def set_revision_target(
        self,
        presentation_id: str,
        revision_id: str,
        slide_id: str,
    ) -> None:
        revision = await self.session.get(PresentationRevision, uuid.UUID(revision_id))
        if revision is None or str(revision.presentation_id) != presentation_id:
            return
        revision.target_slide_id = slide_id
        await self.session.commit()

    # Return one owned deck, its current full spec, and complete revision lineage.
    async def get_owned(
        self,
        user_id: str,
        presentation_id: str,
    ) -> dict[str, Any] | None:
        presentation = cast(
            Presentation | None,
            await self.session.scalar(
                select(Presentation)
                .where(
                    Presentation.id == uuid.UUID(presentation_id),
                    Presentation.user_id == user_id,
                )
                .execution_options(populate_existing=True)
            ),
        )
        if presentation is None:
            return None
        revisions = list(
            (
                await self.session.scalars(
                    select(PresentationRevision)
                    .where(PresentationRevision.presentation_id == presentation.id)
                    .order_by(PresentationRevision.revision_number.desc())
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        current = next(
            (
                revision
                for revision in revisions
                if revision.id == presentation.current_revision_id
            ),
            None,
        )
        return self._detail(presentation, current, revisions)

    # List each owned deck with the public metadata for its current revision.
    async def list_for_user(
        self,
        user_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        presentations = list(
            (
                await self.session.scalars(
                    select(Presentation)
                    .where(Presentation.user_id == user_id)
                    .order_by(Presentation.updated_at.desc())
                    .limit(limit)
                )
            ).all()
        )
        results = []
        for presentation in presentations:
            current = (
                cast(
                    PresentationRevision | None,
                    await self.session.get(
                        PresentationRevision,
                        presentation.current_revision_id,
                    ),
                )
                if presentation.current_revision_id
                else None
            )
            latest = current or cast(
                PresentationRevision | None,
                await self.session.scalar(
                    select(PresentationRevision)
                    .where(PresentationRevision.presentation_id == presentation.id)
                    .order_by(PresentationRevision.revision_number.desc())
                    .limit(1)
                ),
            )
            results.append(
                self._detail(
                    presentation,
                    current,
                    [latest] if current is None and latest is not None else [],
                )
            )
        return results

    # Return the private storage key only after both ownership checks succeed.
    async def get_revision_content(
        self,
        user_id: str,
        presentation_id: str,
        revision_id: str,
    ) -> dict[str, Any] | None:
        presentation, revision = await self._owned_revision(
            user_id, presentation_id, revision_id
        )
        if (
            presentation is None
            or revision is None
            or revision.status != "ready"
            or not revision.storage_key
        ):
            return None
        return {
            **revision.to_dict(),
            "presentation_title": presentation.title,
            "_storage_key": revision.storage_key,
        }

    # Delete one owned deck and return every binary key requiring cleanup.
    async def delete(self, user_id: str, presentation_id: str) -> list[str] | None:
        presentation = cast(
            Presentation | None,
            await self.session.scalar(
                select(Presentation).where(
                    Presentation.id == uuid.UUID(presentation_id),
                    Presentation.user_id == user_id,
                )
            ),
        )
        if presentation is None:
            return None
        keys = [
            key
            for key in (
                await self.session.scalars(
                    select(PresentationRevision.storage_key).where(
                        PresentationRevision.presentation_id == presentation.id,
                        PresentationRevision.storage_key.is_not(None),
                    )
                )
            ).all()
            if key
        ]
        presentation.current_revision_id = None
        await self.session.flush()
        await self.session.execute(
            delete(Presentation).where(Presentation.id == presentation.id)
        )
        await self.session.commit()
        return keys

    # Load a revision only through its user-owned parent presentation.
    async def _owned_revision(
        self,
        user_id: str,
        presentation_id: str,
        revision_id: str,
    ) -> tuple[Presentation | None, PresentationRevision | None]:
        presentation = cast(
            Presentation | None,
            await self.session.scalar(
                select(Presentation).where(
                    Presentation.id == uuid.UUID(presentation_id),
                    Presentation.user_id == user_id,
                )
            ),
        )
        if presentation is None:
            return None, None
        revision = cast(
            PresentationRevision | None,
            await self.session.scalar(
                select(PresentationRevision).where(
                    PresentationRevision.id == uuid.UUID(revision_id),
                    PresentationRevision.presentation_id == presentation.id,
                )
            ),
        )
        return presentation, revision

    # Build one public response with a full spec only for the active revision.
    def _detail(
        self,
        presentation: Presentation,
        current: PresentationRevision | None,
        revisions: list[PresentationRevision],
    ) -> dict[str, Any]:
        return {
            **presentation.to_dict(),
            "current_revision": (
                current.to_dict(include_specification=True) if current else None
            ),
            # Each revision carries its own specification so the interface can show
            # the exact slides at any point in the history, not only the latest.
            "revisions": [
                revision.to_dict(include_specification=True) for revision in revisions
            ],
        }
