import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from backend.mcp.invocation import MCPInvocationError

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Transport failures where the call may not have reached the server, so a
# replay-safe tool can be retried. A deterministic refusal is never in this
# set: re-running a schema or egress rejection would fail identically.
_TRANSIENT = (
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
    OSError,
)


@dataclass(frozen=True, slots=True)
class MCPRetryPolicy:
    """When and how to retry a tool call after a transient transport failure.

    Retrying is only ever safe for a call that can be replayed without effect.
    A dropped connection does not tell you whether the server executed the call
    before the response was lost, so retrying a write risks doing it twice. The
    caller decides replay-safety per server; this policy only governs how a
    replay-safe call is retried.
    """

    max_attempts: int = 3
    base_delay_seconds: float = 0.2
    max_delay_seconds: float = 2.0

    # A gate refusal or a withdrawn tool is deterministic, so only genuine
    # transport failures are treated as retryable.
    def is_transient(self, exc: BaseException) -> bool:
        if isinstance(exc, MCPInvocationError):
            return False
        return isinstance(exc, _TRANSIENT)

    # Exponential backoff, capped, so a flapping server is retried without
    # hammering it.
    def _delay(self, attempt: int) -> float:
        return float(
            min(self.base_delay_seconds * (2**attempt), self.max_delay_seconds)
        )

    # Run an operation, retrying only transient failures and only up to the
    # allowed number of attempts. Non-transient failures propagate at once.
    async def run(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        attempts: int,
        describe: str,
    ) -> T:
        bounded = max(1, min(attempts, self.max_attempts))
        last: BaseException | None = None
        for attempt in range(bounded):
            try:
                return await operation()
            except Exception as exc:
                if not self.is_transient(exc) or attempt == bounded - 1:
                    raise
                last = exc
                delay = self._delay(attempt)
                logger.warning(
                    "Transient failure on %s (attempt %d/%d): %s; retrying in %.2fs",
                    describe,
                    attempt + 1,
                    bounded,
                    type(exc).__name__,
                    delay,
                )
                await asyncio.sleep(delay)
        # Unreachable: the final attempt either returns or raises above.
        raise last if last is not None else RuntimeError("retry loop exhausted")
