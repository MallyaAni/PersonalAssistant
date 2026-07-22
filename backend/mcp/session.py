import contextlib
from collections.abc import AsyncIterator
from typing import Any

from backend.mcp.types import MCPServerConfig


# Open an initialized session to one server over its configured transport.
#
# Both transports are first class. stdio launches the server as a subprocess,
# which requires its runtime to be present locally; http connects to an
# already-running service, which does not. Keeping the choice here means the
# listing and invocation paths never learn which is in use.
@contextlib.asynccontextmanager
async def open_session(
    server: MCPServerConfig,
    timeout_seconds: float,
) -> AsyncIterator[Any]:
    # Imported lazily so importing this module never requires a live server.
    from mcp import ClientSession

    if server.transport == "http":
        from mcp.client.streamable_http import streamablehttp_client

        async with (
            streamablehttp_client(
                server.url,
                headers=dict(server.headers) or None,
                timeout=timeout_seconds,
            ) as (read, write, _get_session_id),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session
        return

    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=server.command, args=list(server.args))
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session
