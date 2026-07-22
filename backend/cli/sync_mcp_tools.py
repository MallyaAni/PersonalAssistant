import argparse
import asyncio
import json
from collections.abc import Sequence

from backend.config.settings import settings
from backend.core.dependencies import get_embedding_provider
from backend.database.session import AsyncSessionLocal
from backend.mcp.client import StdioMCPToolLister
from backend.mcp.types import MCPServerConfig
from backend.memory.retrieval import SemanticRetrievalPolicy
from backend.services.mcp_registry_service import MCPRegistryService
from backend.services.tool_memory_service import ToolMemoryService


# Read configured servers, rejecting entries that do not declare an identity.
def load_servers() -> tuple[MCPServerConfig, ...]:
    raw = json.loads(settings.MCP_SERVERS_JSON or "[]")
    servers = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        server_id = entry.get("server_id")
        command = entry.get("command")
        if not server_id or not command:
            continue
        servers.append(
            MCPServerConfig(
                server_id=str(server_id),
                command=str(command),
                args=tuple(str(a) for a in entry.get("args", [])),
                risk_classification=str(entry.get("risk_classification", "untrusted")),
                enabled=bool(entry.get("enabled", True)),
            )
        )
    return tuple(servers)


# Define safe command-line options for tool discovery.
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Discover MCP tools and index them for semantic search.",
    )
    parser.add_argument("--user-id", required=True, help="Owner of the descriptors.")
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Report the live catalogue without indexing anything.",
    )
    return parser


# Connect to every configured server and refresh the descriptor index.
async def run(user_id: str, list_only: bool) -> dict[str, object]:
    servers = load_servers()
    if not servers:
        return {"error": "no MCP servers configured in MCP_SERVERS_JSON"}

    lister = StdioMCPToolLister(timeout_seconds=settings.MCP_LIST_TIMEOUT_SECONDS)
    if list_only:
        catalogue = []
        for server in servers:
            tools = await lister.list_tools(server)
            catalogue.append(
                {
                    "server_id": server.server_id,
                    "tools": [
                        {"name": t.name, "input_purpose": t.input_purpose}
                        for t in tools
                    ],
                }
            )
        return {"listed": catalogue}

    async with AsyncSessionLocal() as session:
        tool_memory = ToolMemoryService(
            session,
            get_embedding_provider(),
            SemanticRetrievalPolicy(
                max_cosine_distance=settings.MEMORY_SEMANTIC_MAX_COSINE_DISTANCE,
                max_results=settings.MEMORY_SEMANTIC_MAX_RESULTS,
                max_content_chars=settings.MEMORY_SEMANTIC_MAX_CONTENT_CHARS,
            ),
            settings.EMBEDDING_MODEL_VERSION,
        )
        registry = MCPRegistryService(lister, tool_memory, servers)
        return await registry.sync(user_id)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(json.dumps(asyncio.run(run(args.user_id, args.list_only)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
