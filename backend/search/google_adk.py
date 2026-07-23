"""Google ADK research subagent backed by Gemini Search Grounding."""

import asyncio
import logging
import uuid
from collections.abc import Callable
from typing import Any, Protocol, cast

from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.adk.tools.google_search_tool import google_search
from google.genai import types

from backend.core.interfaces import SearchProvider
from backend.search.quota import SQLiteDailySearchQuota
from backend.search.types import SearchResult, SearchResults

logger = logging.getLogger(__name__)
_APP_NAME = "anios-google-research"
_ANONYMOUS_USER_ID = "public-research"


class ResearchRunner(Protocol):
    """Expose only the ADK runner operations used by the provider."""

    session_service: Any

    # Stream one isolated research invocation.
    def run_async(self, **kwargs: Any) -> Any: ...

    # Release the runner and its in-memory session state.
    async def close(self) -> None: ...


# Create one request-isolated Gemini researcher with no access to AniOS memory.
def _default_runner_factory(model: str, max_output_tokens: int) -> ResearchRunner:
    agent = Agent(
        name="google_researcher",
        model=model,
        mode="chat",
        include_contents="none",
        instruction=(
            "Research only the public-information question supplied in this turn. "
            "Use Google Search when needed. Return a concise factual answer grounded "
            "in the cited web sources. Do not ask for or infer personal context."
        ),
        tools=[google_search],
        generate_content_config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=max_output_tokens,
        ),
    )
    return cast(
        ResearchRunner,
        InMemoryRunner(agent=agent, app_name=_APP_NAME),
    )


# Join text parts from one terminal ADK event without exposing other event data.
def _event_text(event: Any) -> str:
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    return "".join(
        text for part in parts if isinstance((text := getattr(part, "text", None)), str)
    ).strip()


# Map grounded answer segments back to each source cited by Gemini.
def _source_segments(metadata: Any) -> dict[int, list[str]]:
    mapped: dict[int, list[str]] = {}
    for support in getattr(metadata, "grounding_supports", None) or []:
        segment = getattr(getattr(support, "segment", None), "text", None)
        if not isinstance(segment, str) or not segment.strip():
            continue
        for raw_index in getattr(support, "grounding_chunk_indices", None) or []:
            if isinstance(raw_index, int):
                mapped.setdefault(raw_index, []).append(segment.strip())
    return mapped


# Convert Google grounding metadata into bounded, attributable web results.
def _grounded_results(
    metadata: Any,
    answer: str,
    max_results: int,
    max_content_chars: int,
) -> tuple[SearchResult, ...]:
    segments = _source_segments(metadata)
    results: list[SearchResult] = []
    for index, chunk in enumerate(getattr(metadata, "grounding_chunks", None) or []):
        web = getattr(chunk, "web", None)
        title = getattr(web, "title", None)
        uri = getattr(web, "uri", None)
        if not isinstance(title, str) or not isinstance(uri, str):
            continue
        supported = " ".join(dict.fromkeys(segments.get(index, []))).strip()
        if not supported and not results:
            supported = answer
        results.append(
            SearchResult(
                title=title[:200],
                url=uri[:500],
                content=supported[:max_content_chars],
                score=None,
                provider="google",
            )
        )
        if len(results) >= max_results:
            break
    return tuple(results)


class GoogleADKSearchProvider(SearchProvider):
    """Delegate one minimized public query to an isolated Gemini researcher."""

    # Configure ADK without giving the subagent conversation or user identity.
    def __init__(
        self,
        api_key: str | None,
        model: str,
        timeout_seconds: float,
        max_results: int,
        max_content_chars: int,
        quota: SQLiteDailySearchQuota,
        max_output_tokens: int = 1_024,
        runner_factory: Callable[[str, int], ResearchRunner] = _default_runner_factory,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_results = max_results
        self.max_content_chars = max_content_chars
        self.quota = quota
        self.max_output_tokens = max_output_tokens
        self.runner_factory = runner_factory

    # Enable the cloud researcher only when an operator supplied a Google key.
    def is_enabled(self) -> bool:
        return bool(self.api_key)

    # Execute one isolated ADK session and return only grounded public sources.
    async def search(
        self,
        query: str,
        max_results: int | None = None,
    ) -> SearchResults:
        if not self.is_enabled():
            raise RuntimeError("Google Search Grounding is not configured.")
        # Reserved before the call so concurrent requests cannot overshoot the
        # budget, and returned below whenever no usable result was produced.
        await self.quota.consume()
        bounded = max(1, min(max_results or self.max_results, self.max_results))
        session_id = str(uuid.uuid4())
        try:
            runner = self.runner_factory(self.model, self.max_output_tokens)
            try:
                await runner.session_service.create_session(
                    app_name=_APP_NAME,
                    user_id=_ANONYMOUS_USER_ID,
                    session_id=session_id,
                )
                answer, metadata = await asyncio.wait_for(
                    self._run_research(runner, session_id, query),
                    timeout=self.timeout_seconds,
                )
            finally:
                await runner.close()
            if metadata is None:
                raise RuntimeError("Google research returned no grounding metadata.")
            results = _grounded_results(
                metadata,
                answer,
                bounded,
                self.max_content_chars,
            )
            if not results:
                raise RuntimeError("Google research returned no attributable sources.")
        except Exception:
            # A refused or failed attempt spent no provider quota, so the local
            # budget must not record one either.
            await self.quota.release()
            raise
        return SearchResults(
            query=query,
            results=results,
            provider="google",
        )

    # Collect the terminal answer and latest grounding metadata from ADK events.
    async def _run_research(
        self,
        runner: ResearchRunner,
        session_id: str,
        query: str,
    ) -> tuple[str, Any | None]:
        answer = ""
        grounding_metadata = None
        message = types.Content(role="user", parts=[types.Part(text=query)])
        async for event in runner.run_async(
            user_id=_ANONYMOUS_USER_ID,
            session_id=session_id,
            new_message=message,
        ):
            metadata = getattr(event, "grounding_metadata", None)
            if metadata is not None:
                grounding_metadata = metadata
            is_final = getattr(event, "is_final_response", None)
            if callable(is_final) and is_final():
                candidate = _event_text(event)
                if candidate:
                    answer = candidate
        if not answer:
            logger.warning("Google research completed without terminal answer text")
        return answer, grounding_metadata
