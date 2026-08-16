"""Where referent candidates come from, one implementation per modality.

Each source answers the same question for its own kind of thing: which of this
user's items are semantically near what they just said? Both sources here read
an owner-scoped vector index that already exists and is already maintained by
the ingest path for that kind -- derived visual observations for pictures,
chunk embeddings for documents. Neither builds an index of its own.

Adding video is adding a file like this one, not editing `ReferentResolver`.
"""

import logging
from typing import Any

from backend.services.referent_resolution import MAX_CANDIDATES, Referent

logger = logging.getLogger(__name__)

_IMAGE_KINDS = {"generated_image", "uploaded_image"}


# Best available text for one stored image, preferring what the vision model
# actually observed over the words that were used to generate it.
def _image_description(artifact: dict[str, Any]) -> str:
    metadata = artifact.get("metadata") or {}
    for field in ("analysis", "generation_prompt"):
        value = metadata.get(field)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return str(artifact.get("title") or "")


class ImageReferentSource:
    """Offer the user's ready, owned pictures as referent candidates."""

    kind = "image"

    # Hold the semantic candidate loader and the repository that owns readiness.
    def __init__(self, memory: Any, artifacts: Any) -> None:
        self.memory = memory
        self.artifacts = artifacts

    # Return owned, ready pictures near this reference, newest first.
    #
    # Ownership and readiness are re-checked per row rather than trusted from
    # the semantic index, which can outlive the artifact it describes.
    async def candidates(
        self,
        user_id: str,
        reference: str,
        query_embedding: list[float] | None,
    ) -> list[Referent]:
        loader = getattr(self.memory, "get_visual_memory_candidates", None)
        if loader is None or self.artifacts is None:
            return []
        try:
            vector = query_embedding or await self.memory.embed_query(reference)
            rows = await loader(user_id, vector)
        except Exception:
            logger.warning("Image referent candidates unavailable", exc_info=True)
            return []

        found: list[Referent] = []
        seen: set[str] = set()
        for row in rows:
            handle = str((row.get("extra_data") or {}).get("artifact_id") or "")
            if not handle or handle in seen:
                continue
            seen.add(handle)
            try:
                artifact = await self.artifacts.get_owned(user_id, handle)
            except Exception:
                logger.warning("Referent ownership check failed", exc_info=True)
                continue
            if artifact is None or artifact.get("status") != "ready":
                continue
            if artifact.get("kind") not in _IMAGE_KINDS:
                continue
            found.append(
                Referent(
                    handle=handle,
                    kind=self.kind,
                    description=_image_description(artifact)
                    or str(row.get("content") or ""),
                    when=str(artifact.get("created_at") or ""),
                    title=str(artifact.get("title") or ""),
                )
            )
        found.sort(key=lambda item: item.when, reverse=True)
        return found[:MAX_CANDIDATES]


class DocumentReferentSource:
    """Offer the user's ingested documents as referent candidates.

    Chunks are collapsed to one candidate per document: the user refers to "the
    contract", not to its fourth paragraph, and offering six chunks of one file
    as six choices would manufacture ambiguity that does not exist.
    """

    kind = "document"

    # Hold the agent-memory manager whose knowledge store owns the chunk index.
    def __init__(self, agent_memory: Any) -> None:
        self.agent_memory = agent_memory

    # Return owned documents near this reference, best-matching chunk first.
    async def candidates(
        self,
        user_id: str,
        reference: str,
        query_embedding: list[float] | None,
    ) -> list[Referent]:
        knowledge = getattr(self.agent_memory, "knowledge", None)
        if knowledge is None:
            return []
        try:
            rows = await knowledge.search(
                user_id,
                reference,
                MAX_CANDIDATES,
                query_embedding=query_embedding,
            )
        except Exception:
            logger.warning("Document referent candidates unavailable", exc_info=True)
            return []

        found: list[Referent] = []
        seen: set[str] = set()
        for row in rows:
            document = row.get("document") or {}
            handle = str(document.get("id") or "")
            if not handle or handle in seen:
                continue
            seen.add(handle)
            found.append(
                Referent(
                    handle=handle,
                    kind=self.kind,
                    description=str(row.get("content") or ""),
                    when=str(document.get("created_at") or ""),
                    title=str(document.get("title") or ""),
                )
            )
        return found[:MAX_CANDIDATES]
