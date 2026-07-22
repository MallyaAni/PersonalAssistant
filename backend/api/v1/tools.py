from typing import Annotated, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.auth import IdentityDependency, authorize_user
from backend.core.dependencies import MCPInvocationDependency
from backend.mcp.invocation import MCPInvocationError

router = APIRouter(prefix="/tools/{user_id}", tags=["tools"])


class ToolCallRequest(BaseModel):
    """One explicit request to call a discovered tool."""

    server_id: str = Field(min_length=1, max_length=200)
    tool_name: str = Field(min_length=1, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Sent back from a stored descriptor so the call can be refused when the
    # live contract no longer matches what was indexed.
    schema_fingerprint: str | None = Field(default=None, max_length=64)
    # An explicit human decision, never inferred from the request itself.
    confirmed: bool = False


# Reasons a call is refused before reaching the server, and how to read them.
_REFUSAL_STATUS = {
    "server_unavailable": 404,
    "tool_not_offered": 404,
    "confirmation_required": 409,
    "descriptor_changed": 409,
    "descriptor_poisoned": 422,
    "argument_withheld": 422,
    "missing_arguments": 422,
    "unknown_arguments": 422,
    "argument_type": 422,
}


# Invoke one discovered tool, refusing with a readable reason when a gate fails.
@router.post("/call")
async def call_tool(
    user_id: str,
    request: ToolCallRequest,
    service: MCPInvocationDependency,
    identity: IdentityDependency,
) -> dict[str, Any]:
    authorize_user(user_id, identity)
    try:
        result = await service.invoke(
            server_id=request.server_id,
            tool_name=request.tool_name,
            arguments=request.arguments,
            expected_fingerprint=request.schema_fingerprint,
            confirmed=request.confirmed,
        )
    except MCPInvocationError as exc:
        raise HTTPException(
            status_code=_REFUSAL_STATUS.get(exc.reason, 400),
            detail={"reason": exc.reason, "detail": exc.detail},
        ) from exc

    return {
        "server_id": result.server_id,
        "tool_name": result.tool_name,
        "content": result.content,
        "is_error": result.is_error,
        # Instruction-shaped output is reported rather than hidden, so a caller
        # can see that the result tried to steer the model.
        "markers": list(result.markers),
    }


# List the servers this deployment is configured to reach.
@router.get("/servers")
async def list_servers(
    user_id: str,
    service: MCPInvocationDependency,
    identity: IdentityDependency,
) -> list[dict[str, Any]]:
    authorize_user(user_id, identity)
    return [
        {
            "server_id": server.server_id,
            "risk_classification": server.risk_classification,
            "enabled": server.enabled,
            "requires_confirmation": server.risk_classification
            not in {"trusted", "read_only"},
        }
        for server in service.servers.values()
    ]


ToolCallResponse = Annotated[dict[str, Any], None]
