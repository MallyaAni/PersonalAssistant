import pytest

from backend.mcp.invocation import MCPInvocationError, ToolCallResult
from backend.mcp.retry import MCPRetryPolicy
from backend.mcp.types import MCPServerConfig, MCPTool
from backend.services.mcp_invocation_service import MCPInvocationService

# No real backoff during tests.
_FAST = MCPRetryPolicy(max_attempts=3, base_delay_seconds=0, max_delay_seconds=0)


def _tool() -> MCPTool:
    return MCPTool(
        server_id="srv",
        name="read",
        description="Reads a value",
        input_schema={"properties": {"key": {"type": "string"}}},
    )


class StubLister:
    async def list_tools(self, server):
        return [_tool()]


class FlakyInvoker:
    """Fail with a transport error a set number of times, then succeed."""

    def __init__(self, failures: int, error: Exception | None = None) -> None:
        self.remaining = failures
        self.error = error or ConnectionError("connection reset")
        self.attempts = 0

    async def call_tool(self, server, tool_name, arguments, request_meta=None):
        self.attempts += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise self.error
        return ToolCallResult(server.server_id, tool_name, "ok")


def _service(invoker, risk="read_only") -> MCPInvocationService:
    server = MCPServerConfig(server_id="srv", command="noop", risk_classification=risk)
    return MCPInvocationService(
        invoker,  # type: ignore[arg-type]
        StubLister(),  # type: ignore[arg-type]
        (server,),
        retry=_FAST,
    )


@pytest.mark.asyncio
async def test_a_transient_failure_on_a_read_is_retried_and_succeeds():
    invoker = FlakyInvoker(failures=2)

    result = await _service(invoker).invoke("srv", "read", {"key": "x"})

    assert result.content == "ok"
    assert invoker.attempts == 3


@pytest.mark.asyncio
async def test_a_write_is_never_retried_even_on_a_transient_failure():
    # A dropped connection does not prove the write did not execute, so a
    # consequential server gets exactly one attempt.
    invoker = FlakyInvoker(failures=1)
    service = _service(invoker, risk="untrusted")

    with pytest.raises(ConnectionError):
        await service.invoke("srv", "read", {"key": "x"}, confirmed=True)

    assert invoker.attempts == 1


@pytest.mark.asyncio
async def test_retries_are_bounded_and_then_the_failure_propagates():
    invoker = FlakyInvoker(failures=99)

    with pytest.raises(ConnectionError):
        await _service(invoker).invoke("srv", "read", {"key": "x"})

    assert invoker.attempts == 3


class DeterministicInvoker:
    """Always fail with a non-transport error."""

    def __init__(self) -> None:
        self.attempts = 0

    async def call_tool(self, server, tool_name, arguments, request_meta=None):
        self.attempts += 1
        raise ValueError("malformed response")


@pytest.mark.asyncio
async def test_a_non_transport_failure_is_not_retried():
    invoker = DeterministicInvoker()

    with pytest.raises(ValueError, match="malformed"):
        await _service(invoker).invoke("srv", "read", {"key": "x"})

    # Retrying a deterministic failure would only fail again, so it is not.
    assert invoker.attempts == 1


@pytest.mark.asyncio
async def test_the_policy_never_treats_a_gate_refusal_as_transient():
    policy = MCPRetryPolicy()

    assert policy.is_transient(MCPInvocationError("argument_withheld")) is False
    assert policy.is_transient(ConnectionError()) is True
    assert policy.is_transient(TimeoutError()) is True
    assert policy.is_transient(ValueError()) is False


@pytest.mark.asyncio
async def test_a_timeout_is_retried_for_a_replay_safe_server():
    invoker = FlakyInvoker(failures=1, error=TimeoutError())

    result = await _service(invoker).invoke("srv", "read", {"key": "x"})

    assert result.content == "ok"
    assert invoker.attempts == 2


@pytest.mark.asyncio
async def test_the_run_helper_respects_a_lower_attempt_ceiling():
    policy = MCPRetryPolicy(max_attempts=5, base_delay_seconds=0)
    calls = 0

    async def always_fail():
        nonlocal calls
        calls += 1
        raise ConnectionError()

    # A caller asking for one attempt gets one, regardless of the policy max.
    with pytest.raises(ConnectionError):
        await policy.run(always_fail, attempts=1, describe="test")

    assert calls == 1
