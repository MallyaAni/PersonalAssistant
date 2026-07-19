import json
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.services.agent_memory_manager import AgentMemoryManager
from backend.services.tool_memory_service import ToolMemoryService

_COORDINATOR_CACHE_MODEL = "memory-coordinator-v1"


class MemoryQueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_working: bool = True
    use_episodic: bool = False
    use_semantic: bool = True
    use_entities: bool = False
    use_knowledge: bool = False
    use_summaries: bool = False
    use_procedures: bool = False
    use_toolbox: bool = False
    reason_categories: list[str] = Field(default_factory=list, max_length=10)


# Decide which memory stores should handle a query.
def build_memory_query_plan(query: str) -> MemoryQueryPlan:
    normalized = f" {_normalize_query(query)} "
    category_terms = {
        "episodic": (
            " remember ",
            " last time ",
            " when did ",
            " experience ",
            " event ",
            " happened ",
        ),
        "entities": (
            " who is ",
            " person ",
            " contact ",
            " project ",
            " team ",
            " relationship ",
        ),
        "knowledge": (
            " document ",
            " notes ",
            " file ",
            " knowledge ",
            " according to ",
            " reference ",
        ),
        "summaries": (
            " summarize ",
            " summary ",
            " recap ",
            " earlier conversation ",
            " what did we ",
            " we agreed ",
        ),
        "procedures": (
            " how do i ",
            " how should i ",
            " steps ",
            " workflow ",
            " process ",
            " routine ",
            " procedure ",
        ),
        "toolbox": (
            " tool ",
            " calendar ",
            " email ",
            " schedule ",
            " mcp ",
        ),
    }
    matched = {
        category
        for category, terms in category_terms.items()
        if any(term in normalized for term in terms)
    }
    return MemoryQueryPlan(
        use_episodic="episodic" in matched,
        use_entities="entities" in matched,
        use_knowledge="knowledge" in matched,
        use_summaries="summaries" in matched,
        use_procedures="procedures" in matched,
        use_toolbox="toolbox" in matched,
        reason_categories=sorted(matched) or ["semantic_default"],
    )


# Normalize query text before matching routing terms.
def _normalize_query(query: str) -> str:
    return " ".join(query.strip().casefold().split())


class MemoryCoordinatorAgent:
    """Plans and curates retrieval without granting the model storage authority."""

    # Store the services and limits used to coordinate memory operations.
    def __init__(
        self,
        stores: AgentMemoryManager,
        toolbox: ToolMemoryService,
        cache_ttl: timedelta = timedelta(minutes=15),
        working_ttl: timedelta = timedelta(minutes=30),
        summary_interval: int = 10,
    ) -> None:
        self.stores = stores
        self.toolbox = toolbox
        self.cache_ttl = cache_ttl
        self.working_ttl = working_ttl
        self.summary_interval = summary_interval

    # Retrieve relevant memory and format it for the model prompt.
    async def prepare_context(
        self,
        user_id: str,
        conversation_id: str,
        query: str,
        trace_id: str,
        base_context: dict[str, Any],
        plan_result: tuple[MemoryQueryPlan, bool] | None = None,
    ) -> dict[str, Any]:
        plan, cache_hit = plan_result or await self.plan(user_id, query)
        now = datetime.now(UTC)
        await self.stores.working.upsert(
            user_id,
            conversation_id,
            "memory_query_plan",
            plan.model_dump_json(),
            "request_coordination",
            now + self.working_ttl,
        )

        context = dict(base_context)
        context["memory_plan"] = {
            **plan.model_dump(),
            "semantic_cache_hit": cache_hit,
            "trace_id": trace_id,
        }
        if plan.use_working:
            context["working"] = await self.stores.working.list_active(
                user_id, conversation_id
            )
        if plan.use_entities:
            context["entities"] = await self.stores.entities.search(user_id, query, 3)
        if plan.use_knowledge:
            context["knowledge"] = await self.stores.knowledge.search(user_id, query, 3)
        summaries = []
        latest_summary = await self.stores.summaries.latest(user_id, conversation_id)
        if latest_summary is not None:
            summaries.append(latest_summary)
        if plan.use_summaries:
            searched = await self.stores.summaries.search(user_id, query, 3)
            known_ids = {item["id"] for item in summaries}
            summaries.extend(item for item in searched if item["id"] not in known_ids)
        if summaries:
            context["summaries"] = summaries[:3]
        if plan.use_procedures:
            context["procedures"] = await self.stores.procedures.search(
                user_id, query, 3
            )
        if plan.use_toolbox:
            context["toolbox"] = await self.toolbox.search_descriptors(
                user_id, query, None, 3
            )
        return context

    # Update working memory and summaries after a completed chat turn.
    async def record_completed_turn(
        self,
        user_id: str,
        conversation_id: str,
        query: str,
        response: str,
        trace_id: str,
        prior_history: list[dict[str, Any]],
        turn_count: int,
    ) -> None:
        now = datetime.now(UTC)
        await self.stores.working.upsert(
            user_id,
            conversation_id,
            "last_exchange",
            json.dumps(
                {"query": query[-2_000:], "response": response[-4_000:]},
                separators=(",", ":"),
            ),
            "session_continuity",
            now + self.working_ttl,
        )
        if turn_count < self.summary_interval or turn_count % self.summary_interval:
            return

        previous = await self.stores.summaries.latest(user_id, conversation_id)
        recent_turns = [
            *prior_history[-(self.summary_interval - 1) :],
            {"query": query, "response": response},
        ]
        sections = []
        if previous is not None:
            sections.append(f"Previous digest:\n{previous['content']}")
        sections.append(
            "Recent exchanges:\n"
            + "\n".join(
                f"- User: {str(turn.get('query', ''))[:500]}\n"
                f"  AniOS: {str(turn.get('response', ''))[:500]}"
                for turn in recent_turns
            )
        )
        await self.stores.summaries.save(
            user_id,
            conversation_id,
            "\n\n".join(sections),
            turn_count,
            trace_id,
        )

    # Return a cached or newly computed query plan.
    async def plan(
        self,
        user_id: str,
        query: str,
    ) -> tuple[MemoryQueryPlan, bool]:
        cached = await self.stores.semantic_cache.get(
            user_id,
            query,
            _COORDINATOR_CACHE_MODEL,
            semantic_fallback=False,
        )
        if cached is not None:
            try:
                return MemoryQueryPlan.model_validate_json(cached["response"]), True
            except (KeyError, TypeError, ValidationError):
                pass

        plan = build_memory_query_plan(query)
        await self.stores.semantic_cache.put(
            user_id,
            query,
            json.dumps(plan.model_dump(), separators=(",", ":")),
            _COORDINATOR_CACHE_MODEL,
            datetime.now(UTC) + self.cache_ttl,
        )
        return plan, False
