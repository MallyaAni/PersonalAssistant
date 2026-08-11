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
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# Where AniOS puts the shared secret. Configured on its side as a per-server
# header, so it never becomes a tool argument the outbound privacy gate would
# refuse to send.
BRIDGE_TOKEN_HEADER = "x-anios-bridge-token"

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
#
# Digits only. This kept `+` once, which quietly defeated the country-code rule
# below: `+17032613382` does not start with "1", so the leading digit was never
# dropped, and the same phone written `+1703...` and `703...` compared as two
# different people. AniOS strips to digits in backend/discovery/addressing.py,
# so keeping the plus here also broke the agreement the two are supposed to
# hold — an approved recipient refused at the last hop for writing her own
# number the other way.
_NON_DIGITS = re.compile(r"[^0-9]")


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
    # Where recipients granted by AniOS are recorded, and whether AniOS may
    # grant any. Both off unless the Mac's operator turns them on.
    grants_path: Path | None = None
    # Whether this bridge may read the Messages database, and where it is.
    #
    # Off unless the operator turns it on, and separate from sending on purpose:
    # sending needs automation permission, reading needs Full Disk Access, and
    # those are different grants protecting different things. With it off, every
    # send still works and reports no identifier, which costs feedback and
    # nothing else.
    #
    # What it is used for is deliberately narrow. Two queries, both keyed on
    # messages this bridge itself sent: the identifier of the message just sent,
    # and the tapbacks attached to identifiers AniOS supplies. No message bodies
    # are read, no conversation is enumerated, and nothing about anyone's other
    # correspondence is reachable through it.
    messages_db: Path | None = None

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
            grants_path=_grants_path(),
            messages_db=_messages_db(),
        )


# Where granted recipients live, or None when granting is switched off.
#
# Off by default, and that default is the point. Letting AniOS extend this list
# means whoever holds the bridge token can decide who this Mac messages as its
# owner — which is a different, larger permission than "message these people".
# Turning it on is the Mac operator's decision to delegate that, made once and
# explicitly, rather than something inherited from installing the bridge.
def _grants_path() -> Path | None:
    if os.environ.get("IMESSAGE_BRIDGE_ALLOW_GRANTS", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        return None
    configured = os.environ.get("IMESSAGE_BRIDGE_GRANTS", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".anios-imessage-bridge" / "granted-recipients.json"


# Recipients AniOS has been allowed to add, read fresh on every check.
#
# Read from disk each time rather than cached at startup, because the point of
# granting is that approving a subscription works *now*. A cached list would
# reintroduce exactly the failure this exists to remove: an approval that looks
# done and a bridge that still refuses until someone restarts it.
def load_grants(config: BridgeConfig) -> frozenset[str]:
    if config.grants_path is None or not config.grants_path.exists():
        return frozenset()
    try:
        stored = json.loads(config.grants_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A corrupt grant file must not take the bridge down, and must not
        # silently widen the allowlist either. It reads as no grants.
        return frozenset()
    if not isinstance(stored, list):
        return frozenset()
    return frozenset(
        normalize_recipient(str(item)) for item in stored if str(item).strip()
    )


# Record one granted recipient. Returns whether it was newly added.
def store_grant(config: BridgeConfig, recipient: str) -> bool:
    if config.grants_path is None:
        raise BridgeError(
            "This bridge does not accept grants. "
            "Set IMESSAGE_BRIDGE_ALLOW_GRANTS=true to let AniOS add recipients."
        )
    normalized = normalize_recipient(recipient)
    if not normalized:
        raise BridgeError("A recipient is required.")
    existing = load_grants(config)
    if normalized in existing or normalized in config.allowed_recipients:
        return False
    config.grants_path.parent.mkdir(parents=True, exist_ok=True)
    config.grants_path.write_text(
        json.dumps(sorted(existing | {normalized}), indent=2), encoding="utf-8"
    )
    return True


# Compare recipients by digits so "+1 (555) 010-0" and "+15550100" are one
# person. An Apple ID is compared case-insensitively instead.
def normalize_recipient(value: str) -> str:
    cleaned = value.strip()
    if "@" in cleaned:
        return cleaned.casefold()
    digits = _NON_DIGITS.sub("", cleaned)
    # `+12025550143` and `2025550143` are the same phone. Comparing raw digits
    # made them different, so an allowlist written with the country code refused
    # the address AniOS actually stored — a refusal at the last hop, for a
    # recipient who had done nothing wrong. The leading 1 is dropped only when
    # what remains is a full ten-digit number, so an international number that
    # legitimately begins with one is left intact. AniOS applies the same rule
    # in backend/discovery/addressing.py; the two must agree.
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


def check_recipient(config: BridgeConfig, recipient: str) -> str:
    normalized = normalize_recipient(recipient)
    if not normalized:
        raise BridgeError("A recipient is required.")
    # Two sources, one rule: what the Mac's operator wrote in the environment,
    # plus anyone AniOS was permitted to grant. The environment list is never
    # rewritten, so the operator's own choices survive a grant file being
    # deleted, and deleting it revokes every grant at once.
    if normalized not in config.allowed_recipients | load_grants(config):
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


# Where the Messages database is, or None when reading it is switched off.
#
# Off by default for the same reason granting is: it is a permission the Mac's
# operator gives deliberately, not one inherited from installing the bridge.
def _messages_db() -> Path | None:
    if os.environ.get("IMESSAGE_BRIDGE_READ_REACTIONS", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        return None
    raw = os.environ.get("IMESSAGE_BRIDGE_MESSAGES_DB", "").strip()
    path = Path(raw) if raw else Path.home() / "Library" / "Messages" / "chat.db"
    return path if path.exists() else None


# Read-only connection to the Messages database, or None when unavailable.
#
# Opened through an immutable URI so this cannot write, cannot create the file,
# and cannot take a lock that would interfere with Messages itself.
def _open_messages(config: BridgeConfig) -> sqlite3.Connection | None:
    connection, _ = _open_messages_reporting(config)
    return connection


# Open the database read-only, and say why if it will not open.
#
# `mode=ro` first, and this ordering is load-bearing rather than a preference:
# `immutable=1` tells SQLite the file cannot change, which makes it skip the
# write-ahead log entirely. Messages keeps recent messages there before
# checkpointing them, so the message this bridge sent a second ago — the whole
# reason for looking — is usually in the WAL and invisible under `immutable`.
#
# `immutable` stays as a fallback because a read-only WAL connection needs the
# `-shm` file to exist and be readable, which is true while Messages is running
# and not guaranteed when it is closed. Stale data beats no data there, since
# the fallback is only reached when the accurate mode cannot open at all.
def _open_messages_reporting(
    config: BridgeConfig,
) -> tuple[sqlite3.Connection | None, str]:
    if config.messages_db is None:
        return None, "reading is switched off"
    attempts = (
        ("mode=ro", f"file:{config.messages_db}?mode=ro"),
        ("immutable", f"file:{config.messages_db}?immutable=1"),
    )
    reasons = []
    for label, uri in attempts:
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=2.0)
            # Connecting is lazy, so a permission problem surfaces on the first
            # read rather than here. Ask something trivial to force it.
            connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
            return connection, label
        except sqlite3.Error as error:
            reasons.append(f"{label}: {error}")
    return None, "; ".join(reasons)


# The identifier of the message just sent to this recipient, if it can be read.
#
# Correlated by recipient and recency rather than returned by the send, because
# AppleScript's `send` hands back nothing. The window is deliberately tight and
# the text is compared, so a message the operator typed by hand a moment earlier
# cannot be mistaken for ours.
def latest_sent_guid(
    config: BridgeConfig, recipient: str, body: str
) -> str | None:
    connection = _open_messages(config)
    if connection is None:
        return None
    # Deliberately not joined to `handle`, and deliberately not matched on the
    # recipient string. The first version did both and found nothing on a real
    # Mac, for three separate reasons, any one of which is enough:
    #
    # - an outgoing message often carries `handle_id = 0`, so the join drops it;
    # - `handle.id` holds Apple's canonical form of an address, which is not
    #   necessarily the string AniOS was configured to send to;
    # - on recent macOS `message.text` is frequently NULL, because the body is
    #   stored in the `attributedBody` blob instead.
    #
    # So: the newest few outgoing messages, bounded to the seconds around this
    # send, matched on the body wherever the body can be read at all.
    since = _apple_time(datetime.now(timezone.utc) - timedelta(seconds=SEND_WINDOW))  # noqa: UP017
    try:
        rows = connection.execute(
            """
            SELECT guid, text, attributedBody
            FROM message
            WHERE is_from_me = 1
              AND date >= ?
            ORDER BY date DESC
            LIMIT 10
            """,
            (since,),
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        connection.close()

    wanted = body.strip()
    for guid, text, blob in rows:
        if (text or "").strip() == wanted:
            return str(guid)
        # The body as it survives inside the attributed blob. Compared on a
        # distinctive slice rather than the whole thing, because the blob wraps
        # the text in binary plist framing and may hard-wrap it.
        if blob and wanted[:60] and wanted[:60].encode("utf-8") in bytes(blob):
            return str(guid)
    # Nothing matched by content. The newest outgoing message inside the window
    # is almost certainly the one just sent, but "almost" would attach someone
    # else's reaction to a find, so this stops here and reports no identifier.
    return None


# How many seconds around a send count as "the message just sent".
SEND_WINDOW = 30

# Apple's epoch for the `date` column: nanoseconds since 2001-01-01 UTC.
_APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)  # noqa: UP017


# A datetime as the Messages database stores it.
def _apple_time(moment: datetime) -> int:
    return int((moment - _APPLE_EPOCH).total_seconds() * 1_000_000_000)


# Which of the given messages have been reacted to, and how.
#
# Only the identifiers AniOS supplies are looked at, and only the reaction type
# is returned. Tapbacks live in the same table as messages, distinguished by
# `associated_message_type`: 2001 is a thumbs up and 2002 a thumbs down, while
# 3001 and 3002 are those same reactions being removed again.
def read_tapbacks(
    config: BridgeConfig, guids: list[str]
) -> list[dict[str, object]]:
    if not guids:
        return []
    connection = _open_messages(config)
    if connection is None:
        return []
    # The association is stored as a prefixed copy of the target's identifier
    # ("p:0/<guid>"), so matching is on the suffix rather than on equality.
    wanted = {guid.split(";")[-1]: guid for guid in guids if guid}
    if not wanted:
        return []
    # Constrained in SQL rather than filtered afterwards. Selecting every
    # reaction in the database and discarding most of them in Python reaches
    # every conversation on this Mac to answer a question about a handful of
    # messages; a LIKE per requested identifier reaches only those.
    #
    # `is_from_me` is deliberately *not* filtered. A digest sent from this Mac to
    # the owner's own number is a thread with themselves, so their tapback comes
    # back marked as from them — filtering those out dropped exactly the
    # reactions this feature exists to collect.
    clauses = " OR ".join("associated_message_guid LIKE ?" for _ in wanted)
    parameters = [f"%{suffix}" for suffix in wanted]
    try:
        rows = connection.execute(
            f"""
            SELECT associated_message_guid, associated_message_type, date
            FROM message
            WHERE associated_message_type IN (2001, 2002, 3001, 3002)
              AND ({clauses})
            ORDER BY date ASC
            """,
            parameters,
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()

    # Latest wins: someone who thumbs-ups and then removes it has no opinion,
    # and someone who switches from down to up has changed their mind.
    latest: dict[str, dict[str, object]] = {}
    for associated, kind, when in rows:
        suffix = str(associated or "").split("/")[-1]
        guid = wanted.get(suffix)
        if guid is None:
            continue
        if kind in (3001, 3002):
            latest.pop(guid, None)
            continue
        latest[guid] = {
            "message_guid": guid,
            "reaction": "liked" if kind == 2001 else "disliked",
            "at": _apple_epoch(when),
        }
    return list(latest.values())


# Apple stores message times as nanoseconds since 2001-01-01 UTC.
def _apple_epoch(value: object) -> str | None:
    try:
        seconds = int(value) / 1_000_000_000
    except (TypeError, ValueError):
        return None
    # `timezone.utc` rather than `datetime.UTC`: the alias needs 3.11 and this
    # file runs on whatever Python the Mac's operator built the venv with, which
    # the setup only requires to be 3.10 or newer.
    return (
        datetime(2001, 1, 1, tzinfo=timezone.utc)  # noqa: UP017
        + timedelta(seconds=seconds)
    ).isoformat()


# Whether reading is configured and working, described without disclosing any of
# it. Counts and shapes answer every setup question that matters; the contents
# would answer none of them and are nobody's business but the Mac owner's.
def diagnose(config: BridgeConfig) -> dict[str, object]:
    if config.messages_db is None:
        return {
            "readable": False,
            "why": "IMESSAGE_BRIDGE_READ_REACTIONS is off, or the database path "
            "does not exist.",
        }
    connection, how = _open_messages_reporting(config)
    if connection is None:
        return {
            "readable": False,
            # SQLite's own words. "unable to open database file" is Full Disk
            # Access not granted to whatever runs this bridge — and the grant is
            # per executable, so granting it to Terminal does nothing for a
            # LaunchAgent running a different Python.
            "why": how,
            "path": str(config.messages_db),
        }
    since = _apple_time(datetime.now(timezone.utc) - timedelta(days=1))  # noqa: UP017
    try:
        sent, without_text = connection.execute(
            """
            SELECT COUNT(*), SUM(CASE WHEN text IS NULL OR text = '' THEN 1 ELSE 0 END)
            FROM message WHERE is_from_me = 1 AND date >= ?
            """,
            (since,),
        ).fetchone()
        tapbacks = connection.execute(
            """
            SELECT COUNT(*) FROM message
            WHERE associated_message_type IN (2001, 2002, 3001, 3002) AND date >= ?
            """,
            (since,),
        ).fetchone()[0]
        # Every association type seen recently, not just the four we map.
        #
        # A thumbs-up was left on a digest and read_reactions returned nothing,
        # and there was no way to tell whether the reaction had not synced from
        # the phone yet or had arrived under a type this does not recognise —
        # recent iOS lets any emoji be a reaction, and those are not 2001. The
        # type is a small integer and says nothing about any conversation.
        kinds = connection.execute(
            """
            SELECT associated_message_type, COUNT(*)
            FROM message
            WHERE associated_message_type IS NOT NULL
              AND associated_message_type != 0
              AND date >= ?
            GROUP BY associated_message_type ORDER BY 2 DESC
            """,
            (since,),
        ).fetchall()
    except sqlite3.Error as error:
        return {"readable": False, "why": f"Query failed: {type(error).__name__}"}
    finally:
        connection.close()
    return {
        "readable": True,
        # Which mode opened it. "immutable" means the write-ahead log is not
        # being read, so a message sent moments ago may not be visible yet.
        "opened_with": how,
        "sent_last_day": int(sent or 0),
        # The reason a body match can fail on a modern Mac: the text lives in
        # `attributedBody` instead, which the lookup now also reads.
        "sent_without_plain_text": int(without_text or 0),
        "tapbacks_last_day": int(tapbacks or 0),
        # {type: count} for every association seen in the last day. 2001 is a
        # thumbs up and 2002 a thumbs down; anything else here is a reaction
        # this bridge currently ignores, which is worth seeing rather than
        # inferring from an empty result.
        "association_types": {str(kind): int(count) for kind, count in kinds},
    }


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
        # The identifier a tapback will point at, when this Mac allows it to be
        # read. "sent" otherwise, which is what every caller understood before
        # feedback existed and still handles.
        return latest_sent_guid(config, recipient, text) or "sent"

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
        to: str,
        body: str,
        attachment_name: str | None = None,
        attachment_media_type: str | None = None,
        attachment_base64: str | None = None,
    ) -> str:
        """Send one iMessage, optionally with a calendar file attached."""
        # The token is checked at the transport, not here. It used to be a tool
        # argument, which cannot work against AniOS: every string argument is
        # screened by the outbound privacy gate before it leaves, and a
        # high-entropy secret is precisely what that gate refuses to send. A
        # header is also simply the right place for a credential.
        return send_message(
            config,
            to,
            body,
            attachment_name,
            attachment_media_type,
            attachment_base64,
        )

    @server.tool()
    def allow_recipient(to: str) -> str:
        """Permit one recipient, so an approved subscription can be messaged."""
        # Approving a subscription in AniOS and hand-editing a list on the Mac
        # are two records of the same decision, and they drifted: a recipient
        # was approved, the digest was built on time, and the bridge refused it
        # at the last hop. One approval should reach both.
        added = store_grant(config, to)
        return "Recipient allowed." if added else "Recipient was already allowed."

    @server.tool()
    def describe_messages_access() -> str:
        """Report whether reactions can be read, and in what shape, for setup."""
        # Written because the first real run recorded three messages and no
        # identifiers, and there were three equally plausible reasons. Counts
        # and shapes only — no message text, no addresses, nothing about any
        # conversation — so this answers "is it wired up" without becoming a way
        # to read the Mac.
        return json.dumps(diagnose(config))

    @server.tool()
    def read_reactions(message_guids: list[str]) -> str:
        """Report thumbs-up and thumbs-down tapbacks on messages this sent."""
        # Answers only about identifiers the caller already has, which are the
        # ones this bridge handed back when it sent them. It cannot be asked
        # "what has been said to you lately", no message text is read, and a Mac
        # that has not been given Full Disk Access returns an empty list rather
        # than an error — the digest still went, and only the feedback is lost.
        return json.dumps({"reactions": read_tapbacks(config, message_guids)})

    return server


# Wrap the MCP app so an unauthenticated request is refused before it reaches
# any tool. Anything on the network can open an HTTP port; without this the
# bridge is an open "send an iMessage as me" endpoint.
def build_app(config: BridgeConfig) -> Any:
    import hmac

    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    app = create_bridge(config).streamable_http_app()

    # Compared in constant time so the token cannot be recovered by timing.
    async def authenticate(request: Any, call_next: Any) -> Any:
        supplied = request.headers.get(BRIDGE_TOKEN_HEADER, "")
        if not hmac.compare_digest(supplied, config.token):
            # No detail: a caller that guessed wrong learns only that it did.
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    app.add_middleware(BaseHTTPMiddleware, dispatch=authenticate)
    return app


def main() -> None:
    if sys.platform != "darwin":
        # Refuse loudly rather than failing later with a confusing osascript
        # error. This only ever works on a Mac.
        raise SystemExit("The iMessage bridge only runs on macOS.")
    if sys.version_info < (3, 10):
        # macOS still ships 3.9 as `python3`, and mcp requires 3.10. Building the
        # venv with the system interpreter therefore fails at `pip install` with
        # "no matching distribution found for mcp", which names the package
        # rather than the actual cause.
        raise SystemExit(
            "This bridge needs Python 3.10 or newer; "
            f"this is {sys.version_info.major}.{sys.version_info.minor}. "
            "macOS ships 3.9 as python3 — install a newer one and rebuild the "
            "virtual environment with it."
        )
    import uvicorn

    config = BridgeConfig.from_environment()
    uvicorn.run(build_app(config), host=config.host, port=config.port)


if __name__ == "__main__":
    main()


__all__: list[Any] = [
    "BRIDGE_TOKEN_HEADER",
    "BridgeConfig",
    "build_app",
    "BridgeError",
    "check_recipient",
    "create_bridge",
    "decode_attachment",
    "load_grants",
    "normalize_recipient",
    "send_message",
    "store_grant",
]
