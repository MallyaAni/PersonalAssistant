import logging
from abc import ABC, abstractmethod
from hashlib import sha256
from time import monotonic

from backend.config.settings import settings
from backend.mcp.session import open_session
from backend.mcp.types import MCPServerConfig, MCPTool

logger = logging.getLogger(__name__)

# Guard against a server advertising an unbounded catalogue. Pagination is
# followed, but only so far: a registry this large is a configuration problem,
# not something to absorb silently.
_MAX_TOOLS_PER_SERVER = 500
_MAX_PAGES = 50


class MCPToolLister(ABC):
    """Reads the live tool catalogue from one MCP server."""

    # Return every tool the server currently declares.
    @abstractmethod
    async def list_tools(self, server: MCPServerConfig) -> list[MCPTool]: ...


class SessionMCPToolLister(MCPToolLister):
    """Lists tools over whichever transport a server is configured to use.

    The connection is opened per call and closed immediately, and for a stdio
    server that means spawning the server process, importing it, listing, and
    tearing it down.

    That was written when the only caller was descriptor sync, and it says so:
    "discovery is infrequent". It stopped being true when the router began
    resolving live schemas per turn. `MainActionSelector.select` resolves
    `search_web`, `get_weather` and, for an operator, `search_credits`, so
    every routing decision spawned the internet server two or three times
    before the model was asked anything. Measured 2026-09-03 in the deployed
    image: 1.0-1.1s each, against a 1.8s routing call. Most of the time a turn
    spent choosing a tool went on re-reading a catalogue that had not changed.

    So a listing is now held for `MCP_TOOL_LIST_CACHE_SECONDS`. The cache is
    keyed on what would change the answer - the server's identity and the
    transport it is reached over - so editing a server's configuration does
    not read back the old catalogue. Staleness is bounded by the TTL and, at
    the point of an actual call, by the schema fingerprint the invocation
    service already asserts. Zero switches it off.
    """

    # Bound how long a server may take to answer before it is abandoned.
    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._held: dict[str, tuple[float, list[MCPTool]]] = {}

    # What identifies a catalogue: change any of it and the answer may differ.
    @staticmethod
    def _key(server: MCPServerConfig) -> str:
        material = "\x1f".join(
            str(part)
            for part in (
                server.server_id,
                getattr(server, "transport", ""),
                getattr(server, "url", ""),
                getattr(server, "command", ""),
                tuple(getattr(server, "args", ()) or ()),
                tuple(sorted(getattr(server, "allowed_tools", ()) or ())),
            )
        )
        return sha256(material.encode("utf-8", "replace")).hexdigest()

    # Forget every held catalogue. For tests, and for anything that changes
    # what a server would answer without changing its configuration.
    def forget(self) -> None:
        self._held.clear()

    # Connect over the configured transport and page through the catalogue.
    async def list_tools(self, server: MCPServerConfig) -> list[MCPTool]:
        ttl = settings.MCP_TOOL_LIST_CACHE_SECONDS
        key = self._key(server)
        if ttl > 0:
            found = self._held.get(key)
            if found is not None and monotonic() - found[0] <= ttl:
                return list(found[1])
        collected: list[MCPTool] = []
        async with open_session(server, self.timeout_seconds) as session:
            cursor: str | None = None
            for _ in range(_MAX_PAGES):
                page = await session.list_tools(cursor)
                for tool in page.tools:
                    collected.append(
                        MCPTool(
                            server_id=server.server_id,
                            name=tool.name,
                            description=tool.description or "",
                            input_schema=dict(tool.inputSchema or {}),
                        )
                    )
                    if len(collected) >= _MAX_TOOLS_PER_SERVER:
                        logger.warning(
                            "Server %s exceeded %d tools; truncating",
                            server.server_id,
                            _MAX_TOOLS_PER_SERVER,
                        )
                        return collected
                cursor = page.nextCursor
                if not cursor:
                    break
        permitted = _permitted(server, collected)
        if ttl > 0:
            self._held[key] = (monotonic(), list(permitted))
        return permitted


# The catalogue narrowed to what the operator permits.
#
# Filtered here rather than at each caller, because there are three - the
# invocation service, the registry and the descriptor sync - and a control
# that has to be composed correctly in three places is a control that will one
# day be composed incorrectly in one. Everything reads the catalogue through
# this function, so a tool nobody permitted is never indexed, never offered to
# the model, and never resolvable.
def _permitted(server: MCPServerConfig, tools: list[MCPTool]) -> list[MCPTool]:
    if not server.allowed_tools:
        return tools
    allowed = set(server.allowed_tools)
    kept = [tool for tool in tools if tool.name in allowed]
    withheld = sorted({tool.name for tool in tools} - allowed)
    if withheld:
        # Named, not counted. A third-party catalogue that grows a tool is
        # worth an operator seeing by name, and the alternative - silence - is
        # how a `browser_run_code_unsafe` arrives unnoticed.
        logger.info(
            "Server %s offers %d tool(s) outside its allowlist, withheld: %s",
            server.server_id,
            len(withheld),
            ", ".join(withheld)[:400],
        )
    missing = sorted(allowed - {tool.name for tool in tools})
    if missing:
        # The other direction, and it matters just as much: a permitted tool
        # the server no longer offers means the contract moved under us.
        logger.warning(
            "Server %s no longer offers permitted tool(s): %s",
            server.server_id,
            ", ".join(missing),
        )
    return kept
