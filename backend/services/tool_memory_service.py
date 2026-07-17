import asyncio
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, or_, update
from sqlalchemy.future import select
from sqlalchemy.orm import Session

from backend.embeddings.base import EmbeddingProvider
from backend.memory.retrieval import SemanticRetrievalPolicy
from backend.models.tool_memory import (
    ToolDescriptor,
    ToolPreference,
    ToolUsageOutcome,
)

_SENSITIVE_MARKER = re.compile(
    r"\b(password|passwd|secret|api[_ -]?(key|token)|access[_ -]?token|"
    r"authorization|bearer)\b",
    re.IGNORECASE,
)


def reject_sensitive_tool_memory(value: str) -> str:
    normalized = value.strip()
    if _SENSITIVE_MARKER.search(normalized):
        raise ValueError("Tool memory must not contain credentials or secret fields")
    return normalized


class ToolMemoryService:
    def __init__(
        self,
        session: Session,
        embeddings: EmbeddingProvider,
        retrieval_policy: SemanticRetrievalPolicy,
        embedding_version: str,
    ) -> None:
        self.session = session
        self.embeddings = embeddings
        self.retrieval_policy = retrieval_policy
        self.embedding_version = embedding_version

    async def upsert_descriptor(
        self,
        user_id: str,
        server_id: str,
        tool_name: str,
        description: str,
        input_purpose: str,
        schema_fingerprint: str,
        tool_version: str,
        risk_classification: str,
    ) -> dict[str, Any]:
        canonical = (
            f"server={server_id}\nname={tool_name}\ndescription={description}\n"
            f"input_purpose={input_purpose}\nversion={tool_version}\n"
            f"risk={risk_classification}"
        )
        embedding = await asyncio.to_thread(self.embeddings.embed_text, canonical)
        existing = self.session.execute(
            select(ToolDescriptor).where(
                ToolDescriptor.user_id == user_id,
                ToolDescriptor.server_id == server_id,
                ToolDescriptor.tool_name == tool_name,
                ToolDescriptor.schema_fingerprint == schema_fingerprint,
            )
        ).scalar_one_or_none()
        self.session.execute(
            update(ToolDescriptor)
            .where(
                ToolDescriptor.user_id == user_id,
                ToolDescriptor.server_id == server_id,
                ToolDescriptor.tool_name == tool_name,
                ToolDescriptor.schema_fingerprint != schema_fingerprint,
            )
            .values(active=False)
        )
        if existing is None:
            existing = ToolDescriptor(
                user_id=user_id,
                server_id=server_id,
                tool_name=tool_name,
                description=description,
                input_purpose=input_purpose,
                schema_fingerprint=schema_fingerprint,
                tool_version=tool_version,
                risk_classification=risk_classification,
                embedding=embedding,
                embedding_model=getattr(self.embeddings, "model", "unknown"),
                embedding_version=self.embedding_version,
                embedding_dimension=len(embedding),
                active=True,
            )
            self.session.add(existing)
        else:
            existing.description = description
            existing.input_purpose = input_purpose
            existing.tool_version = tool_version
            existing.risk_classification = risk_classification
            existing.embedding = embedding
            existing.embedding_version = self.embedding_version
            existing.embedding_dimension = len(embedding)
            existing.active = True
        self.session.commit()
        self.session.refresh(existing)
        return existing.to_dict()

    async def search_descriptors(
        self,
        user_id: str,
        query: str,
        server_id: str | None,
        top_k: int,
    ) -> list[dict[str, Any]]:
        query_embedding = await asyncio.to_thread(self.embeddings.embed_query, query)
        distance = ToolDescriptor.embedding.cosine_distance(query_embedding)
        filters = [ToolDescriptor.user_id == user_id, ToolDescriptor.active.is_(True)]
        if server_id:
            filters.append(ToolDescriptor.server_id == server_id)
        rows = self.session.execute(
            select(ToolDescriptor, distance.label("cosine_distance"))
            .where(*filters, distance <= self.retrieval_policy.max_cosine_distance)
            .order_by(distance, ToolDescriptor.id)
            .limit(min(top_k, self.retrieval_policy.max_results))
        ).all()
        results = []
        for descriptor, score in rows:
            item = descriptor.to_dict()
            item["retrieval"] = {
                "cosine_distance": round(float(score), 6),
                "relevance_score": round(max(0.0, 1.0 - float(score)), 6),
            }
            results.append(item)
        return results

    def _require_active_descriptor(
        self, user_id: str, server_id: str, tool_name: str
    ) -> ToolDescriptor:
        descriptor = self.session.execute(
            select(ToolDescriptor).where(
                ToolDescriptor.user_id == user_id,
                ToolDescriptor.server_id == server_id,
                ToolDescriptor.tool_name == tool_name,
                ToolDescriptor.active.is_(True),
            )
        ).scalar_one_or_none()
        if descriptor is None:
            raise LookupError("Active tool descriptor not found")
        return descriptor

    async def save_preference(
        self,
        user_id: str,
        server_id: str,
        tool_name: str,
        preference_key: str,
        value: str,
        purpose: str,
        source_trace_id: str,
        expires_at: datetime | None,
    ) -> dict[str, Any]:
        self._require_active_descriptor(user_id, server_id, tool_name)
        preference = self.session.execute(
            select(ToolPreference).where(
                ToolPreference.user_id == user_id,
                ToolPreference.server_id == server_id,
                ToolPreference.tool_name == tool_name,
                ToolPreference.preference_key == preference_key,
            )
        ).scalar_one_or_none()
        if preference is None:
            preference = ToolPreference(
                user_id=user_id,
                server_id=server_id,
                tool_name=tool_name,
                preference_key=preference_key,
                value=value,
                purpose=purpose,
                approval_state="approved",
                source_trace_id=uuid.UUID(source_trace_id),
                expires_at=expires_at,
            )
            self.session.add(preference)
        else:
            preference.value = value
            preference.purpose = purpose
            preference.approval_state = "approved"
            preference.source_trace_id = uuid.UUID(source_trace_id)
            preference.expires_at = expires_at
        self.session.commit()
        self.session.refresh(preference)
        return preference.to_dict()

    async def record_outcome(
        self,
        user_id: str,
        server_id: str,
        tool_name: str,
        outcome_category: str,
        source_trace_id: str,
    ) -> dict[str, Any]:
        self._require_active_descriptor(user_id, server_id, tool_name)
        outcome = ToolUsageOutcome(
            user_id=user_id,
            server_id=server_id,
            tool_name=tool_name,
            outcome_category=outcome_category,
            source_trace_id=uuid.UUID(source_trace_id),
            extra_data={},
        )
        self.session.add(outcome)
        self.session.commit()
        self.session.refresh(outcome)
        return outcome.to_dict()

    async def snapshot(self, user_id: str) -> dict[str, Any]:
        now = datetime.now(UTC)
        descriptors = self.session.execute(
            select(ToolDescriptor)
            .where(ToolDescriptor.user_id == user_id)
            .order_by(ToolDescriptor.created_at)
        ).scalars()
        preferences = self.session.execute(
            select(ToolPreference)
            .where(
                ToolPreference.user_id == user_id,
                ToolPreference.approval_state == "approved",
                or_(
                    ToolPreference.expires_at.is_(None),
                    ToolPreference.expires_at > now,
                ),
            )
            .order_by(ToolPreference.created_at)
        ).scalars()
        outcomes = self.session.execute(
            select(ToolUsageOutcome)
            .where(ToolUsageOutcome.user_id == user_id)
            .order_by(ToolUsageOutcome.created_at.desc())
            .limit(50)
        ).scalars()
        return {
            "descriptors": [item.to_dict() for item in descriptors],
            "preferences": [item.to_dict() for item in preferences],
            "outcomes": [item.to_dict() for item in outcomes],
        }

    async def delete_all(self, user_id: str) -> dict[str, int]:
        counts = {}
        for name, model in (
            ("outcomes", ToolUsageOutcome),
            ("preferences", ToolPreference),
            ("descriptors", ToolDescriptor),
        ):
            result = self.session.execute(delete(model).where(model.user_id == user_id))
            counts[name] = int(getattr(result, "rowcount", 0))
        self.session.commit()
        return counts
