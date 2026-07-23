"""Web-search adapter that executes through the guarded MCP tool boundary."""

import json
from typing import Any

from backend.core.interfaces import SearchProvider
from backend.search.types import SearchResult, SearchResults
from backend.services.mcp_invocation_service import MCPInvocationService


class MCPWebSearchProvider(SearchProvider):
    """Expose one configured read-only MCP tool as the web-search provider."""

    # Configure the fixed server/tool identity and result bounds.
    def __init__(
        self,
        invocation: MCPInvocationService,
        server_id: str,
        tool_name: str,
        max_results: int,
        max_content_chars: int,
        min_score: float,
    ) -> None:
        self.invocation = invocation
        self.server_id = server_id
        self.tool_name = tool_name
        self.max_results = max_results
        self.max_content_chars = max_content_chars
        self.min_score = min_score

    # Report the MCP identity so chat can display this provider as tool activity.
    @property
    def tool_identity(self) -> tuple[str, str]:
        return self.server_id, self.tool_name

    # Enable search only when local policy permits autonomous use of the server.
    def is_enabled(self) -> bool:
        return self.invocation.can_auto_invoke(self.server_id)

    # Parse one untrusted result while enforcing the local prompt-size budget.
    def _parse_result(self, raw: Any) -> SearchResult | None:
        if not isinstance(raw, dict):
            return None
        title = raw.get("title")
        url = raw.get("url")
        content = raw.get("content")
        score = raw.get("score")
        if not isinstance(title, str) or not isinstance(url, str):
            return None
        return SearchResult(
            title=title,
            url=url,
            content=(content if isinstance(content, str) else "")[
                : self.max_content_chars
            ],
            score=float(score) if isinstance(score, (int, float)) else 0.0,
        )

    # Execute the fixed search tool and convert its bounded JSON result.
    async def search(
        self,
        query: str,
        max_results: int | None = None,
    ) -> SearchResults:
        if not self.is_enabled():
            raise RuntimeError("The MCP internet-search server is not available.")
        bounded = max(1, min(max_results or self.max_results, self.max_results))
        result = await self.invocation.invoke(
            self.server_id,
            self.tool_name,
            {"query": query, "max_results": bounded},
        )
        if result.is_error:
            raise RuntimeError("The MCP internet-search tool returned an error.")
        try:
            payload = json.loads(result.content)
        except ValueError as exc:
            raise RuntimeError("The MCP internet-search result was invalid.") from exc
        raw_results = payload.get("results") if isinstance(payload, dict) else None
        parsed = []
        for raw in raw_results if isinstance(raw_results, list) else []:
            item = self._parse_result(raw)
            if item is not None and item.score >= self.min_score:
                parsed.append(item)
        return SearchResults(
            query=query,
            results=tuple(parsed[:bounded]),
            provider=f"mcp:{self.server_id}/{self.tool_name}",
        )
