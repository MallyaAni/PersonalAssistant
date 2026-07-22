import logging
from abc import ABC, abstractmethod

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


class StdioMCPToolLister(MCPToolLister):
    """Lists tools from a server launched as a local subprocess.

    The connection is opened per call and closed immediately. Discovery is
    infrequent, and a long-lived subprocess per configured server would be a
    standing resource cost for no benefit at this stage.
    """

    # Bound how long a server may take to answer before it is abandoned.
    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    # Connect, initialize, and page through the catalogue.
    async def list_tools(self, server: MCPServerConfig) -> list[MCPTool]:
        # Imported lazily so the package remains importable without a server.
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=server.command,
            args=list(server.args),
        )
        collected: list[MCPTool] = []
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
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
