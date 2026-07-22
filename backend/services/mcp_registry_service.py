import logging
from typing import Any

from backend.mcp.client import MCPToolLister
from backend.mcp.inspection import inspect_untrusted_text
from backend.mcp.types import MCPServerConfig
from backend.services.tool_memory_service import ToolMemoryService

logger = logging.getLogger(__name__)


class MCPRegistryService:
    """Syncs live MCP tool catalogues into the searchable descriptor index.

    The live server is the source of truth. Descriptors exist only so a large
    registry can be narrowed by meaning before anything reaches the model, and
    a stored descriptor never authorizes a call: whatever similarity selects
    must be re-resolved against the live catalogue before invocation.
    """

    # Compose the transport with the descriptor store that embeds each tool.
    def __init__(
        self,
        lister: MCPToolLister,
        tool_memory: ToolMemoryService,
        servers: tuple[MCPServerConfig, ...] = (),
    ) -> None:
        self.lister = lister
        self.tool_memory = tool_memory
        self.servers = servers

    # Refresh one user's descriptors from every enabled server.
    async def sync(self, user_id: str) -> dict[str, Any]:
        report: list[dict[str, Any]] = []
        for server in self.servers:
            if not server.enabled:
                report.append({"server_id": server.server_id, "status": "disabled"})
                continue
            report.append(await self._sync_server(user_id, server))
        indexed = sum(int(entry.get("indexed", 0)) for entry in report)
        return {"servers": report, "indexed": indexed}

    # Read one server's catalogue and index every tool it declares.
    async def _sync_server(
        self,
        user_id: str,
        server: MCPServerConfig,
    ) -> dict[str, Any]:
        try:
            tools = await self.lister.list_tools(server)
        except Exception as exc:
            # One unreachable server must not prevent the others from syncing.
            logger.warning(
                "MCP server %s could not be listed: %s",
                server.server_id,
                type(exc).__name__,
            )
            return {
                "server_id": server.server_id,
                "status": "unreachable",
                "error": type(exc).__name__,
            }

        indexed = 0
        quarantined: list[dict[str, Any]] = []
        for tool in tools:
            # A description carrying instructions is not indexed. Discovery
            # would put that text in front of the model, which is exactly what
            # a tool-poisoning payload wants.
            markers = inspect_untrusted_text(tool.description)
            if markers:
                logger.warning(
                    "Quarantined %s/%s: description contains %s",
                    tool.server_id,
                    tool.name,
                    ",".join(markers),
                )
                quarantined.append({"tool": tool.name, "markers": list(markers)})
                continue
            try:
                await self.tool_memory.upsert_descriptor(
                    user_id=user_id,
                    server_id=tool.server_id,
                    tool_name=tool.name,
                    description=tool.description,
                    input_purpose=tool.input_purpose,
                    schema_fingerprint=tool.schema_fingerprint,
                    # The fingerprint is the version that matters: it changes
                    # exactly when the contract does.
                    tool_version=tool.schema_fingerprint[:12],
                    # Trust is assigned locally by the operator, never read
                    # from the server's own description of itself.
                    risk_classification=server.risk_classification,
                )
                indexed += 1
            except Exception as exc:
                # A descriptor rejected for containing secret-shaped text is a
                # normal outcome, not a sync failure.
                logger.info(
                    "Descriptor %s/%s was not indexed: %s",
                    tool.server_id,
                    tool.name,
                    type(exc).__name__,
                )
        return {
            "server_id": server.server_id,
            "status": "ok",
            "declared": len(tools),
            "indexed": indexed,
            "quarantined": quarantined,
        }
