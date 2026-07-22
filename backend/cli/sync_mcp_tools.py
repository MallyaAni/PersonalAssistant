import argparse
import asyncio
import json
from collections.abc import Sequence

from backend.config.settings import settings
from backend.core.dependencies import get_embedding_provider
from backend.database.session import AsyncSessionLocal
from backend.mcp.client import SessionMCPToolLister
from backend.mcp.config import _parse_server_entry
from backend.mcp.types import MCPServerConfig
from backend.memory.retrieval import SemanticRetrievalPolicy
from backend.services.mcp_registry_service import MCPRegistryService
from backend.services.tool_memory_service import ToolMemoryService


# Read configured servers, rejecting entries that do not declare an identity.
def load_servers() -> tuple[MCPServerConfig, ...]:
    raw = json.loads(settings.MCP_SERVERS_JSON or "[]")
    parsed = (_parse_server_entry(e) for e in (raw if isinstance(raw, list) else []))
    return tuple(server for server in parsed if server is not None)


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

    lister = SessionMCPToolLister(timeout_seconds=settings.MCP_LIST_TIMEOUT_SECONDS)
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
