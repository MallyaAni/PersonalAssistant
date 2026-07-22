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
        return collected
