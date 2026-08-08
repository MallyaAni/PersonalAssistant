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

import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol

# A message longer than this is not a notification. Bounded here because the
# text has already crossed the boundary by the time a channel sees it.
MAX_MESSAGE_CHARS = 4_000

# A calendar file for a handful of events is a few kilobytes. The bound exists
# so a malformed one cannot be mailed to someone.
MAX_ATTACHMENT_BYTES = 256 * 1024


class DeliveryError(RuntimeError):
    """Raised when a channel could not deliver, with no side effect."""


class ChannelRefusedError(DeliveryError):
    """The far side answered and declined, with a reason worth recording.

    Distinct from a transport failure because it is *deterministic*: the same
    send will be refused again, so retrying is pointless rather than merely
    unsafe. The code names something an operator can fix.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Attachment:
    """A file travelling with the message.

    This is what makes a digest work away from home. A link has to reach the
    machine that served it; a file that arrives with the message does not, so a
    recipient on mobile data can add an event without AniOS being reachable at
    all — and without anything of it being exposed.
    """

    filename: str
    media_type: str
    content: bytes

    @property
    def too_large(self) -> bool:
        return len(self.content) > MAX_ATTACHMENT_BYTES

    # Transport-safe encoding, since the tool boundary carries JSON.
    def encoded(self) -> str:
        return base64.b64encode(self.content).decode("ascii")


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    delivered: bool
    error_code: str | None = None
    # Whether the message provably never left this machine.
    #
    # This is the only fact that makes a second attempt safe, and it is much
    # narrower than "the send failed". A dropped connection mid-request does not
    # say whether the bridge sent the message before the reply was lost, so
    # resending on that would be how someone gets the same digest twice. A
    # connection that was never *established* carries no such doubt: nothing
    # reached the bridge, so nothing was sent.
    #
    # Defaults to False. A channel that has not thought about the question gets
    # the safe answer, since a wrong True duplicates a message and a wrong False
    # only loses one.
    unsent: bool = False


class NotificationChannel(ABC):
    """Send one bounded message to one address."""

    @property
    @abstractmethod
    def channel_id(self) -> str:
        """Which subscriber channel this implementation serves."""

    @abstractmethod
    async def send(
        self,
        address: str,
        message: str,
        attachment: Attachment | None = None,
    ) -> DeliveryResult:
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

    async def send(
        self,
        address: str,
        message: str,
        attachment: Attachment | None = None,
    ) -> DeliveryResult:
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

    async def send(
        self,
        address: str,
        message: str,
        attachment: Attachment | None = None,
    ) -> DeliveryResult:
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

    async def send(
        self,
        address: str,
        message: str,
        attachment: Attachment | None = None,
    ) -> DeliveryResult:
        if len(message) > MAX_MESSAGE_CHARS:
            return DeliveryResult(delivered=False, error_code="message_too_long")
        if attachment is not None and attachment.too_large:
            return DeliveryResult(delivered=False, error_code="attachment_too_large")

        arguments = {"to": address, "body": message}
        if attachment is not None:
            # Base64 because the tool boundary carries JSON. The bridge writes it
            # to a file and attaches it; the filename is what the recipient sees.
            arguments["attachment_name"] = attachment.filename
            arguments["attachment_media_type"] = attachment.media_type
            arguments["attachment_base64"] = attachment.encoded()
        try:
            await self.invoke_tool(self.tool_name, arguments)
        except ChannelRefusedError as refused:
            # The bridge answered, so nothing is in doubt about whether it sent:
            # it did not. Not marked replayable all the same, because the same
            # refusal would follow every retry until a person changes something.
            return DeliveryResult(delivered=False, error_code=refused.code)
        except Exception as exc:
            # The provider's own error text is not propagated: it can contain
            # the address, and a failure reason is not worth leaking one. Only
            # the shape of the failure is kept, because that is what decides
            # whether trying again could duplicate a message.
            if _never_connected(exc):
                return DeliveryResult(
                    delivered=False, error_code="channel_unreachable", unsent=True
                )
            return DeliveryResult(delivered=False, error_code="channel_failed")
        return DeliveryResult(delivered=True)


# Connection-establishment failures, which prove the request never arrived.
#
# Deliberately not the full set of transport errors. A read timeout or a broken
# pipe happens *after* the request is on the wire, and the bridge may well have
# sent the message before the reply was lost — so those are excluded, and the
# digest is dropped rather than risked twice.
_NEVER_CONNECTED: tuple[type[BaseException], ...] = (
    ConnectionRefusedError,
    # A stdio bridge that is not installed cannot have sent anything either.
    FileNotFoundError,
)

# httpx is how a remote bridge is reached, and its connect errors are not
# OSError subclasses, so they have to be named. This was worth checking rather
# than assuming: they are also wrapped in an ExceptionGroup by the MCP client,
# which is why the unwrapping below exists.
try:  # pragma: no cover - exercised whenever a remote bridge is configured
    import httpx

    _NEVER_CONNECTED = (*_NEVER_CONNECTED, httpx.ConnectError, httpx.ConnectTimeout)
except ImportError:  # pragma: no cover
    pass


# Whether a failure proves the send never reached the bridge.
def _never_connected(exc: BaseException, depth: int = 0) -> bool:
    # An ExceptionGroup is what the MCP client raises, so the real cause is a
    # level or two down. Bounded so a self-referential group cannot spin.
    if depth > 4:
        return False
    nested = getattr(exc, "exceptions", None)
    if nested:
        # Every branch must be a connect failure. One ambiguous member means the
        # whole group is ambiguous.
        return all(_never_connected(item, depth + 1) for item in nested)
    return isinstance(exc, _NEVER_CONNECTED)


# What a channel needs from the MCP layer, so this module depends on the
# capability rather than the client. Structural, so any coroutine of the right
# shape satisfies it without importing anything from here.
class ToolInvoker(Protocol):
    async def __call__(self, tool_name: str, arguments: dict[str, str]) -> object: ...
