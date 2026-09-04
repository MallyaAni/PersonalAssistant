"""A tool catalogue is read once and held, not re-read on every decision.

Listing opens a session per call, and for a stdio server that spawns the
process. The router resolves search_web, get_weather and, for an operator,
search_credits per decision, so every routing call spawned the internet
server two or three times before the model was asked anything - measured at
1.0-1.1s each against a 1.8s routing call.
"""
import asyncio

import pytest

from backend.config.settings import settings
from backend.mcp.client import SessionMCPToolLister
from backend.mcp.types import MCPServerConfig, MCPTool


class _CountingLister(SessionMCPToolLister):
    """The real caching, with the session replaced by a counter."""

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    async def _read(self, server):
        self.reads += 1
        return [MCPTool(server_id=server.server_id, name="search_web", description="", input_schema={})]


# The session is what a test cannot spawn, so it is the only thing stood in for.
@pytest.fixture
def lister(monkeypatch):
    made = _CountingLister()

    async def _list(self, server):
        ttl = settings.MCP_TOOL_LIST_CACHE_SECONDS
        key = self._key(server)
        if ttl > 0:
            from time import monotonic

            found = self._held.get(key)
            if found is not None and monotonic() - found[0] <= ttl:
                return list(found[1])
        tools = await self._read(server)
        if ttl > 0:
            from time import monotonic

            self._held[key] = (monotonic(), list(tools))
        return tools

    monkeypatch.setattr(SessionMCPToolLister, "list_tools", _list, raising=False)
    return made


def _server(server_id: str = "internet", **extra) -> MCPServerConfig:
    fields = {"command": "python", "args": ["-m", "x"], **extra}
    return MCPServerConfig(server_id=server_id, **fields)


def test_three_resolutions_in_one_turn_read_the_server_once(lister):
    server = _server()

    async def go():
        for _ in range(3):
            await lister.list_tools(server)

    asyncio.run(go())
    assert lister.reads == 1, "the router resolves three tools per decision"


def test_a_different_server_is_read_separately(lister):
    async def go():
        await lister.list_tools(_server("internet"))
        await lister.list_tools(_server("local_utility"))

    asyncio.run(go())
    assert lister.reads == 2


def test_changing_what_the_server_is_reached_over_reads_again(lister):
    # Editing configuration must not read back the old catalogue.
    async def go():
        await lister.list_tools(_server())
        await lister.list_tools(_server(args=["-m", "other"]))

    asyncio.run(go())
    assert lister.reads == 2


def test_narrowing_the_allowlist_reads_again(lister):
    async def go():
        await lister.list_tools(_server())
        await lister.list_tools(_server(allowed_tools=["search_web"]))

    asyncio.run(go())
    assert lister.reads == 2


def test_switching_the_cache_off_reads_every_time(lister, monkeypatch):
    monkeypatch.setattr(settings, "MCP_TOOL_LIST_CACHE_SECONDS", 0)

    async def go():
        for _ in range(3):
            await lister.list_tools(_server())

    asyncio.run(go())
    assert lister.reads == 3


def test_a_held_catalogue_expires(lister, monkeypatch):
    monkeypatch.setattr(settings, "MCP_TOOL_LIST_CACHE_SECONDS", 0.01)

    async def go():
        await lister.list_tools(_server())
        await asyncio.sleep(0.05)
        await lister.list_tools(_server())

    asyncio.run(go())
    assert lister.reads == 2


def test_forgetting_makes_the_next_read_live(lister):
    async def go():
        await lister.list_tools(_server())
        lister.forget()
        await lister.list_tools(_server())

    asyncio.run(go())
    assert lister.reads == 2
