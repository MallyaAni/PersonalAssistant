"""The MCP boundary reads each tool's contract, not its server's trust.

Three gaps the 2026-09-04 review named, each pinned: a trusted server's
write was retried as though a lost response proved nothing happened; only the
top level of a tool's schema was checked; and a string nested inside an
object or array left the machine unscreened.
"""

import pytest

from backend.mcp.config import parse_server_configs
from backend.mcp.invocation import (
    MCPInvocationError,
    ToolCallResult,
    validate_arguments,
)
from backend.mcp.retry import MCPRetryPolicy
from backend.mcp.types import MCPServerConfig, MCPTool, ToolPolicy
from backend.services.mcp_invocation_service import MCPInvocationService

SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "count": {"type": "integer", "minimum": 0},
        "mode": {"type": "string", "enum": ["quick", "full"]},
        "payload": {
            "type": "object",
            "properties": {
                "note": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            },
            "required": ["note"],
            "additionalProperties": False,
        },
    },
    "required": ["message"],
}


def _tool(name: str = "echo") -> MCPTool:
    return MCPTool(server_id="srv", name=name, description="Echoes", input_schema=SCHEMA)


class _Lister:
    async def list_tools(self, server):
        return [_tool()]


class _FlakyInvoker:
    """Fail with a transport error the first time, then succeed."""

    def __init__(self) -> None:
        self.calls = 0

    async def call_tool(self, server, tool_name, arguments, request_meta=None):
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("dropped")
        return ToolCallResult(server_id=server.server_id, tool_name=tool_name, content="ok")


class _RecordingInvoker:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def call_tool(self, server, tool_name, arguments, request_meta=None):
        self.calls.append(arguments)
        return ToolCallResult(server_id=server.server_id, tool_name=tool_name, content="ok")


def _service(invoker, risk: str, policies=()) -> MCPInvocationService:
    server = MCPServerConfig(
        server_id="srv",
        command="noop",
        risk_classification=risk,
        tool_policies=tuple(policies),
    )
    return MCPInvocationService(
        invoker,
        _Lister(),
        servers=(server,),
        retry=MCPRetryPolicy(base_delay_seconds=0.0, max_delay_seconds=0.0),
    )


# A read-only server's dropped call is replayed; a trusted server's is not,
# because trust says nothing about whether the write already happened.
@pytest.mark.asyncio
async def test_a_trusted_servers_write_is_never_retried_but_a_read_only_call_is():
    replayed = _FlakyInvoker()
    result = await _service(replayed, "read_only").invoke("srv", "echo", {"message": "hi"})
    assert result.content == "ok"
    assert replayed.calls == 2

    not_replayed = _FlakyInvoker()
    with pytest.raises(ConnectionError):
        await _service(not_replayed, "trusted").invoke("srv", "echo", {"message": "hi"})
    assert not_replayed.calls == 1


# A tool the operator declares a read is replayed even on a trusted server;
# one declared a write stays unreplayed however it is labelled.
@pytest.mark.asyncio
async def test_a_declared_read_on_a_trusted_server_is_replayed():
    invoker = _FlakyInvoker()
    service = _service(invoker, "trusted", [("echo", ToolPolicy(effect="read"))])
    assert (await service.invoke("srv", "echo", {"message": "hi"})).content == "ok"
    assert invoker.calls == 2

    invoker = _FlakyInvoker()
    service = _service(
        invoker, "trusted", [("echo", ToolPolicy(effect="write", retry="replay_safe"))]
    )
    with pytest.raises(ConnectionError):
        await service.invoke("srv", "echo", {"message": "hi"})
    assert invoker.calls == 1


# A tool declared idempotent by its server may be replayed: the server dedupes
# the call by its arguments, so a second delivery cannot double the effect.
@pytest.mark.asyncio
async def test_an_idempotent_write_may_be_replayed():
    invoker = _FlakyInvoker()
    policy = ToolPolicy(effect="write", retry="replay_safe", idempotent=True)
    service = _service(invoker, "trusted", [("echo", policy)])
    assert (await service.invoke("srv", "echo", {"message": "hi"})).content == "ok"
    assert invoker.calls == 2


# Approval is per tool with the classification as its floor.
@pytest.mark.asyncio
async def test_approval_is_read_off_the_tool_and_never_below_the_server():
    always = _service(_RecordingInvoker(), "read_only", [("echo", ToolPolicy(approval="always"))])
    with pytest.raises(MCPInvocationError) as refused:
        await always.invoke("srv", "echo", {"message": "hi"})
    assert refused.value.reason == "confirmation_required"
    assert (await always.invoke("srv", "echo", {"message": "hi"}, confirmed=True)).content == "ok"

    lowered = _service(
        _RecordingInvoker(), "untrusted", [("echo", ToolPolicy(effect="read", approval="never"))]
    )
    with pytest.raises(MCPInvocationError) as still_refused:
        await lowered.invoke("srv", "echo", {"message": "hi"})
    assert still_refused.value.reason == "confirmation_required"


# The contract a later step reads: a read on a trusted server may be one, an
# untrusted server's tool may not.
def test_contract_for_reads_policy_over_classification():
    trusted_read = _service(_RecordingInvoker(), "trusted", [("echo", ToolPolicy(effect="read"))])
    assert trusted_read.contract_for("srv", "echo").allows_later_step(60.0)
    assert not _service(_RecordingInvoker(), "trusted").contract_for("srv", "echo").allows_later_step(60.0)
    assert not _service(_RecordingInvoker(), "untrusted").contract_for("srv", "echo").allows_later_step(60.0)
    assert _service(_RecordingInvoker(), "read_only").contract_for("srv", "other").effect == "read"
    assert _service(_RecordingInvoker(), "read_only").contract_for("nope", "echo").effect == "mutate_external"


# A secret inside a nested object or an array is withheld, and the refusal
# names where it was.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "where"),
    [
        ({"message": "hi", "payload": {"note": "key sk-abcdefghijklmnopqrstuvwxyz0123456789"}}, "payload.note"),
        ({"message": "hi", "payload": {"note": "fine", "tags": ["ok", "sk-abcdefghijklmnopqrstuvwxyz0123456789"]}}, "payload.tags[1]"),
    ],
)
async def test_nested_strings_are_screened(arguments, where):
    invoker = _RecordingInvoker()
    with pytest.raises(MCPInvocationError) as refused:
        await _service(invoker, "read_only").invoke("srv", "echo", arguments)
    assert refused.value.reason == "argument_withheld"
    assert refused.value.detail.startswith(where), refused.value.detail
    assert invoker.calls == []


# Clean nested values pass through the screen unchanged.
@pytest.mark.asyncio
async def test_clean_nested_values_reach_the_server_intact():
    invoker = _RecordingInvoker()
    arguments = {"message": "hi", "payload": {"note": "bring the cake", "tags": ["a", "b"]}}
    await _service(invoker, "read_only").invoke("srv", "echo", arguments)
    assert invoker.calls == [arguments]


# The whole declared schema is enforced, not only its top level.
@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        ({"message": "hi", "count": -1}, "argument_schema"),
        ({"message": "hi", "mode": "sideways"}, "argument_schema"),
        ({"message": "hi", "payload": {"tags": []}}, "argument_schema"),
        ({"message": "hi", "payload": {"note": "x", "extra": 1}}, "argument_schema"),
        ({"message": "hi", "payload": {"note": "x", "tags": [1]}}, "argument_schema"),
        ({"message": "hi", "payload": {"note": "x", "tags": ["a", "b", "c", "d"]}}, "argument_schema"),
        ({"message": "hi", "count": True}, "argument_type"),
        ({"message": "hi", "payload": "not an object"}, "argument_type"),
    ],
)
def test_nested_schema_violations_are_refused(arguments, reason):
    with pytest.raises(MCPInvocationError) as refused:
        validate_arguments(SCHEMA, arguments)
    assert refused.value.reason == reason


def test_valid_nested_arguments_pass():
    validate_arguments(
        SCHEMA,
        {"message": "hi", "count": 2, "mode": "quick", "payload": {"note": "x", "tags": ["a"]}},
    )


# A schema the validator cannot read is not a contract this system calls against.
def test_an_unreadable_schema_refuses_the_call():
    with pytest.raises(MCPInvocationError) as refused:
        validate_arguments({"type": "object", "properties": {"a": {"type": "wibble"}}}, {"a": 1})
    assert refused.value.reason == "schema_invalid"


# The operator's per-tool declarations parse from the server entry, and a
# value policy does not know is dropped rather than read as something else.
def test_tool_policies_parse_from_the_server_entry():
    raw = (
        '[{"server_id":"srv","command":"noop","risk_classification":"trusted",'
        '"tools":{"lookup":{"effect":"read"},'
        '"send":{"approval":"always","retry":"sometimes","effect":"teleport"}}}]'
    )
    (server,) = parse_server_configs(raw)
    assert server.policy_for("lookup") == ToolPolicy(effect="read")
    assert server.policy_for("send") == ToolPolicy(approval="always")
    assert server.policy_for("missing") is None
