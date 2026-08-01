"""The outbound boundary: how a digest leaves the machine.

This is the first path in AniOS that reaches a third party, and every subsystem
before it fails closed inside the machine. So the contract is deliberately
narrow — one bounded string to one consented address — and the default
configuration sends nothing at all.

Three properties are enforced here rather than trusted to callers:

- delivery requires recorded consent and an unrevoked permission;
- a channel receives the message text and nothing else. No memory, no profile,
  no conversation, and no ability to ask for any of it;
- a failure is a failure. A channel never reports success it did not have,
  because `delivered_at` is written once and a false success is unrecoverable.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

# A message longer than this is not a notification. Bounded here because the
# text has already crossed the boundary by the time a channel sees it.
MAX_MESSAGE_CHARS = 4_000


class DeliveryError(RuntimeError):
    """Raised when a channel could not deliver, with no side effect."""


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    delivered: bool
    error_code: str | None = None


class NotificationChannel(ABC):
    """Send one bounded message to one address."""

    @property
    @abstractmethod
    def channel_id(self) -> str:
        """Which subscriber channel this implementation serves."""

    @abstractmethod
    async def send(self, address: str, message: str) -> DeliveryResult:
        """Deliver, or return a failure. Never raise past this boundary."""


class NullChannel(NotificationChannel):
    """The default. Refuses to send, and says so.

    Egress ships disabled: an operator turns delivery on deliberately, rather
    than discovering it was on because a default said so.
    """

    def __init__(self, channel_id: str = "imessage") -> None:
        self._channel_id = channel_id

    @property
    def channel_id(self) -> str:
        return self._channel_id

    async def send(self, address: str, message: str) -> DeliveryResult:
        return DeliveryResult(delivered=False, error_code="egress_disabled")


class PullOnlyChannel(NotificationChannel):
    """A channel that never sends, because the recipient fetches instead.

    The recipient's own device asks for the digest on its own schedule, so
    AniOS makes no outbound connection. This is the only delivery shape that
    needs no egress permission at all, which is why it exists as a first-class
    channel rather than an absence of one.
    """

    @property
    def channel_id(self) -> str:
        return "shortcuts_pull"

    async def send(self, address: str, message: str) -> DeliveryResult:
        return DeliveryResult(delivered=False, error_code="pull_channel")


class MessagesAppChannel(NotificationChannel):
    """Deliver an iMessage through an Apple device the operator controls.

    Apple publishes no server-side API, so the only unpaid path is a Mac signed
    into Messages, driven locally. AniOS calls that machine through the existing
    MCP boundary rather than embedding any Apple-specific mechanism here: the
    Mac owns the sending, and this owns deciding whether to.

    The tool is called with an address and a message and nothing else, so a
    compromised or misbehaving bridge learns only what it must to deliver.
    """

    def __init__(self, invoke_tool: "ToolInvoker", tool_name: str) -> None:
        self.invoke_tool = invoke_tool
        self.tool_name = tool_name

    @property
    def channel_id(self) -> str:
        return "imessage"

    async def send(self, address: str, message: str) -> DeliveryResult:
        if len(message) > MAX_MESSAGE_CHARS:
            return DeliveryResult(delivered=False, error_code="message_too_long")
        try:
            await self.invoke_tool(self.tool_name, {"to": address, "body": message})
        except Exception:
            # The provider's own error text is not propagated: it can contain
            # the address, and a failure reason is not worth leaking one.
            return DeliveryResult(delivered=False, error_code="channel_unreachable")
        return DeliveryResult(delivered=True)


# What a channel needs from the MCP layer, so this module depends on the
# capability rather than the client.
class ToolInvoker:
    async def __call__(
        self, tool_name: str, arguments: dict[str, str]
    ) -> object:  # pragma: no cover - structural type
        raise NotImplementedError
