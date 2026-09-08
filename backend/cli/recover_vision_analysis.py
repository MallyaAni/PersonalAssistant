"""Re-run the analysis of uploaded photos whose first vision pass failed.

An upload whose inspection transiently failed - the vision model restarting, a
timeout - is kept as an artifact but carries no meaning, so a later mention of
what it showed resolves to nothing and the assistant can misread a reference to
it. Reports the failed artifacts by default; `--apply` re-inspects each stored
image with the canonical description and writes the analysis and its embedding,
so the picture's meaning reaches memory after the fact.
"""

import argparse
import asyncio
import logging
from collections.abc import Sequence

from sqlalchemy import select

from backend.artifacts.storage import LocalBinaryArtifactStore
from backend.config.settings import settings
from backend.core.dependencies import (
    get_artifact_repository,
    get_embedding_provider,
    get_memory_service,
    get_vision_provider,
)
from backend.database.session import AsyncSessionLocal
from backend.models.artifact import VisualArtifact
from backend.services.vision_analysis_service import VisionAnalysisService

logger = logging.getLogger(__name__)

# Only uploads carry a description; a generated image's own prompt is the
# meaning, and a diagram holds Mermaid source rather than pixels.
RECOVERABLE_KINDS = ("uploaded_image",)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inventory or recover uploaded photos whose vision analysis failed.",
    )
    parser.add_argument("--user-id", help="Limit the recovery to one user.")
    parser.add_argument(
        "--all-users",
        action="store_true",
        help="Explicitly allow an apply run across every user.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Re-analyse the failed photos; the default is a dry run.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        help="Repeat after this delay; omit it to run exactly once.",
    )
    return parser


# Find ready uploads whose analysis never succeeded, across one user or all.
async def _failed_artifacts(user_id: str | None) -> list[VisualArtifact]:
    async with AsyncSessionLocal() as session:
        query = (
            select(VisualArtifact)
            .where(
                VisualArtifact.status == "ready",
                VisualArtifact.kind.in_(RECOVERABLE_KINDS),
                VisualArtifact.storage_key.is_not(None),
                VisualArtifact.extra_data["analysis_status"].astext == "failed",
            )
            .order_by(VisualArtifact.created_at)
        )
        if user_id:
            query = query.where(VisualArtifact.user_id == user_id)
        return list((await session.execute(query)).scalars().all())


# Re-inspect one stored photo in place and embed its meaning.
async def _recover_one(
    artifact: VisualArtifact,
    store: LocalBinaryArtifactStore,
    service: VisionAnalysisService,
) -> bool:
    try:
        content = await store.read(str(artifact.storage_key))
    except Exception as exc:
        logger.warning("Vision recovery unreadable %s: %s", artifact.id, exc)
        return False
    updated = await service.recover_analysis(
        str(artifact.user_id),
        str(artifact.id),
        "Describe what you see in this picture, briefly.",
        content,
        artifact.mime_type or "image/jpeg",
    )
    return updated is not None


# Recover every failed upload, reporting each outcome; `apply` alone rewrites.
async def run(user_id: str | None, apply: bool) -> dict[str, object]:
    artifacts = await _failed_artifacts(user_id)
    if not artifacts:
        return {"found": 0, "recovered": 0, "message": "no failed uploads"}

    store = LocalBinaryArtifactStore(settings.ARTIFACT_STORAGE_ROOT)
    async with AsyncSessionLocal() as db:
        service = VisionAnalysisService(
            images=None,  # type: ignore[arg-type]
            repository=get_artifact_repository(db),
            provider=get_vision_provider(),
            memory=get_memory_service(db, get_embedding_provider()),
        )
        recovered = 0
        for artifact in artifacts:
            if not apply:
                print(
                    f"  {str(artifact.id)[:8]} {artifact.user_id} "
                    f"{artifact.created_at.date()} (would recover)"
                )
                continue
            if await _recover_one(artifact, store, service):
                recovered += 1
                print(f"  {str(artifact.id)[:8]} {artifact.user_id} recovered")
            else:
                print(f"  {str(artifact.id)[:8]} {artifact.user_id} still failing")
        return {
            "found": len(artifacts),
            "recovered": recovered if apply else len(artifacts),
            "message": "recovered" if apply else "dry run",
        }


# Run once, or loop as a maintenance job when given an interval.
async def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.user_id and arguments.all_users:
        raise SystemExit("--user-id and --all-users are mutually exclusive")
    if arguments.apply and not arguments.user_id and not arguments.all_users:
        raise SystemExit("refusing to apply across every user without --all-users")
    if arguments.interval_seconds is None:
        return await run(arguments.user_id, arguments.apply)
    while True:
        try:
            await run(arguments.user_id, arguments.apply)
        except Exception:
            logger.warning("Vision analysis recovery sweep failed", exc_info=True)
        await asyncio.sleep(arguments.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
