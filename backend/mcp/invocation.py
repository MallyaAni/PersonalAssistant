import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from backend.mcp.session import open_session
from backend.mcp.types import MCPServerConfig, MCPTool

logger = logging.getLogger(__name__)

# A tool result is untrusted third-party content, exactly like a web page. It is
# bounded before it can reach the model so one verbose or hostile response
# cannot dominate the context.
_MAX_RESULT_CHARS = 4_000


class MCPInvocationError(RuntimeError):
    """Raised when a call is refused before it reaches the server."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ToolCallResult:
    """Bounded outcome of one tool invocation."""

    server_id: str
    tool_name: str
    content: str
    is_error: bool = False
    markers: tuple[str, ...] = field(default=())


class MCPToolInvoker(ABC):
    """Calls one tool on a live MCP server."""

    # Invoke a tool and return its bounded textual result.
    @abstractmethod
    async def call_tool(
        self,
        server: MCPServerConfig,
        tool_name: str,
        arguments: dict[str, Any],
        request_meta: dict[str, Any] | None = None,
    ) -> ToolCallResult: ...


class SessionMCPToolInvoker(MCPToolInvoker):
    """Invokes a tool over whichever transport a server is configured to use.

    The catalogue is re-read on every call rather than trusted from storage.
    A stored descriptor records what a server offered when it was indexed; it
    is not evidence of what the server offers now, and a call must be made
    against the live contract.
    """

    # Bound how long a server may take before the call is abandoned.
    def __init__(self, timeout_seconds: float = 60.0) -> None:
        self.timeout_seconds = timeout_seconds

    # Connect over the configured transport, re-resolve, then call.
    async def call_tool(
        self,
        server: MCPServerConfig,
        tool_name: str,
        arguments: dict[str, Any],
        request_meta: dict[str, Any] | None = None,
    ) -> ToolCallResult:
        async with open_session(server, self.timeout_seconds) as session:
            live = await session.list_tools()
            match = next((t for t in live.tools if t.name == tool_name), None)
            if match is None:
                # The tool was indexed once and is gone now: a stale vector must
                # never be able to authorize a call.
                raise MCPInvocationError(
                    "tool_not_offered",
                    f"{server.server_id} no longer offers {tool_name}",
                )

            response = await session.call_tool(
                tool_name,
                arguments,
                meta=request_meta,
            )
            parts: list[str] = []
            for item in response.content:
                text = getattr(item, "text", None)
                parts.append(text if isinstance(text, str) else f"[{item.type}]")
            joined = "\n".join(p for p in parts if p)
            return ToolCallResult(
                server_id=server.server_id,
                tool_name=tool_name,
                content=joined[:_MAX_RESULT_CHARS],
                is_error=bool(getattr(response, "isError", False)),
            )


# Confirm the live tool still matches the descriptor that was selected.
# A changed fingerprint means the description or schema moved after indexing,
# which is the rug-pull window, so the call is refused rather than guessed at.
def assert_descriptor_is_current(live: MCPTool, expected_fingerprint: str) -> None:
    if live.schema_fingerprint != expected_fingerprint:
        raise MCPInvocationError(
            "descriptor_changed",
            f"{live.server_id}/{live.name} no longer matches the indexed contract",
        )


# Check arguments against the tool's declared schema before any call is made.
# Only the shape is enforced: required keys, unknown keys and primitive types.
# A wrong tool usually cannot accept the right tool's arguments, so this is the
# cheapest signal that similarity selected badly.
def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return

    required = schema.get("required")
    missing = [
        name
        for name in (required if isinstance(required, list) else [])
        if name not in arguments
    ]
    if missing:
        raise MCPInvocationError("missing_arguments", ", ".join(sorted(missing)))

    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        raise MCPInvocationError("unknown_arguments", ", ".join(unknown))

    expected_types: dict[str, type | tuple[type, ...]] = {
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    for name, value in arguments.items():
        spec = properties.get(name)
        declared = spec.get("type") if isinstance(spec, dict) else None
        python_type = expected_types.get(str(declared))
        if python_type and not isinstance(value, python_type):
            raise MCPInvocationError(
                "argument_type",
                f"{name} expected {declared}",
            )
