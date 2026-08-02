"""An MCP server that sends iMessages, run on a Mac.

Apple publishes no server-side API, so the only unpaid way to send an iMessage is
a Mac signed into Messages, driven locally. This is that machine's side of the
boundary: AniOS decides *whether* to send and what to say; this decides nothing
and only sends.

It runs on the Mac, not with AniOS. Streamable HTTP rather than stdio precisely
because the two are different machines — AniOS may be on Windows today and a DGX
tomorrow, and neither can spawn a process on the Mac.

Three properties this holds on its own, rather than trusting its caller:

- **a recipient allowlist.** The bridge sends only to numbers the Mac's operator
  listed. This is the last hop before a message reaches a real person, and it is
  the only place that can refuse independently of whatever asked it to send;
- **a shared secret.** Anything on the LAN can reach an HTTP port. Without a
  token this would be an open "send an iMessage as me" endpoint;
- **no AppleScript interpolation.** Arguments are passed to `osascript` as argv
  and read via `on run argv`, so a message body containing quotes or backslashes
  is data, never script. Building the script by string formatting is how this
  kind of bridge becomes a remote code execution hole.

Setup lives in README.md next to this file.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# Bounds mirroring the caller's, enforced again here because a bridge that
# trusts its caller's limits has no limits.
MAX_BODY_CHARS = 4_000
MAX_ATTACHMENT_BYTES = 256 * 1024
SEND_TIMEOUT_SECONDS = 30.0

# Only calendar files are attachable. A general file-sending endpoint on a
# machine signed into someone's Apple ID is a much larger thing than this needs
# to be.
ALLOWED_MEDIA_TYPES = frozenset({"text/calendar"})
ALLOWED_SUFFIXES = frozenset({".ics"})

# Phone numbers and Apple IDs, normalized for comparison against the allowlist.
_NON_DIGITS = re.compile(r"[^\d+]")


class BridgeError(RuntimeError):
    """Raised when a send is refused. The reason is safe to return."""


# Arguments reach AppleScript as argv, never as source. `on run argv` is what
# makes a body containing a quote a string rather than a statement.
_SEND_TEXT = """
on run argv
    set targetId to item 1 of argv
    set messageBody to item 2 of argv
    tell application "Messages"
        set targetService to 1st account whose service type = iMessage
        set targetBuddy to participant targetId of targetService
        send messageBody to targetBuddy
    end tell
end run
"""

_SEND_WITH_ATTACHMENT = """
on run argv
    set targetId to item 1 of argv
    set messageBody to item 2 of argv
    set filePath to item 3 of argv
    tell application "Messages"
        set targetService to 1st account whose service type = iMessage
        set targetBuddy to participant targetId of targetService
        send messageBody to targetBuddy
        send (POSIX file filePath) to targetBuddy
    end tell
end run
"""


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    """What the Mac's operator decided this bridge may do."""

    token: str
    allowed_recipients: frozenset[str]
    host: str
    port: int

    @classmethod
    def from_environment(cls) -> BridgeConfig:
        token = os.environ.get("IMESSAGE_BRIDGE_TOKEN", "").strip()
        if not token:
            # No default. An unauthenticated send-as-me endpoint must not be
            # something you get by forgetting to configure one.
            raise BridgeError("Set IMESSAGE_BRIDGE_TOKEN. This endpoint sends as you.")
        raw = os.environ.get("IMESSAGE_BRIDGE_RECIPIENTS", "")
        allowed = frozenset(
            normalize_recipient(part) for part in raw.split(",") if part.strip()
        )
        if not allowed:
            raise BridgeError(
                "Set IMESSAGE_BRIDGE_RECIPIENTS to the numbers this may message."
            )
        return cls(
            token=token,
            allowed_recipients=allowed,
            # Loopback by default: reaching this from another machine is a
            # deliberate act, not the out-of-the-box state.
            host=os.environ.get("IMESSAGE_BRIDGE_HOST", "127.0.0.1"),
            port=int(os.environ.get("IMESSAGE_BRIDGE_PORT", "8010")),
        )


# Compare recipients by digits so "+1 (555) 010-0" and "+15550100" are one
# person. An Apple ID is compared case-insensitively instead.
def normalize_recipient(value: str) -> str:
    cleaned = value.strip()
    if "@" in cleaned:
        return cleaned.casefold()
    return _NON_DIGITS.sub("", cleaned)


def check_recipient(config: BridgeConfig, recipient: str) -> str:
    normalized = normalize_recipient(recipient)
    if not normalized:
        raise BridgeError("A recipient is required.")
    if normalized not in config.allowed_recipients:
        # Deliberately does not echo the recipient: the refusal reason should
        # not become a way to probe who is on the list.
        raise BridgeError("That recipient is not on this bridge's allowlist.")
    return recipient.strip()


# Decode and validate an attachment before anything touches the filesystem.
def decode_attachment(
    name: str | None, media_type: str | None, encoded: str | None
) -> tuple[str, bytes] | None:
    if not encoded:
        return None
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise BridgeError(f"Unsupported attachment type: {media_type}")

    safe_name = Path(name or "attachment.ics").name
    if Path(safe_name).suffix.lower() not in ALLOWED_SUFFIXES:
        raise BridgeError("Only .ics attachments are supported.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BridgeError("Attachment was not valid base64.") from exc
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise BridgeError("Attachment is too large.")
    if not content.lstrip().startswith(b"BEGIN:VCALENDAR"):
        # Cheap proof the bytes are what the media type claims, so this cannot
        # be used to drop an arbitrary file onto the Mac.
        raise BridgeError("Attachment is not an iCalendar document.")
    return safe_name, content


def run_osascript(script: str, arguments: list[str]) -> None:
    result = subprocess.run(
        ["osascript", "-e", script, "--", *arguments],
        capture_output=True,
        text=True,
        timeout=SEND_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        # Only the first line, and never the arguments: stderr echoes them.
        raise BridgeError(detail[0] if detail else "Messages refused the send.")


def send_message(
    config: BridgeConfig,
    to: str,
    body: str,
    attachment_name: str | None = None,
    attachment_media_type: str | None = None,
    attachment_base64: str | None = None,
) -> str:
    recipient = check_recipient(config, to)
    text = body.strip()
    if not text:
        raise BridgeError("A message body is required.")
    if len(text) > MAX_BODY_CHARS:
        raise BridgeError("Message body is too long.")

    attachment = decode_attachment(
        attachment_name, attachment_media_type, attachment_base64
    )
    if attachment is None:
        run_osascript(_SEND_TEXT, [recipient, text])
        return "sent"

    safe_name, content = attachment
    # Written inside a directory that is removed however this returns, so a
    # failed send does not leave someone's calendar on disk.
    with tempfile.TemporaryDirectory(prefix="anios-imessage-") as directory:
        path = Path(directory) / safe_name
        path.write_bytes(content)
        run_osascript(_SEND_WITH_ATTACHMENT, [recipient, text, str(path)])
    return "sent with attachment"


def create_bridge(config: BridgeConfig) -> FastMCP:
    server = FastMCP(
        "AniOS iMessage Bridge",
        host=config.host,
        port=config.port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )

    @server.tool()
    def send_imessage(
        token: str,
        to: str,
        body: str,
        attachment_name: str | None = None,
        attachment_media_type: str | None = None,
        attachment_base64: str | None = None,
    ) -> str:
        """Send one iMessage, optionally with a calendar file attached."""
        # Compared in constant time so the token cannot be recovered by timing
        # repeated calls.
        import hmac

        if not hmac.compare_digest(token, config.token):
            raise BridgeError("Invalid bridge token.")
        return send_message(
            config,
            to,
            body,
            attachment_name,
            attachment_media_type,
            attachment_base64,
        )

    return server


def main() -> None:
    if sys.platform != "darwin":
        # Refuse loudly rather than failing later with a confusing osascript
        # error. This only ever works on a Mac.
        raise SystemExit("The iMessage bridge only runs on macOS.")
    config = BridgeConfig.from_environment()
    create_bridge(config).run(transport="streamable-http")


if __name__ == "__main__":
    main()


__all__: list[Any] = [
    "BridgeConfig",
    "BridgeError",
    "check_recipient",
    "create_bridge",
    "decode_attachment",
    "normalize_recipient",
    "send_message",
]
