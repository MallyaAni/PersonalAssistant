import asyncio
import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.locks import transaction_advisory_lock
from backend.embeddings.base import EmbeddingProvider
from backend.memory.retrieval import SemanticRetrievalPolicy
from backend.models.agent_memory import (
    ConversationSummary,
    KnowledgeChunk,
    KnowledgeDocument,
    MemoryEntity,
    MemoryEntityRelation,
    ProcedureMemory,
    SemanticCacheEntry,
    WorkingMemoryItem,
)


# Normalize text so equivalent values share the same lookup key.
def _normalized(value: str) -> str:
    return " ".join(value.strip().casefold().split())


# Build a stable cache key from normalized query text.
def _cache_key(query: str) -> str:
    return hashlib.sha256(_normalized(query).encode()).hexdigest()


# Attach readable similarity scores to a retrieved memory record.
def _retrieval(item: dict[str, Any], distance: float) -> dict[str, Any]:
    item["retrieval"] = {
        "cosine_distance": round(distance, 6),
        "relevance_score": round(max(0.0, 1.0 - distance), 6),
    }
    return item


class _VectorStore:
    # Store the shared database, embedding, and retrieval dependencies.
    def __init__(
        self,
        session: AsyncSession,
        embeddings: EmbeddingProvider,
        retrieval_policy: SemanticRetrievalPolicy,
        embedding_version: str,
    ) -> None:
        self.session = session
        self.embeddings = embeddings
        self.retrieval_policy = retrieval_policy
        self.embedding_version = embedding_version

    # Generate an embedding for text that will be stored.
    async def _embed_text(self, text: str) -> list[float]:
        return await asyncio.to_thread(self.embeddings.embed_text, text)

    # Generate an embedding for a retrieval query.
    async def _embed_query(self, query: str) -> list[float]:
        return await asyncio.to_thread(self.embeddings.embed_query, query)

    # Describe the model and dimensions used for an embedding.
    def _embedding_metadata(self, embedding: list[float]) -> dict[str, Any]:
        return {
            "embedding_model": getattr(self.embeddings, "model", "unknown"),
            "embedding_version": self.embedding_version,
            "embedding_dimension": len(embedding),
        }


class SemanticCacheStore(_VectorStore):
    # Return an exact or semantically similar unexpired cached response.
    async def get(
        self,
        user_id: str,
        query: str,
        model: str,
        *,
        semantic_fallback: bool = True,
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        exact = (
            await self.session.execute(
                select(SemanticCacheEntry).where(
                    SemanticCacheEntry.user_id == user_id,
                    SemanticCacheEntry.cache_key == _cache_key(query),
                    SemanticCacheEntry.model == model,
                    SemanticCacheEntry.expires_at > now,
                )
            )
        ).scalar_one_or_none()
        if exact is not None:
            exact.hit_count += 1
            exact.last_accessed_at = now
            await self.session.commit()
            await self.session.refresh(exact)
            return exact.to_dict()

        if not semantic_fallback:
            return None

        embedding = await self._embed_query(query)
        distance = SemanticCacheEntry.embedding.cosine_distance(embedding)
        row = (
            await self.session.execute(
                select(SemanticCacheEntry, distance.label("cosine_distance"))
                .where(
                    SemanticCacheEntry.user_id == user_id,
                    SemanticCacheEntry.model == model,
                    SemanticCacheEntry.expires_at > now,
                    distance <= self.retrieval_policy.max_cosine_distance,
                )
                .order_by(distance, SemanticCacheEntry.id)
                .limit(1)
            )
        ).first()
        if row is None:
            return None
        entry, score = row
        entry.hit_count += 1
        entry.last_accessed_at = now
        await self.session.commit()
        await self.session.refresh(entry)
        return _retrieval(entry.to_dict(), float(score))

    # Create or refresh a cached response for a user query.
    async def put(
        self,
        user_id: str,
        query: str,
        response: str,
        model: str,
        expires_at: datetime,
    ) -> dict[str, Any]:
        key = _cache_key(query)
        embedding = await self._embed_text(query)
        await transaction_advisory_lock(
            self.session, "semantic_cache", user_id, key, model
        )
        entry = (
            await self.session.execute(
                select(SemanticCacheEntry).where(
                    SemanticCacheEntry.user_id == user_id,
                    SemanticCacheEntry.cache_key == key,
                    SemanticCacheEntry.model == model,
                )
            )
        ).scalar_one_or_none()
        if entry is None:
            entry = SemanticCacheEntry(
                user_id=user_id,
                cache_key=key,
                query=query,
                response=response,
                embedding=embedding,
                model=model,
                hit_count=0,
                expires_at=expires_at,
                **self._embedding_metadata(embedding),
            )
            self.session.add(entry)
        else:
            entry.query = query
            entry.response = response
            entry.embedding = embedding
            entry.expires_at = expires_at
            entry.embedding_model = getattr(self.embeddings, "model", "unknown")
            entry.embedding_version = self.embedding_version
            entry.embedding_dimension = len(embedding)
        await self.session.commit()
        await self.session.refresh(entry)
        return entry.to_dict()

    # Delete expired semantic-cache entries for one user.
    async def purge_expired(self, user_id: str) -> int:
        result = await self.session.execute(
            delete(SemanticCacheEntry).where(
                SemanticCacheEntry.user_id == user_id,
                SemanticCacheEntry.expires_at <= datetime.now(UTC),
            )
        )
        await self.session.commit()
        return int(getattr(result, "rowcount", 0))


class WorkingMemoryStore:
    # Store the database session used for working-memory operations.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Create or update a temporary value for one conversation.
    async def upsert(
        self,
        user_id: str,
        conversation_id: str,
        memory_key: str,
        value: str,
        purpose: str,
        expires_at: datetime,
    ) -> dict[str, Any]:
        conversation_uuid = uuid.UUID(conversation_id)
        await transaction_advisory_lock(
            self.session,
            "working_memory",
            user_id,
            conversation_id,
            memory_key,
        )
        item = (
            await self.session.execute(
                select(WorkingMemoryItem).where(
                    WorkingMemoryItem.user_id == user_id,
                    WorkingMemoryItem.conversation_id == conversation_uuid,
                    WorkingMemoryItem.memory_key == memory_key,
                )
            )
        ).scalar_one_or_none()
        if item is None:
            item = WorkingMemoryItem(
                user_id=user_id,
                conversation_id=conversation_uuid,
                memory_key=memory_key,
                value=value,
                purpose=purpose,
                expires_at=expires_at,
            )
            self.session.add(item)
        else:
            item.value = value
            item.purpose = purpose
            item.expires_at = expires_at
        await self.session.commit()
        await self.session.refresh(item)
        return item.to_dict()

    # List unexpired working-memory values for one conversation.
    async def list_active(
        self, user_id: str, conversation_id: str
    ) -> list[dict[str, Any]]:
        items = (
            await self.session.execute(
                select(WorkingMemoryItem)
                .where(
                    WorkingMemoryItem.user_id == user_id,
                    WorkingMemoryItem.conversation_id == uuid.UUID(conversation_id),
                    WorkingMemoryItem.expires_at > datetime.now(UTC),
                )
                .order_by(WorkingMemoryItem.updated_at, WorkingMemoryItem.id)
            )
        ).scalars()
        return [item.to_dict() for item in items]


class ProcedureStore(_VectorStore):
    # Save a newly approved version of a reusable procedure.
    async def approve(
        self,
        user_id: str,
        name: str,
        description: str,
        steps: list[dict[str, Any]],
        source_conversation_id: str | None,
        source_trace_id: str,
        expires_at: datetime | None,
        extra_data: dict[str, Any],
    ) -> dict[str, Any]:
        canonical = f"{name}\n{description}\n{json.dumps(steps, sort_keys=True)}"
        embedding = await self._embed_text(canonical)
        await transaction_advisory_lock(self.session, "procedure", user_id, name)
        latest_version = (
            await self.session.execute(
                select(func.max(ProcedureMemory.version)).where(
                    ProcedureMemory.user_id == user_id,
                    ProcedureMemory.name == name,
                )
            )
        ).scalar_one()
        previous = (
            await self.session.execute(
                select(ProcedureMemory).where(
                    ProcedureMemory.user_id == user_id,
                    ProcedureMemory.name == name,
                    ProcedureMemory.active.is_(True),
                )
            )
        ).scalars()
        for item in previous:
            item.active = False
        procedure = ProcedureMemory(
            user_id=user_id,
            name=name,
            description=description,
            steps=steps,
            approval_state="approved",
            version=(latest_version or 0) + 1,
            source_trace_id=uuid.UUID(source_trace_id),
            source_conversation_id=(
                uuid.UUID(source_conversation_id) if source_conversation_id else None
            ),
            embedding=embedding,
            active=True,
            expires_at=expires_at,
            extra_data=extra_data,
            **self._embedding_metadata(embedding),
        )
        self.session.add(procedure)
        await self.session.commit()
        await self.session.refresh(procedure)
        return procedure.to_dict()

    # Find approved procedures that are relevant to a query.
    async def search(
        self,
        user_id: str,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        embedding = await self._embed_query(query)
        distance = ProcedureMemory.embedding.cosine_distance(embedding)
        rows = (
            await self.session.execute(
                select(ProcedureMemory, distance.label("cosine_distance"))
                .where(
                    ProcedureMemory.user_id == user_id,
                    ProcedureMemory.active.is_(True),
                    ProcedureMemory.approval_state == "approved",
                    or_(
                        ProcedureMemory.expires_at.is_(None),
                        ProcedureMemory.expires_at > datetime.now(UTC),
                    ),
                    distance <= self.retrieval_policy.max_cosine_distance,
                )
                .order_by(distance, ProcedureMemory.id)
                .limit(min(top_k, self.retrieval_policy.max_results))
            )
        ).all()
        return [_retrieval(item.to_dict(), float(score)) for item, score in rows]


class EntityStore(_VectorStore):
    # Create or update an approved entity and its attributes.
    async def upsert(
        self,
        user_id: str,
        entity_type: str,
        canonical_name: str,
        attributes: dict[str, Any],
        source_conversation_id: str | None,
        source_trace_id: str,
        expires_at: datetime | None,
    ) -> dict[str, Any]:
        normalized_name = _normalized(canonical_name)
        canonical = (
            f"{entity_type}\n{canonical_name}\n"
            f"{json.dumps(attributes, sort_keys=True)}"
        )
        embedding = await self._embed_text(canonical)
        await transaction_advisory_lock(
            self.session,
            "entity",
            user_id,
            entity_type,
            normalized_name,
        )
        entity = (
            await self.session.execute(
                select(MemoryEntity).where(
                    MemoryEntity.user_id == user_id,
                    MemoryEntity.entity_type == entity_type,
                    MemoryEntity.normalized_name == normalized_name,
                )
            )
        ).scalar_one_or_none()
        if entity is None:
            entity = MemoryEntity(
                user_id=user_id,
                entity_type=entity_type,
                canonical_name=canonical_name,
                normalized_name=normalized_name,
                attributes=attributes,
                approval_state="approved",
                source_conversation_id=(
                    uuid.UUID(source_conversation_id)
                    if source_conversation_id
                    else None
                ),
                source_trace_id=uuid.UUID(source_trace_id),
                embedding=embedding,
                expires_at=expires_at,
                **self._embedding_metadata(embedding),
            )
            self.session.add(entity)
        else:
            entity.canonical_name = canonical_name
            entity.attributes = attributes
            entity.source_conversation_id = (
                uuid.UUID(source_conversation_id) if source_conversation_id else None
            )
            entity.source_trace_id = uuid.UUID(source_trace_id)
            entity.embedding = embedding
            entity.embedding_model = getattr(self.embeddings, "model", "unknown")
            entity.embedding_version = self.embedding_version
            entity.embedding_dimension = len(embedding)
            entity.expires_at = expires_at
            entity.approval_state = "approved"
        await self.session.commit()
        await self.session.refresh(entity)
        return entity.to_dict()

    # Find approved entities that are relevant to a query.
    async def search(
        self,
        user_id: str,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        embedding = await self._embed_query(query)
        distance = MemoryEntity.embedding.cosine_distance(embedding)
        rows = (
            await self.session.execute(
                select(MemoryEntity, distance.label("cosine_distance"))
                .where(
                    MemoryEntity.user_id == user_id,
                    MemoryEntity.approval_state == "approved",
                    or_(
                        MemoryEntity.expires_at.is_(None),
                        MemoryEntity.expires_at > datetime.now(UTC),
                    ),
                    distance <= self.retrieval_policy.max_cosine_distance,
                )
                .order_by(distance, MemoryEntity.id)
                .limit(min(top_k, self.retrieval_policy.max_results))
            )
        ).all()
        return [_retrieval(item.to_dict(), float(score)) for item, score in rows]

    # Create or update a relationship between two user-owned entities.
    async def relate(
        self,
        user_id: str,
        source_entity_id: str,
        target_entity_id: str,
        relation_type: str,
        attributes: dict[str, Any],
        source_trace_id: str,
    ) -> dict[str, Any]:
        source_uuid = uuid.UUID(source_entity_id)
        target_uuid = uuid.UUID(target_entity_id)
        await transaction_advisory_lock(
            self.session,
            "entity_relation",
            user_id,
            str(source_uuid),
            str(target_uuid),
            relation_type,
        )
        owned = (
            await self.session.execute(
                select(func.count(MemoryEntity.id)).where(
                    MemoryEntity.user_id == user_id,
                    MemoryEntity.id.in_([source_uuid, target_uuid]),
                )
            )
        ).scalar_one()
        if owned != 2:
            raise LookupError("Both entities must exist for the current user")
        relation = (
            await self.session.execute(
                select(MemoryEntityRelation).where(
                    MemoryEntityRelation.user_id == user_id,
                    MemoryEntityRelation.source_entity_id == source_uuid,
                    MemoryEntityRelation.target_entity_id == target_uuid,
                    MemoryEntityRelation.relation_type == relation_type,
                )
            )
        ).scalar_one_or_none()
        if relation is None:
            relation = MemoryEntityRelation(
                user_id=user_id,
                source_entity_id=source_uuid,
                target_entity_id=target_uuid,
                relation_type=relation_type,
                attributes=attributes,
                approval_state="approved",
                source_trace_id=uuid.UUID(source_trace_id),
            )
            self.session.add(relation)
        else:
            relation.attributes = attributes
            relation.approval_state = "approved"
            relation.source_trace_id = uuid.UUID(source_trace_id)
        await self.session.commit()
        await self.session.refresh(relation)
        return relation.to_dict()


class KnowledgeStore(_VectorStore):
    # Split a document into compact chunks for embedding and retrieval.
    @staticmethod
    def _chunks(content: str, chunk_size: int = 1_000) -> list[str]:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content)]
        paragraphs = [part for part in paragraphs if part]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs or [content.strip()]:
            if current and len(current) + len(paragraph) + 2 > chunk_size:
                chunks.append(current)
                current = paragraph
            else:
                current = f"{current}\n\n{paragraph}".strip()
        if current:
            chunks.append(current)
        return chunks

    # Store a document and embed each of its text chunks.
    async def ingest(
        self,
        user_id: str,
        title: str,
        content: str,
        source_uri: str | None,
        purpose: str,
        source_conversation_id: str | None = None,
        source_trace_id: str | None = None,
    ) -> dict[str, Any]:
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        await transaction_advisory_lock(
            self.session,
            "knowledge_document",
            user_id,
            content_hash,
        )
        existing = (
            await self.session.execute(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.user_id == user_id,
                    KnowledgeDocument.content_hash == content_hash,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return await self._document_with_chunks(existing)
        document = KnowledgeDocument(
            user_id=user_id,
            title=title,
            source_uri=source_uri,
            content_hash=content_hash,
            purpose=purpose,
            status="indexing",
            approval_state="approved",
            source_conversation_id=(
                uuid.UUID(source_conversation_id) if source_conversation_id else None
            ),
            source_trace_id=(uuid.UUID(source_trace_id) if source_trace_id else None),
        )
        self.session.add(document)
        await self.session.flush()
        chunks = self._chunks(content)
        embeddings = [await self._embed_text(chunk) for chunk in chunks]
        for position, (chunk, embedding) in enumerate(
            zip(chunks, embeddings, strict=True)
        ):
            self.session.add(
                KnowledgeChunk(
                    user_id=user_id,
                    document_id=document.id,
                    position=position,
                    content=chunk,
                    embedding=embedding,
                    extra_data={},
                    **self._embedding_metadata(embedding),
                )
            )
        document.status = "active"
        await self.session.commit()
        await self.session.refresh(document)
        return await self._document_with_chunks(document)

    # Serialize a knowledge document together with its ordered chunks.
    async def _document_with_chunks(
        self, document: KnowledgeDocument
    ) -> dict[str, Any]:
        chunks = (
            await self.session.execute(
                select(KnowledgeChunk)
                .where(
                    KnowledgeChunk.user_id == document.user_id,
                    KnowledgeChunk.document_id == document.id,
                )
                .order_by(KnowledgeChunk.position)
            )
        ).scalars()
        result = document.to_dict()
        result["chunks"] = [chunk.to_dict() for chunk in chunks]
        return result

    # Find knowledge chunks that are relevant to a query.
    async def search(
        self,
        user_id: str,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        embedding = await self._embed_query(query)
        distance = KnowledgeChunk.embedding.cosine_distance(embedding)
        rows = (
            await self.session.execute(
                select(
                    KnowledgeChunk, KnowledgeDocument, distance.label("cosine_distance")
                )
                .join(
                    KnowledgeDocument,
                    KnowledgeDocument.id == KnowledgeChunk.document_id,
                )
                .where(
                    KnowledgeChunk.user_id == user_id,
                    KnowledgeDocument.user_id == user_id,
                    KnowledgeDocument.status == "active",
                    distance <= self.retrieval_policy.max_cosine_distance,
                )
                .order_by(distance, KnowledgeChunk.id)
                .limit(min(top_k, self.retrieval_policy.max_results))
            )
        ).all()
        results = []
        for chunk, document, score in rows:
            item = chunk.to_dict()
            item["document"] = document.to_dict()
            results.append(_retrieval(item, float(score)))
        return results

    # Delete one user-owned knowledge document and its chunks.
    async def delete(self, user_id: str, document_id: str) -> bool:
        result = await self.session.execute(
            delete(KnowledgeDocument).where(
                KnowledgeDocument.user_id == user_id,
                KnowledgeDocument.id == uuid.UUID(document_id),
            )
        )
        await self.session.commit()
        return bool(getattr(result, "rowcount", 0))


class SummaryStore(_VectorStore):
    # Save an embedded summary for a completed span of conversation turns.
    async def save(
        self,
        user_id: str,
        conversation_id: str,
        content: str,
        through_turn_count: int,
        source_trace_id: str,
    ) -> dict[str, Any]:
        embedding = await self._embed_text(content)
        await transaction_advisory_lock(
            self.session,
            "conversation_summary",
            user_id,
            conversation_id,
            str(through_turn_count),
        )
        summary = (
            await self.session.execute(
                select(ConversationSummary).where(
                    ConversationSummary.user_id == user_id,
                    ConversationSummary.conversation_id == uuid.UUID(conversation_id),
                    ConversationSummary.through_turn_count == through_turn_count,
                )
            )
        ).scalar_one_or_none()
        if summary is None:
            summary = ConversationSummary(
                user_id=user_id,
                conversation_id=uuid.UUID(conversation_id),
                content=content,
                through_turn_count=through_turn_count,
                source_trace_id=uuid.UUID(source_trace_id),
                embedding=embedding,
                **self._embedding_metadata(embedding),
            )
            self.session.add(summary)
        else:
            summary.content = content
            summary.source_trace_id = uuid.UUID(source_trace_id)
            summary.embedding = embedding
            summary.embedding_model = getattr(self.embeddings, "model", "unknown")
            summary.embedding_version = self.embedding_version
            summary.embedding_dimension = len(embedding)
        await self.session.commit()
        await self.session.refresh(summary)
        return summary.to_dict()

    # Return the newest summary for a conversation, if one exists.
    async def latest(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        summary = (
            await self.session.execute(
                select(ConversationSummary)
                .where(
                    ConversationSummary.user_id == user_id,
                    ConversationSummary.conversation_id == uuid.UUID(conversation_id),
                )
                .order_by(
                    ConversationSummary.through_turn_count.desc(),
                    ConversationSummary.created_at.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return summary.to_dict() if summary else None

    # Find conversation summaries that are relevant to a query.
    async def search(
        self,
        user_id: str,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        embedding = await self._embed_query(query)
        distance = ConversationSummary.embedding.cosine_distance(embedding)
        rows = (
            await self.session.execute(
                select(ConversationSummary, distance.label("cosine_distance"))
                .where(
                    ConversationSummary.user_id == user_id,
                    distance <= self.retrieval_policy.max_cosine_distance,
                )
                .order_by(distance, ConversationSummary.id)
                .limit(min(top_k, self.retrieval_policy.max_results))
            )
        ).all()
        return [_retrieval(item.to_dict(), float(score)) for item, score in rows]


class AgentMemoryManager:
    """Typed access to memory stores; never exposes raw tables to an agent."""

    # Assemble the specialized stores behind one memory manager.
    def __init__(
        self,
        session: AsyncSession,
        embeddings: EmbeddingProvider,
        retrieval_policy: SemanticRetrievalPolicy,
        embedding_version: str,
    ) -> None:
        self.session = session
        args = (session, embeddings, retrieval_policy, embedding_version)
        self.semantic_cache = SemanticCacheStore(*args)
        self.working = WorkingMemoryStore(session)
        self.procedures = ProcedureStore(*args)
        self.entities = EntityStore(*args)
        self.knowledge = KnowledgeStore(*args)
        self.summaries = SummaryStore(*args)

    # Count each agent-memory record type for one user.
    async def snapshot(self, user_id: str) -> dict[str, Any]:
        model_counts: dict[str, Any] = {
            "semantic_cache": SemanticCacheEntry,
            "working": WorkingMemoryItem,
            "procedures": ProcedureMemory,
            "entities": MemoryEntity,
            "entity_relations": MemoryEntityRelation,
            "knowledge_documents": KnowledgeDocument,
            "knowledge_chunks": KnowledgeChunk,
            "summaries": ConversationSummary,
        }
        counts: dict[str, Any] = {}
        for name, model in model_counts.items():
            counts[name] = (
                await self.session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.user_id == user_id)
                )
                or 0
            )
        return counts

    # Export all agent-memory records owned by one user.
    async def export(self, user_id: str) -> dict[str, list[dict[str, Any]]]:
        models: tuple[tuple[str, Any], ...] = (
            ("semantic_cache", SemanticCacheEntry),
            ("working", WorkingMemoryItem),
            ("procedures", ProcedureMemory),
            ("entities", MemoryEntity),
            ("entity_relations", MemoryEntityRelation),
            ("knowledge_documents", KnowledgeDocument),
            ("knowledge_chunks", KnowledgeChunk),
            ("summaries", ConversationSummary),
        )
        exported: dict[str, list[dict[str, Any]]] = {}
        for name, model in models:
            rows = await self.session.execute(
                select(model).where(model.user_id == user_id).order_by(model.id)
            )
            exported[name] = [item.to_dict() for item in rows.scalars()]
        return exported

    # Delete one user-owned record from a supported agent-memory store.
    async def delete_record(
        self,
        user_id: str,
        memory_type: str,
        memory_id: str,
    ) -> bool:
        models: dict[str, Any] = {
            "cache": SemanticCacheEntry,
            "working": WorkingMemoryItem,
            "procedures": ProcedureMemory,
            "entities": MemoryEntity,
            "entity_relations": MemoryEntityRelation,
            "summaries": ConversationSummary,
        }
        model = models.get(memory_type)
        if model is None:
            return False
        result = await self.session.execute(
            delete(model).where(
                model.user_id == user_id,
                model.id == uuid.UUID(memory_id),
            )
        )
        await self.session.commit()
        return int(getattr(result, "rowcount", 0)) == 1

    # Delete every agent-memory record owned by one user.
    async def delete_all(self, user_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for name, model in (
            ("entity_relations", MemoryEntityRelation),
            ("knowledge_chunks", KnowledgeChunk),
            ("summaries", ConversationSummary),
            ("working", WorkingMemoryItem),
            ("semantic_cache", SemanticCacheEntry),
            ("procedures", ProcedureMemory),
            ("entities", MemoryEntity),
            ("knowledge_documents", KnowledgeDocument),
        ):
            result = await self.session.execute(
                delete(model).where(model.user_id == user_id)
            )
            counts[name] = int(getattr(result, "rowcount", 0))
        await self.session.commit()
        return counts
