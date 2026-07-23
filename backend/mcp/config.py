"""Parse configured MCP servers from their JSON representation."""

import json

from backend.mcp.types import MCPServerConfig


# Build one server config from a raw JSON entry, or None when it is unusable.
def _parse_server_entry(entry: object) -> MCPServerConfig | None:
    if not isinstance(entry, dict) or not entry.get("server_id"):
        return None
    headers = entry.get("headers", {})
    try:
        return MCPServerConfig(
            server_id=str(entry["server_id"]),
            transport=str(entry.get("transport", "stdio")),
            command=str(entry.get("command", "")),
            args=tuple(str(a) for a in entry.get("args", [])),
            inherit_env=tuple(str(name) for name in entry.get("inherit_env", [])),
            url=str(entry.get("url", "")),
            headers=(
                tuple((str(k), str(v)) for k, v in headers.items())
                if isinstance(headers, dict)
                else ()
            ),
            risk_classification=str(entry.get("risk_classification", "untrusted")),
            enabled=bool(entry.get("enabled", True)),
        )
    except ValueError:
        # A misconfigured transport is skipped rather than crashing discovery.
        return None


# Parse every usable server entry from the operator-owned JSON setting.
def parse_server_configs(raw: str) -> tuple[MCPServerConfig, ...]:
    try:
        decoded = json.loads(raw or "[]")
    except ValueError:
        return ()
    if not isinstance(decoded, list):
        return ()
    parsed = (_parse_server_entry(entry) for entry in decoded)
    return tuple(server for server in parsed if server is not None)
