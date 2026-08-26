import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.interfaces import MemoryService, SemanticMemoryWriter
from backend.discovery.projection import interest_fact
from backend.embeddings.base import EmbeddingProvider
from backend.memory.purposes import VISUAL_ANALYSIS_PURPOSE
from backend.memory.repository import MemoryRepository
from backend.memory.retrieval import SemanticRetrievalPolicy
from backend.models.memory import UserProfile

# Semantic entries this system derived rather than the user stating them.
# They are retrievable by embedding and must not be listed back as facts.
DERIVED_PURPOSES = frozenset({VISUAL_ANALYSIS_PURPOSE})


# How many candidates to read for each one kept, since questions are dropped
# after the database has already applied its limit.
_RECALL_OVERFETCH = 4

logger = logging.getLogger(__name__)


# A bounded excerpt that says so: the marker is what stops a model from
# quoting a cut answer as though it were the whole of one.
def _excerpt(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


# A question the user once asked says nothing about them, and it embeds close
# to the question they are asking now - closer than the statement that would
# answer it. Measured on real history: "what do I like to watch?" matched an
# earlier "What are my interests?" at 0.361 and the true answer, "I am
# interested in true crime", at 0.380, so the useless turn outranked the useful
# one, and an identical question matched itself at 0.000.
#
# A shape test, not a judgement about meaning: it excludes the interrogative
# form whatever the turn happens to be about.
def _is_a_question(text: str) -> bool:
    return (text or "").strip().endswith("?")


class PostgresMemoryService(MemoryService, SemanticMemoryWriter):
    def __init__(
        self,
        session: AsyncSession,
        embeddings: EmbeddingProvider,
        retrieval_policy: SemanticRetrievalPolicy | None = None,
        embedding_model_version: str = "unknown",
    ):
        self.repo = MemoryRepository(session)
        self.embeddings = embeddings
        self.retrieval_policy = retrieval_policy or SemanticRetrievalPolicy()
        self.embedding_model_version = embedding_model_version

    async def get_user_profile(self, user_id: str) -> dict[str, Any]:
        profile = await self.repo.get_user_profile(user_id)
        if not profile:
            # Fallback/Default if no profile exists
            return {"user_id": user_id, "preferences": {}}
        result = profile.to_dict()
        if await self.repo.has_fact_history(user_id, "preferred_name"):
            current_name = await self.repo.get_current_fact(user_id, "preferred_name")
            result["name"] = current_name.value if current_name else None
        return result

    async def save_user_profile(self, profile: UserProfile) -> UserProfile:
        return await self.repo.save_user_profile(profile)

    async def upsert_user_profile(
        self,
        user_id: str,
        name: str | None,
        preferences: dict[str, Any],
    ) -> dict[str, Any]:
        profile = await self.repo.upsert_user_profile(user_id, name, preferences)
        return profile.to_dict()

    async def approve_preferred_name(
        self,
        user_id: str,
        name: str,
        source_conversation_id: str,
        source_trace_id: str,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        profile, fact, deduplicated = await self.repo.approve_preferred_name_fact(
            user_id,
            name,
            source_conversation_id,
            source_trace_id,
            expires_at,
        )
        return {
            "profile": profile.to_dict(),
            "fact": fact.to_dict(),
            "deduplicated": deduplicated,
        }

    # Approve a typed fact and return its serialized record.
    async def approve_fact(
        self,
        *,
        user_id: str,
        fact_type: str,
        fact_key: str,
        value: str,
        purpose: str,
        source_conversation_id: str | None,
        source_trace_id: str,
        expires_at: datetime | None,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        fact, deduplicated = await self.repo.approve_fact(
            user_id=user_id,
            fact_type=fact_type,
            fact_key=fact_key,
            value=value,
            purpose=purpose,
            source_conversation_id=source_conversation_id,
            source_trace_id=source_trace_id,
            expires_at=expires_at,
            extra_data=metadata,
        )
        return {"fact": fact.to_dict(), "deduplicated": deduplicated}

    # Approve one semantic Scout proposal as an all-or-nothing fact batch.
    async def approve_discovery_interests(
        self,
        *,
        user_id: str,
        labels: list[str],
        source_conversation_id: str,
        source_trace_id: str,
    ) -> dict[str, Any]:
        items = []
        seen: set[str] = set()
        for label in labels:
            fact = interest_fact(label)
            if fact.fact_key in seen:
                continue
            seen.add(fact.fact_key)
            items.append(
                {
                    "user_id": user_id,
                    "fact_type": fact.fact_type,
                    "fact_key": fact.fact_key,
                    "value": fact.value,
                    "purpose": fact.purpose,
                    "source_conversation_id": source_conversation_id,
                    "source_trace_id": source_trace_id,
                    "expires_at": None,
                    "extra_data": {
                        "source": "chat_approval",
                        "classifier": "semantic_memory_proposal_agent",
                    },
                }
            )
        results = await self.repo.approve_facts(items)
        return {
            "facts": [fact.to_dict() for fact, _ in results],
            "deduplicated": [deduplicated for _, deduplicated in results],
        }

    # Delete one user-owned fact.
    async def delete_fact(self, user_id: str, fact_id: str) -> bool:
        return await self.repo.delete_fact(user_id, fact_id)

    # Replace an existing fact with a new approved version.
    async def correct_fact(
        self,
        *,
        user_id: str,
        fact_id: str,
        value: str,
        source_conversation_id: str | None,
        source_trace_id: str,
        expires_at: datetime | None,
        metadata: dict[str, Any],
    ) -> dict[str, Any] | None:
        existing = await self.repo.get_fact(user_id, fact_id)
        if existing is None:
            return None
        return await self.approve_fact(
            user_id=user_id,
            fact_type=existing.fact_type,
            fact_key=existing.fact_key,
            value=value,
            purpose=existing.purpose,
            source_conversation_id=source_conversation_id,
            source_trace_id=source_trace_id,
            expires_at=expires_at,
            metadata=metadata,
        )

    # Delete all facts stored under one key for a user.
    async def clear_fact_key(self, user_id: str, fact_key: str) -> int:
        return await self.repo.clear_fact_key(user_id, fact_key)

    async def clear_preferred_name(self, user_id: str) -> dict[str, Any]:
        profile = await self.repo.clear_preferred_name_facts(user_id)
        if profile is None:
            return {"user_id": user_id, "preferences": {}}
        return profile.to_dict()

    async def get_episodic_memory(
        self,
        user_id: str,
        query: str,
    ) -> list[dict[str, Any]]:
        memories = await self.repo.get_episodic_memories(user_id, limit=5)
        return [m.to_dict() for m in memories]

    # Embed one retrieval query so a single turn can reuse the vector everywhere.
    async def embed_query(self, query: str) -> list[float]:
        return await asyncio.to_thread(self.embeddings.embed_query, query)

    async def get_semantic_memory(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        if query_embedding is None:
            query_embedding = await asyncio.to_thread(
                self.embeddings.embed_query, query
            )
        memories = await self.repo.get_semantic_memories(
            user_id,
            query_embedding,
            min(top_k, self.retrieval_policy.max_results),
            self.retrieval_policy.max_cosine_distance,
            embedding_model=getattr(self.embeddings, "model", "unknown"),
            embedding_version=self.embedding_model_version,
            embedding_dimension=len(query_embedding),
        )
        return self.retrieval_policy.select(memories, top_k)

    # The user's own past turns nearest this question.
    #
    # Kept beside `get_semantic_memory` rather than folded into it: both search
    # one vector, but a promoted fact is something the application asserts and
    # a recalled turn is something the user said, and the prompt has to be able
    # to tell the reader which is which.
    async def get_recalled_turns(
        self,
        user_id: str,
        query_embedding: list[float],
        top_k: int,
        max_cosine_distance: float,
        exclude_conversation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        # Over-fetched because the useless ones are dropped below, after the
        # text is readable: `query` is encrypted at rest, so the database
        # cannot tell a question from a statement and a predicate against that
        # column would match ciphertext and quietly return everything.
        rows = await self.repo.get_recalled_turns(
            user_id,
            query_embedding,
            top_k * _RECALL_OVERFETCH,
            max_cosine_distance,
            uuid.UUID(exclude_conversation_id) if exclude_conversation_id else None,
        )
        recalled: list[dict[str, Any]] = []
        # People repeat themselves. Three slots spent on one interest stated
        # three times crowds out the other two things they said.
        seen: set[str] = set()
        for turn, distance in rows:
            if len(recalled) >= top_k:
                break
            if _is_a_question(turn.query):
                continue
            spoken = (turn.query or "").strip()
            if spoken.casefold() in seen:
                continue
            seen.add(spoken.casefold())
            recalled.append(
                {
                    "said": turn.query,
                    "when": turn.created_at.isoformat() if turn.created_at else None,
                    "retrieval": {
                        "cosine_distance": round(distance, 6),
                        "relevance_score": round(max(0.0, 1.0 - distance), 6),
                    },
                }
            )
        return recalled

    # Search the transcript store for what the model asked to find.
    #
    # The active counterpart to `get_recalled_turns` above, and deliberately
    # less opinionated: questions are kept (the person may be looking for one
    # they asked), answers come back beside what was said, and the dedup is
    # on the exchange rather than the remark. Bounded excerpts, because a
    # 4k-token answer quoted whole would spend the evidence budget on one hit.
    async def search_turns(
        self,
        user_id: str,
        query_embedding: list[float],
        top_k: int,
        max_cosine_distance: float,
        exclude_conversation_id: str | None = None,
        created_after: Any = None,
        created_before: Any = None,
    ) -> list[dict[str, Any]]:
        rows = await self.repo.get_recalled_turns(
            user_id,
            query_embedding,
            top_k * _RECALL_OVERFETCH,
            max_cosine_distance,
            uuid.UUID(exclude_conversation_id) if exclude_conversation_id else None,
            created_after=created_after,
            created_before=created_before,
        )
        found: list[dict[str, Any]] = []
        seen: set[str] = set()
        for turn, distance in rows:
            if len(found) >= top_k:
                break
            said = (turn.query or "").strip()
            answered = (turn.response or "").strip()
            key = f"{said.casefold()}\n{answered.casefold()}"
            if not (said or answered) or key in seen:
                continue
            seen.add(key)
            found.append(
                {
                    "when": turn.created_at.isoformat() if turn.created_at else None,
                    "you_said": _excerpt(said, 1_000),
                    "assistant_said": _excerpt(answered, 1_500),
                    "retrieval": {
                        "cosine_distance": round(distance, 6),
                        "relevance_score": round(max(0.0, 1.0 - distance), 6),
                    },
                }
            )
        if not found:
            # The near-miss, recorded. The threshold was reasoned, not
            # measured, and an honest "I could not find it" at 0.6 with the
            # target sitting at 0.65 would otherwise be indistinguishable
            # from the row not existing. One tiny query on misses only, and
            # the number that tunes the constant lands in the log.
            await self._log_search_miss(
                user_id,
                query_embedding,
                max_cosine_distance,
                created_after,
                created_before,
            )
        return found

    # Log how near the nearest rejected turn was, so misses tune the threshold.
    async def _log_search_miss(
        self,
        user_id: str,
        query_embedding: list[float],
        threshold: float,
        created_after: Any,
        created_before: Any,
    ) -> None:
        try:
            nearest = await self.repo.get_recalled_turns(
                user_id,
                query_embedding,
                1,
                2.0,
                created_after=created_after,
                created_before=created_before,
            )
        except Exception:
            return
        if nearest:
            logger.info(
                "history_search_miss nearest=%.4f threshold=%.4f",
                nearest[0][1],
                threshold,
            )
        else:
            logger.info("history_search_miss no candidate rows in window")

    # Return a broad owned visual shortlist for a model to judge semantically.
    async def get_visual_memory_candidates(
        self,
        user_id: str,
        query_embedding: list[float],
        top_k: int = 8,
        max_cosine_distance: float = 0.65,
    ) -> list[dict[str, Any]]:
        rows = await self.repo.get_visual_semantic_memories(
            user_id,
            query_embedding,
            top_k,
            max_cosine_distance,
            embedding_model=getattr(self.embeddings, "model", "unknown"),
            embedding_version=self.embedding_model_version,
            embedding_dimension=len(query_embedding),
        )
        results: list[dict[str, Any]] = []
        for memory, distance in rows:
            item = memory.to_dict()
            item["retrieval"] = {
                "cosine_distance": round(distance, 6),
                "relevance_score": round(max(0.0, 1.0 - distance), 6),
            }
            results.append(item)
        return results

    async def save_episodic_memory(
        self,
        user_id: str,
        content: str,
        metadata: dict[str, Any],
        purpose: str = "user_explicit",
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        memory = await self.repo.save_episodic_memory(
            content,
            user_id,
            metadata,
            purpose,
            expires_at,
        )
        return memory.to_dict()

    async def save_semantic_memory(
        self,
        user_id: str,
        content: str,
        metadata: dict[str, Any],
        purpose: str = "user_explicit",
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        embedding = await asyncio.to_thread(self.embeddings.embed_text, content)
        memory = await self.repo.save_semantic_memory(
            user_id,
            content,
            embedding,
            metadata,
            purpose,
            getattr(self.embeddings, "model", "unknown"),
            self.embedding_model_version,
            len(embedding),
            expires_at,
        )
        return memory.to_dict()

    # Re-embed and replace one image's derived description without duplicates.
    async def replace_visual_semantic_memory(
        self,
        user_id: str,
        artifact_id: str,
        content: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        embedding = await asyncio.to_thread(self.embeddings.embed_text, content)
        memory = await self.repo.replace_visual_semantic_memory(
            user_id=user_id,
            artifact_id=artifact_id,
            content=content,
            embedding=embedding,
            metadata=metadata,
            purpose=VISUAL_ANALYSIS_PURPOSE,
            embedding_model=getattr(self.embeddings, "model", "unknown"),
            embedding_version=self.embedding_model_version,
            embedding_dimension=len(embedding),
        )
        return memory.to_dict()

    async def update_memory(
        self,
        user_id: str,
        memory_type: str,
        memory_id: str,
        content: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any] | None:
        embedding = None
        if memory_type == "semantic":
            embedding = await asyncio.to_thread(self.embeddings.embed_text, content)
        memory = await self.repo.update_memory(
            user_id,
            memory_type,
            memory_id,
            content,
            metadata,
            embedding,
        )
        return memory.to_dict() if memory else None

    # Return a personal-memory snapshot, bounded for the display path.
    async def get_memory_snapshot(
        self, user_id: str, limit: int | None = None
    ) -> dict[str, Any]:
        profile = await self.get_user_profile(user_id)
        episodic = [
            memory.to_dict()
            for memory in await self.repo.get_episodic_memories(user_id, limit=limit)
        ]
        # Derived entries are an index, not something the user told us.
        #
        # A vision analysis is written into semantic memory so an image can be
        # found by describing it, and it is deliberately filed under its own
        # purpose rather than as a stated fact. Nothing honoured that here, so
        # the panel listed 1,300 characters of image description under "facts
        # and preferences" — including, once, the assistant's own refusal to
        # edit a picture, presented back to the user as a fact about them.
        #
        # Retrieval is unaffected: image recall searches by embedding, not
        # through this snapshot.
        semantic = [
            memory.to_dict()
            for memory in await self.repo.list_semantic_memories(user_id, limit=limit)
            if getattr(memory, "purpose", "") not in DERIVED_PURPOSES
        ]
        facts = [
            fact.to_dict()
            for fact in await self.repo.list_memory_facts(user_id, limit=limit)
        ]
        return {
            "profile": profile,
            "episodic": episodic,
            "semantic": semantic,
            "facts": facts,
        }

    # Export the complete owned memory graph; export must not silently truncate.
    async def get_user_export(self, user_id: str) -> dict[str, Any]:
        return {
            "memory": await self.get_memory_snapshot(user_id, limit=None),
            "conversations": [
                conversation.to_dict()
                for conversation in await self.repo.list_conversations(user_id)
            ],
        }

    async def delete_memory(
        self,
        user_id: str,
        memory_type: str,
        memory_id: str,
    ) -> bool:
        return await self.repo.delete_memory(user_id, memory_type, memory_id)

    async def delete_all_user_memory(self, user_id: str) -> dict[str, int]:
        return await self.repo.delete_all_user_memory(user_id)
