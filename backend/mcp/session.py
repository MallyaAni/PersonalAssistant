import contextlib
import os
from collections.abc import AsyncIterator
from typing import Any

from backend.config.settings import settings
from backend.mcp.types import MCPServerConfig


# Resolve one inherited variable for a child server process.
#
# The process environment wins so an operator can override per run. Anything
# else falls back to loaded configuration, because pydantic-settings reads
# `.env` into the settings object without exporting to os.environ: a key
# configured only in `.env` is invisible to a subprocess that reads os.environ.
# Under Compose this happened to work, since Compose performs its own `.env`
# substitution into the container environment, so the gap only appeared when
# the backend ran from the host.
def _resolve_inherited(name: str) -> str | None:
    from_process = os.environ.get(name)
    if from_process:
        return from_process
    value = getattr(settings, name, None)
    if value is None or isinstance(value, bool):
        return None
    text = str(value)
    return text or None


# Build the environment a stdio server is launched with, carrying only the
# variables its configuration explicitly names.
def build_child_environment(
    server: MCPServerConfig,
    base_environment: dict[str, str],
) -> dict[str, str]:
    child = dict(base_environment)
    for name in server.inherit_env:
        resolved = _resolve_inherited(name)
        if resolved is not None:
            child[name] = resolved
    return child


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
    from mcp.client.stdio import get_default_environment, stdio_client

    child_env = build_child_environment(server, get_default_environment())
    params = StdioServerParameters(
        command=server.command,
        args=list(server.args),
        env=child_env,
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session
