import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.memory.digest import summarise
from backend.services.agent_memory_manager import AgentMemoryManager
from backend.services.tool_memory_service import ToolMemoryService

# Retrieved context lists that compete for one shared per-turn relevance budget.
_BUDGETED_KEYS = ("semantic", "entities", "knowledge", "procedures", "toolbox")


# Build a conversation digest that cannot grow without bound.
#
# The previous implementation appended each interval's verbatim exchanges to
# the digest before it, so the "summary" only ever got longer - and the latest
# one is injected into every prompt. At a ten-turn interval a hundred-turn
# conversation would carry roughly a hundred kilobytes of truncated transcript
# into every request, which is the opposite of what a digest is for. It had
# barely been exercised, so nobody had seen it yet.
#
# This still does not summarise: nothing here asks a model to compress meaning,
# because that costs a call and belongs behind its own setting and prompt. What
# it guarantees is the property the old one lacked - a ceiling. The newest
# material is kept and the oldest is dropped, which for a conversation is the
# right direction: a digest exists so the distant past is *recoverable*, and
# the recent past is what the current turn is likely to depend on.
def _digest(
    previous: dict[str, Any] | None,
    recent_turns: list[dict[str, Any]],
    max_chars: int,
) -> str:
    exchanges = "\n".join(
        f"- User: {str(turn.get('query', ''))[:500]}\n"
        f"  AniOS: {str(turn.get('response', ''))[:500]}"
        for turn in recent_turns
    )
    recent = f"Recent exchanges:\n{exchanges}"
    if previous is None:
        return recent[:max_chars]

    # Whatever is left after the newest material has taken what it needs. The
    # older digest is trimmed from its front, since its own tail is the more
    # recent half of it.
    spare = max_chars - len(recent) - len("Previous digest:\n\n\n")
    if spare <= 0:
        return recent[:max_chars]
    carried = str(previous.get("content") or "")[-spare:]
    if not carried.strip():
        return recent[:max_chars]
    return f"Previous digest:\n{carried}\n\n{recent}"[:max_chars]


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

    # Report whether any vector store is selected, so the query embeds only once.
    def needs_vector(self) -> bool:
        return any(
            (
                self.use_semantic,
                self.use_entities,
                self.use_knowledge,
                self.use_summaries,
                self.use_procedures,
                self.use_toolbox,
            )
        )


# Decide which memory stores should handle a query.
#
# Every embedded store is searched on every turn. Keyword gating was a losing
# game for the same reason it was for web-search routing: "what did my dentist
# recommend" names an entity worth recalling but contains none of the entity
# trigger words, so a keyword gate silently drops it. Recall should surface
# anything important regardless of phrasing. This is safe to do unconditionally
# because each store already filters by a cosine-distance threshold - an
# unrelated store returns nothing rather than polluting the prompt - and the
# shared relevance budget keeps only the closest matches across all stores.
def build_memory_query_plan(query: str) -> MemoryQueryPlan:
    normalized = f" {_normalize_query(query)} "
    # Episodic memory is the one store with no embedding, so it cannot be
    # recalled by similarity and stays selected by explicit intent until it is
    # embedded. Everything else is always-on.
    # Space-delimited so a term matches a word rather than a fragment. Stems
    # are listed explicitly for the same reason: " event " does not match
    # "events", and the commonest question this store exists to serve - "what
    # events are on this weekend" - was silently excluded by that one letter
    # until 2026-08-29.
    episodic_terms = (
        " remember ",
        " last time ",
        " when did ",
        " experience ",
        " experiences ",
        " event ",
        " events ",
        " happened ",
    )
    use_episodic = any(term in normalized for term in episodic_terms)
    reason_categories = ["always_on_similarity"]
    if use_episodic:
        reason_categories.append("episodic_keyword")
    return MemoryQueryPlan(
        use_episodic=use_episodic,
        use_entities=True,
        use_knowledge=True,
        use_summaries=True,
        use_procedures=True,
        use_toolbox=True,
        reason_categories=reason_categories,
    )


# Normalize query text before matching routing terms.
def _normalize_query(query: str) -> str:
    return " ".join(query.strip().casefold().split())


# Derive a stable text fingerprint used to dedup retrieved items across stores.
def _content_fingerprint(item: dict[str, Any]) -> str:
    for key in ("content", "canonical_name", "name", "description", "value"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_query(value)
    return _normalize_query(
        json.dumps(
            {k: v for k, v in item.items() if k != "retrieval"},
            sort_keys=True,
            default=str,
        )
    )


# Keep operational coordination records out of model-facing working memory.
def _visible_working(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if item.get("purpose") != "request_coordination"]


class MemoryCoordinatorAgent:
    """Plans and curates retrieval without granting the model storage authority."""

    # Store the services and limits used to coordinate memory operations.
    def __init__(
        self,
        stores: AgentMemoryManager,
        toolbox: ToolMemoryService,
        working_ttl: timedelta = timedelta(minutes=30),
        summary_interval: int = 10,
        max_context_items: int = 12,
        max_context_chars: int = 6_000,
        digest_max_chars: int = 4_000,
        # Optional on purpose. Every existing caller and test constructs this
        # without one and keeps the truncating behaviour, so compression is an
        # addition rather than a new requirement.
        summariser: Any | None = None,
    ) -> None:
        self.stores = stores
        self.toolbox = toolbox
        self.working_ttl = working_ttl
        self.summary_interval = summary_interval
        self.max_context_items = max_context_items
        self.max_context_chars = max_context_chars
        self.digest_max_chars = digest_max_chars
        self.summariser = summariser

    # Retrieve relevant memory and format it for the model prompt.
    async def prepare_context(
        self,
        user_id: str,
        conversation_id: str,
        query: str,
        trace_id: str,
        base_context: dict[str, Any],
        plan_result: tuple[MemoryQueryPlan, bool] | None = None,
        query_embedding: list[float] | None = None,
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

        # Embed the query once so every selected vector store reuses one vector.
        if query_embedding is None and plan.needs_vector():
            query_embedding = await self.stores.embed_query(query)

        context = dict(base_context)
        context["memory_plan"] = {
            **plan.model_dump(),
            "semantic_cache_hit": cache_hit,
            "trace_id": trace_id,
        }
        if plan.use_working:
            working = await self.stores.working.list_active(user_id, conversation_id)
            # The plan is persisted for operational inspection, not as a fact
            # for the reply model. Feeding its own routing JSON back as personal
            # memory wastes context and lets internal coordination bias answers.
            visible_working = _visible_working(working)
            context["working"] = visible_working
        if plan.use_entities:
            context["entities"] = await self.stores.entities.search(
                user_id, query, 3, query_embedding
            )
        if plan.use_knowledge:
            context["knowledge"] = await self.stores.knowledge.search(
                user_id, query, 3, query_embedding
            )
        summaries = []
        latest_summary = await self.stores.summaries.latest(user_id, conversation_id)
        if latest_summary is not None:
            summaries.append(latest_summary)
        if plan.use_summaries:
            searched = await self.stores.summaries.search(
                user_id, query, 3, query_embedding
            )
            known_ids = {item["id"] for item in summaries}
            summaries.extend(item for item in searched if item["id"] not in known_ids)
        if summaries:
            context["summaries"] = summaries[:3]
        if plan.use_procedures:
            context["procedures"] = await self.stores.procedures.search(
                user_id, query, 3, query_embedding
            )
        if plan.use_toolbox:
            context["toolbox"] = await self.toolbox.search_descriptors(
                user_id, query, None, 3, query_embedding
            )
        return self._apply_context_budget(context)

    # Enforce one shared relevance/character budget and dedup across stores.
    def _apply_context_budget(self, context: dict[str, Any]) -> dict[str, Any]:
        candidates: list[tuple[float, str, dict[str, Any]]] = []
        for key in _BUDGETED_KEYS:
            for item in context.get(key, []) or []:
                score = float(item.get("retrieval", {}).get("relevance_score", 0.0))
                candidates.append((score, key, item))
        candidates.sort(key=lambda entry: entry[0], reverse=True)

        kept: dict[str, list[dict[str, Any]]] = {key: [] for key in _BUDGETED_KEYS}
        seen: set[str] = set()
        used_items = 0
        used_chars = 0
        for _score, key, item in candidates:
            if used_items >= self.max_context_items:
                break
            fingerprint = _content_fingerprint(item)
            if fingerprint in seen:
                continue
            size = len(fingerprint)
            if used_chars + size > self.max_context_chars:
                continue
            seen.add(fingerprint)
            kept[key].append(item)
            used_items += 1
            used_chars += size

        for key in _BUDGETED_KEYS:
            if key in context:
                if kept[key]:
                    context[key] = kept[key]
                else:
                    context.pop(key, None)
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
        # Compression first, truncation underneath. The bound is not a fallback
        # bolted on after: it shipped on its own, so this call can fail - model
        # down, timeout, empty answer - without the unbounded growth returning.
        carried = str((previous or {}).get("content") or "")
        # In a worker thread because `summarise` is a synchronous model call
        # that can run for the length of a full generation. Awaited inline it
        # held the event loop itself, so a digest turn stalled every other
        # request on the server, not just this conversation's.
        written = await asyncio.to_thread(
            summarise, self.summariser, carried, recent_turns
        )
        content = written or _digest(previous, recent_turns, self.digest_max_chars)
        await self.stores.summaries.save(
            user_id,
            conversation_id,
            content[: self.digest_max_chars],
            turn_count,
            trace_id,
        )

    # Compute the deterministic query plan without an embedding round trip.
    async def plan(
        self,
        user_id: str,
        query: str,
    ) -> tuple[MemoryQueryPlan, bool]:
        # Routing is deterministic keyword matching, so recomputing is far cheaper
        # than embedding the query to store and re-read a cached plan.
        return build_memory_query_plan(query), False
