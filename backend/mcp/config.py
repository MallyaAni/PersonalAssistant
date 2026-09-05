"""Parse configured MCP servers from their JSON representation."""

import json

from backend.mcp.types import MCPServerConfig, ToolPolicy

_EFFECTS = {"read", "write", "send", "spend", "mutate_external"}
_RETRIES = {"replay_safe", "once", "never"}
_APPROVALS = {"never", "consequential", "always"}


# Per-tool declarations from a server entry's `tools` object, keyed by tool
# name. A value the policy vocabulary does not know is dropped rather than
# read as something it is not; the tool then inherits from the classification.
def _parse_tool_policies(raw: object) -> tuple[tuple[str, ToolPolicy], ...]:
    if not isinstance(raw, dict):
        return ()
    parsed: list[tuple[str, ToolPolicy]] = []
    for name, declared in raw.items():
        if not isinstance(declared, dict) or not str(name).strip():
            continue
        effect = str(declared.get("effect", "")).strip()
        retry = str(declared.get("retry", "")).strip()
        approval = str(declared.get("approval", "")).strip()
        parsed.append(
            (
                str(name).strip(),
                ToolPolicy(
                    effect=effect if effect in _EFFECTS else "",
                    retry=retry if retry in _RETRIES else "",
                    approval=approval if approval in _APPROVALS else "",
                    idempotent=bool(declared.get("idempotent", False)),
                ),
            )
        )
    return tuple(parsed)


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
            forward_context=bool(entry.get("forward_context", False)),
            risk_classification=str(entry.get("risk_classification", "untrusted")),
            enabled=bool(entry.get("enabled", True)),
            discover=bool(entry.get("discover", False)),
            allowed_tools=tuple(str(name) for name in entry.get("allowed_tools", [])),
            navigates=bool(entry.get("navigates", False)),
            allowed_hosts=tuple(
                str(host).strip().casefold()
                for host in entry.get("allowed_hosts", [])
                if str(host).strip()
            ),
            tool_policies=_parse_tool_policies(entry.get("tools")),
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
