import argparse
import asyncio
import json
from collections.abc import Sequence

from sqlalchemy import select

from backend.artifacts.storage import LocalBinaryArtifactStore
from backend.config.settings import settings
from backend.core.dependencies import get_vision_embedding_provider
from backend.database.session import AsyncSessionLocal
from backend.models.artifact import VisualArtifact
from backend.services.artifact_repository import SQLAlchemyArtifactRepository

# Diagrams hold Mermaid source rather than pixels, so the image encoder cannot
# describe them and they are excluded from backfill.
EMBEDDABLE_KINDS = ("generated_image", "uploaded_image")


# Define safe command-line options for image embedding backfill.
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inventory or backfill aligned image embeddings.",
    )
    parser.add_argument("--user-id", help="Limit the backfill to one user.")
    parser.add_argument(
        "--all-users",
        action="store_true",
        help="Explicitly allow an apply run across every user.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write embeddings; the default is a dry run.",
    )
    return parser


# Embed every ready image that has no vector yet, reporting per-artifact outcome.
async def run(user_id: str | None, apply: bool) -> dict[str, object]:
    provider = get_vision_embedding_provider()
    if not provider.is_enabled():
        return {"error": "vision embedding weights are not present", "processed": 0}

    store = LocalBinaryArtifactStore(settings.ARTIFACT_STORAGE_ROOT)
    processed: list[dict[str, object]] = []

    async with AsyncSessionLocal() as session:
        query = select(VisualArtifact).where(
            VisualArtifact.status == "ready",
            VisualArtifact.embedding.is_(None),
            VisualArtifact.kind.in_(EMBEDDABLE_KINDS),
            VisualArtifact.storage_key.is_not(None),
        )
        if user_id:
            query = query.where(VisualArtifact.user_id == user_id)
        artifacts = list((await session.execute(query)).scalars().all())

        repository = SQLAlchemyArtifactRepository(session)
        for artifact in artifacts:
            record: dict[str, object] = {
                "artifact_id": str(artifact.id),
                "user_id": artifact.user_id,
                "kind": artifact.kind,
            }
            if not apply:
                record["action"] = "would_embed"
                processed.append(record)
                continue
            try:
                content = await store.read(str(artifact.storage_key))
                vector = await asyncio.to_thread(provider.embed_image, content)
                await repository.set_embedding(
                    str(artifact.id),
                    artifact.user_id,
                    vector,
                    settings.VISION_EMBEDDING_MODEL,
                )
                record["action"] = "embedded"
            except Exception as exc:  # noqa: BLE001 - reported, never fatal
                record["action"] = "failed"
                record["error"] = type(exc).__name__
            processed.append(record)

    return {
        "applied": apply,
        "model": settings.VISION_EMBEDDING_MODEL,
        "processed": len(processed),
        "artifacts": processed,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.apply and not args.user_id and not args.all_users:
        print("Refusing an apply run without --user-id or --all-users.")
        return 2
    print(json.dumps(asyncio.run(run(args.user_id, args.apply)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
