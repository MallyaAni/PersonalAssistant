import logging
from abc import ABC, abstractmethod

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

    The connection is opened per call and closed immediately. Discovery is
    infrequent, and holding a session open per configured server would be a
    standing resource cost for no benefit at this stage.
    """

    # Bound how long a server may take to answer before it is abandoned.
    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    # Connect over the configured transport and page through the catalogue.
    async def list_tools(self, server: MCPServerConfig) -> list[MCPTool]:
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
        return _permitted(server, collected)


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
