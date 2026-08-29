"""An MCP server that sends and receives iMessages, run on a Mac.

Apple publishes no server-side API, so the only unpaid way to send an iMessage is
a Mac signed into Messages, driven locally. This is that machine's side of the
boundary: AniOS decides *whether* to send and what to say; this decides nothing
and only carries. Receiving works the same way: AniOS decides what a message
means and whether to answer; this only reports what allowlisted senders said.

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

Reading is split into two separately granted permissions, both off by default.
`IMESSAGE_BRIDGE_READ_REACTIONS` reads only tapbacks on messages AniOS itself
composed — no bodies ever leave those queries. `IMESSAGE_BRIDGE_READ_INCOMING`
is the larger grant: it returns the bodies of one-to-one messages from senders
on the allowlist, so those people can converse with AniOS. Messages from anyone
not on the allowlist are filtered here, inside this process, and never leave
it. Group chats are read only when the Mac's operator lists them in
IMESSAGE_BRIDGE_GROUPS with reading on; every allowlisted member's message
in a listed room is forwarded, marked with how it addressed this account
(a reply in a thread on one of its bubbles, a mention, its name) or not at
all, so the backend reads the room for context and answers only what was
for it. Bodies are never logged.

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

# Pictures may be larger than calendars, and nothing may be larger than this.
MAX_IMAGE_ATTACHMENT_BYTES = 5 * 1024 * 1024

# What may be attached to an outbound message: for each media type, the file
# suffixes it may be named with, its size cap, and the leading bytes that prove
# the content is what the type claims. Calendars and pictures, nothing else — a
# general file-sending endpoint on a machine signed into someone's Apple ID is
# a much larger thing than this needs to be.
OUTBOUND_ATTACHMENT_RULES: dict[str, tuple[frozenset[str], int, tuple[bytes, ...]]] = {
    "text/calendar": (
        frozenset({".ics"}),
        MAX_ATTACHMENT_BYTES,
        (b"BEGIN:VCALENDAR",),
    ),
    "image/jpeg": (
        frozenset({".jpg", ".jpeg"}),
        MAX_IMAGE_ATTACHMENT_BYTES,
        (b"\xff\xd8\xff",),
    ),
    "image/png": (
        frozenset({".png"}),
        MAX_IMAGE_ATTACHMENT_BYTES,
        (b"\x89PNG\r\n\x1a\n",),
    ),
}

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
#
# The first argument is the sending account's id, or "" to take the first
# enabled iMessage account. "First" is which identity this Mac speaks as, and
# with two Apple IDs signed in it is decided by enablement order — so a Mac
# holding both a personal and a dedicated identity pins the dedicated one by
# id (IMESSAGE_BRIDGE_ACCOUNT_ID) rather than trusting the tie to break right.
_SEND_TEXT = """
on run argv
    set accountId to item 1 of argv
    set targetId to item 2 of argv
    set messageBody to item 3 of argv
    tell application "Messages"
        if accountId is "" then
            set targetService to 1st account whose service type = iMessage
        else
            set targetService to account id accountId
        end if
        set targetBuddy to participant targetId of targetService
        send messageBody to targetBuddy
    end tell
end run
"""

# The same two sends addressed to a group chat by its guid. `participant`
# can only ever name one person; a room is addressed by `chat id`, which
# Messages lists as `iMessage;+;chatNNN` (verified on macOS 13, 2026-08-28).
_SEND_TEXT_TO_CHAT = """
on run argv
    set accountId to item 1 of argv
    set targetId to item 2 of argv
    set messageBody to item 3 of argv
    tell application "Messages"
        set targetChat to chat id targetId
        send messageBody to targetChat
    end tell
end run
"""

_SEND_WITH_ATTACHMENT_TO_CHAT = """
on run argv
    set accountId to item 1 of argv
    set targetId to item 2 of argv
    set messageBody to item 3 of argv
    set filePath to item 4 of argv
    tell application "Messages"
        set attachmentFile to (POSIX file filePath) as alias
        set targetChat to chat id targetId
        send attachmentFile to targetChat
        if messageBody is not "" then
            send messageBody to targetChat
        end if
    end tell
end run
"""

_SEND_WITH_ATTACHMENT = """
on run argv
    set accountId to item 1 of argv
    set targetId to item 2 of argv
    set messageBody to item 3 of argv
    set filePath to item 4 of argv
    tell application "Messages"
        if accountId is "" then
            set targetService to 1st account whose service type = iMessage
        else
            set targetService to account id accountId
        end if
        set attachmentFile to (POSIX file filePath) as alias
        set targetBuddy to participant targetId of targetService
        send attachmentFile to targetBuddy
        if messageBody is not "" then
            send messageBody to targetBuddy
        end if
    end tell
end run
"""
# `as alias`, not a bare `POSIX file`, and that coercion is the whole fix.
# A path arriving as an `on run argv` string and sent as `POSIX file filePath`
# leaves the transfer queued in Messages' ledger as "waiting" forever — the
# recipient gets a bubble whose picture never loads while the send reports
# success — but the identical script with the path coerced to an `alias`
# uploads. Isolated by experiment: the same argv script stalled and then
# finished with this one change, self-targeted so no one was paged. Every
# image the bridge ever "sent" before this was a dead bubble. (Message order
# is irrelevant — a text-first direct-form send uploads fine; an earlier
# commit that reordered the sends was chasing the wrong variable.)


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
    # leave those queries, no conversation is enumerated, and nothing about
    # anyone's other correspondence is reachable through them.
    messages_db: Path | None = None
    # Which Messages account sends, by AppleScript account id, or "" for the
    # first enabled iMessage account. Set this whenever more than one Apple ID
    # is signed in: which identity a message comes *from* is an operator
    # decision, not a tie-break.
    account_id: str = ""
    # Whether this bridge may report incoming messages, and from where.
    #
    # A separate grant from reactions on purpose: reactions return no bodies,
    # this returns the bodies of allowlisted senders' one-to-one messages so
    # they can converse with AniOS. Same database, different permission, each
    # turned on by its own deliberate decision. Senders not on the allowlist
    # are filtered inside this process and never leave it.
    incoming_db: Path | None = None
    # Whether attachment bytes may leave this Mac, and the only directory they
    # may be read from. Its own grant on top of incoming, because a message
    # body and a photograph are different sizes of disclosure — and the root
    # containment means a database row cannot point this bridge at any file
    # outside the Messages store.
    attachments_enabled: bool = False
    attachments_root: Path = Path.home() / "Library" / "Messages" / "Attachments"
    # Group chats this bridge may read from and send to, by chat identifier
    # (`chatNNN`), and whether group reading is on at all. Its own grant on top
    # of incoming, env-only - grants never widen it - because a room is not a
    # person who was allowlisted. Even inside an allowlisted room only what is
    # addressed to this Mac's account leaves it (see `_addressed_to_bot`).
    groups: frozenset[str] = frozenset()
    read_groups: bool = False
    # This account's own addresses (the Apple ID email, the number), as
    # people mention it: a mention stores the mentioned handle, not the
    # rendered name (`__kIMMentionConfirmedMention` → deep-matter@…, read
    # from chat.db 2026-08-28), so this is what a mention is matched on and
    # it holds whatever contact name each person saved. Normalized.
    addresses: frozenset[str] = frozenset()
    # The name to answer to as a plain word ("scout, thai or pizza?"). Only
    # as reliable as everyone saving the contact under that name; optional.
    display_name: str = ""

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
        groups = frozenset(
            identifier
            for identifier in (
                normalize_chat_target(part) for part in os.environ.get("IMESSAGE_BRIDGE_GROUPS", "").split(",")
            )
            if identifier
        )
        read_groups = os.environ.get("IMESSAGE_BRIDGE_READ_GROUPS", "").strip().lower() in {"1", "true", "yes"}
        display_name = os.environ.get("IMESSAGE_BRIDGE_DISPLAY_NAME", "").strip()
        addresses = frozenset(
            normalize_recipient(part)
            for part in os.environ.get("IMESSAGE_BRIDGE_ADDRESSES", "").split(",")
            if part.strip()
        )
        if read_groups and not addresses and not display_name:
            raise BridgeError(
                "Set IMESSAGE_BRIDGE_ADDRESSES (this account's email and number, for mentions) "
                "and/or IMESSAGE_BRIDGE_DISPLAY_NAME (a name to answer to) to read group chats."
            )
        return cls(
            token=token,
            allowed_recipients=allowed,
            groups=groups,
            read_groups=read_groups,
            addresses=addresses,
            display_name=display_name,
            # Loopback by default: reaching this from another machine is a
            # deliberate act, not the out-of-the-box state.
            host=os.environ.get("IMESSAGE_BRIDGE_HOST", "127.0.0.1"),
            port=int(os.environ.get("IMESSAGE_BRIDGE_PORT", "8010")),
            grants_path=_grants_path(),
            messages_db=_messages_db(),
            incoming_db=_incoming_db(),
            account_id=os.environ.get("IMESSAGE_BRIDGE_ACCOUNT_ID", "").strip(),
            attachments_enabled=os.environ.get(
                "IMESSAGE_BRIDGE_READ_ATTACHMENTS", ""
            ).strip().lower()
            in {"1", "true", "yes"},
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
    # A room is granted by the Mac's operator in the environment, never by a
    # caller: a chat-shaped value is refused here rather than stored as an
    # address that can never match one.
    if normalize_chat_target(recipient) is not None:
        raise BridgeError("Group chats are allowlisted on the Mac, not granted by callers.")
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


# A group chat target as this bridge names it - `chatNNN`, also accepted as
# the full `iMessage;+;chatNNN` guid Messages lists - or None for anything
# else. Shape only.
def normalize_chat_target(value: str) -> str | None:
    cleaned = (value or "").strip()
    if ";+;" in cleaned:
        cleaned = cleaned.split(";+;", 1)[1]
    if cleaned.startswith("chat") and cleaned[4:].isdigit() and len(cleaned) >= 10:
        return cleaned
    return None


# The guid Messages addresses a group by.
def chat_guid_for(identifier: str) -> str:
    return f"iMessage;+;{identifier}"


def check_recipient(config: BridgeConfig, recipient: str) -> str:
    # A group chat: allowed only when its identifier is in the env-only group
    # list. Never widened by grants, and never echoed back.
    chat = normalize_chat_target(recipient)
    if chat is not None:
        if chat not in config.groups:
            raise BridgeError("That recipient is not on this bridge's allowlist.")
        return chat_guid_for(chat)
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
    rule = OUTBOUND_ATTACHMENT_RULES.get(media_type or "")
    if rule is None:
        raise BridgeError(f"Unsupported attachment type: {media_type}")
    suffixes, cap, magics = rule

    default_suffix = sorted(suffixes)[0]
    safe_name = Path(name or f"attachment{default_suffix}").name
    if Path(safe_name).suffix.lower() not in suffixes:
        if media_type == "text/calendar":
            raise BridgeError("Only .ics attachments are supported.")
        raise BridgeError(
            f"A {media_type} attachment must be named "
            f"{', '.join(sorted(suffixes))}."
        )
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BridgeError("Attachment was not valid base64.") from exc
    if len(content) > cap:
        raise BridgeError("Attachment is too large.")
    # Cheap proof the bytes are what the media type claims, so this cannot
    # be used to drop an arbitrary file onto the Mac. A calendar may open
    # with whitespace; an image signature is byte zero or it is nothing.
    body = content.lstrip() if media_type == "text/calendar" else content
    if not any(body.startswith(magic) for magic in magics):
        if media_type == "text/calendar":
            raise BridgeError("Attachment is not an iCalendar document.")
        raise BridgeError(f"Attachment bytes are not {media_type}.")
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


# Where incoming messages are read from, or None when that is switched off.
#
# Gated separately from reactions because it is a larger permission: reactions
# disclose a thumb on a message AniOS wrote, this discloses what an allowlisted
# person said. The operator turns each on by its own deliberate decision.
def _incoming_db() -> Path | None:
    if os.environ.get("IMESSAGE_BRIDGE_READ_INCOMING", "").strip().lower() not in {
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
    return _open_db_reporting(config.messages_db)


# Open one database path read-only with the WAL-aware two-mode logic above,
# so the reactions grant and the incoming grant share the mechanics without
# sharing the permission that points at them.
def _open_db_reporting(
    path: Path | None,
) -> tuple[sqlite3.Connection | None, str]:
    if path is None:
        return None, "reading is switched off"
    attempts = (
        ("mode=ro", f"file:{path}?mode=ro"),
        ("immutable", f"file:{path}?immutable=1"),
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
    config: BridgeConfig, recipient: str, body: str, chat_identifier: str | None = None
) -> str | None:
    # An empty body cannot be matched: it equals every NULL-text outgoing row,
    # of which recent macOS has many, so it would return whichever came first.
    # An attachment-only send reads its guid through latest_sent_attachment_guid
    # instead.
    if not body.strip():
        return None
    # Either read grant makes the database available, and reading back the
    # guid of a message this bridge itself just sent is the same disclosure
    # under both — so the readback works whenever incoming reading is on, not
    # only under the reactions grant.
    connection, _ = _open_db_reporting(config.messages_db or config.incoming_db)
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
        # Scoped to the room when the send went to one: the same words sent to
        # two chats a breath apart must read back their own bubble.
        if chat_identifier:
            rows = connection.execute(
                """
                SELECT m.guid, m.text, m.attributedBody
                FROM message m
                JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
                JOIN chat c ON c.ROWID = cmj.chat_id
                WHERE m.is_from_me = 1 AND m.date >= ? AND c.chat_identifier = ?
                ORDER BY m.date DESC
                LIMIT 10
                """,
                (since, chat_identifier),
            ).fetchall()
        else:
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


# The guid of the newest attachment this Mac sent, for an attachment with no
# caption to match on. Here, unlike a reaction lookup, the newest outgoing row
# in the window really is the one just sent - the send returned a breath ago -
# so matching by recency is safe, and it is the only handle a captionless
# picture has.
def latest_sent_attachment_guid(
    config: BridgeConfig, chat_identifier: str | None = None
) -> str | None:
    connection, _ = _open_db_reporting(config.messages_db or config.incoming_db)
    if connection is None:
        return None
    since = _apple_time(datetime.now(timezone.utc) - timedelta(seconds=SEND_WINDOW))  # noqa: UP017
    try:
        if chat_identifier:
            row = connection.execute(
                """
                SELECT m.guid FROM message m
                JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
                JOIN chat c ON c.ROWID = cmj.chat_id
                WHERE m.is_from_me = 1 AND m.cache_has_attachments = 1 AND m.date >= ?
                  AND c.chat_identifier = ?
                ORDER BY m.date DESC LIMIT 1
                """,
                (since, chat_identifier),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT guid FROM message
                WHERE is_from_me = 1 AND cache_has_attachments = 1 AND date >= ?
                ORDER BY date DESC LIMIT 1
                """,
                (since,),
            ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    return str(row[0]) if row else None


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
    # Expand each identifier to every copy of that same message.
    #
    # A digest sent to the owner's own address exists twice: the row this Mac
    # sent, and the row their phone received. A reaction left on the phone
    # attaches to the received copy, so matching only the identifier handed back
    # at send time finds nothing — which is exactly what happened, with the
    # reaction sitting in the database as type 2001 the whole time.
    wanted.update(_twins(connection, tuple(wanted.items())))
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


# Every other copy of the same messages, mapped back to the identifier asked
# about.
#
# Two copies exist whenever someone messages their own address, and they carry
# different identifiers. They are matched on body rather than on anything
# structural because that is the only field both rows are guaranteed to share —
# `handle_id`, direction and timestamps all differ between them.
#
# Nothing is returned to the caller from here: the body is read, compared, and
# discarded inside this function, and only identifiers leave it.
def _twins(
    connection: sqlite3.Connection, asked: tuple[tuple[str, str], ...]
) -> dict[str, str]:
    bodies: dict[str, str] = {}
    for suffix, original in asked:
        try:
            row = connection.execute(
                "SELECT text, attributedBody FROM message WHERE guid LIKE ? LIMIT 1",
                (f"%{suffix}",),
            ).fetchone()
        except sqlite3.Error:
            return {}
        if row is None:
            continue
        body = (row[0] or "").strip()
        if not body and row[1]:
            # The body lives in the attributed blob on recent macOS. Only a
            # distinctive slice is needed to recognise the twin.
            body = _readable(bytes(row[1]))
        if body:
            bodies[body[:120]] = original

    if not bodies:
        return {}
    found: dict[str, str] = {}
    try:
        rows = connection.execute(
            """
            SELECT guid, text, attributedBody FROM message
            WHERE date >= ?
            ORDER BY date DESC LIMIT 400
            """,
            (_apple_time(datetime.now(timezone.utc) - timedelta(days=2)),),  # noqa: UP017
        ).fetchall()
    except sqlite3.Error:
        return {}
    for guid, text, blob in rows:
        body = (text or "").strip() or (_readable(bytes(blob)) if blob else "")
        original = bodies.get(body[:120]) if body else None
        if original is not None:
            found[str(guid).split(";")[-1]] = original
    return found


# The legible text inside an attributed-body blob, which is a binary plist with
# the message wrapped in framing. Only used to recognise one message as a copy
# of another, never returned.
def _readable(blob: bytes) -> str:
    try:
        text = blob.decode("utf-8", "ignore")
    except Exception:
        return ""
    # The body sits after the streamtyped header; keeping the printable run is
    # enough to tell two copies of one message apart from a different message.
    printable = "".join(ch if ch.isprintable() else "\n" for ch in text)
    parts = [part.strip() for part in printable.split("\n") if len(part.strip()) > 12]
    return max(parts, key=len) if parts else ""


# The exact message body inside an attributed-body blob, or None.
#
# Incoming bodies mostly live in this blob rather than in `message.text` on
# modern macOS (54 of 64 in one measured sample). `_readable` above is a lossy
# fragment heuristic, good enough to *recognise* a message and nothing more —
# it drops short bodies entirely and keeps only the longest line. A body that
# will be answered has to be exact, so this parses the streamtyped framing
# instead: the UTF-8 payload follows the NSString class marker and a one-byte
# or escaped little-endian length. Anything unexpected returns None rather
# than a mangled string; the caller skips such a message and counts it.
def _typedstream_text(blob: bytes) -> str | None:
    if not blob.startswith(b"\x04\x0bstreamtyped"):
        return None
    # The earliest string-class marker; a mutable string is the common case.
    positions = [
        (index, len(marker))
        for marker in (b"NSMutableString", b"NSString")
        if (index := blob.find(marker)) != -1
    ]
    if not positions:
        return None
    index, marker_length = min(positions)
    after = index + marker_length
    # The `\x01+` type code introduces the raw bytes. It sits past the rest of
    # the class chain — NSString and NSObject follow a mutable string's own
    # marker — so the window is generous but still bounded: a body cannot
    # contain this sequence before the length, because the body starts after it.
    plus = blob.find(b"\x01+", after, after + 64)
    if plus == -1:
        return None
    at = plus + 2
    parsed = _typedstream_length(blob, at)
    if parsed is None:
        return None
    length, start = parsed
    if length == 0 or start + length > len(blob):
        return None
    try:
        return blob[start : start + length].decode("utf-8")
    except UnicodeDecodeError:
        return None


# The payload length at this offset, and where the payload starts, or None.
#
# Lengths under 128 are one byte; 0x81 escapes to a two-byte little-endian
# length and 0x82 to a four-byte one. The length counts bytes, not characters,
# so an emoji body is longer than it looks.
def _typedstream_length(blob: bytes, at: int) -> tuple[int, int] | None:
    if at >= len(blob):
        return None
    first = blob[at]
    if first == 0x81:
        if at + 3 > len(blob):
            return None
        return int.from_bytes(blob[at + 1 : at + 3], "little"), at + 3
    if first == 0x82:
        if at + 5 > len(blob):
            return None
        return int.from_bytes(blob[at + 1 : at + 5], "little"), at + 5
    return first, at + 1


# The best available body for one message row: the plain text column when it
# holds anything, the exactly parsed blob otherwise, None when neither reads.
def extract_body(text: object, blob: object) -> str | None:
    plain = _clean_body(str(text)) if text else ""
    if plain:
        return plain
    if blob:
        parsed = _typedstream_text(bytes(blob))
        if parsed:
            cleaned = _clean_body(parsed)
            if cleaned:
                return cleaned
    return None


# A body without Apple's attachment placeholders. A message carrying a photo
# embeds U+FFFC where the picture sits in the text — a real question arrived
# as "￼how do i fix this bulge?" — and that byte is framing, not something
# the sender said.
def _clean_body(value: str) -> str:
    return value.replace("￼", "").strip()


# The text Messages writes when a reaction cannot be sent as a tapback:
# a verb, then the quoted original. Matched by shape only.
_TAPBACK_TEXT = re.compile(
    r"^(?:Reacted\s.{1,12}?\sto|Liked|Loved|Laughed at|Emphasized|Disliked|Questioned|"
    r"Removed a .{1,24}? from)\s[“\"].+[”\"]\s*$",
    re.DOTALL,
)


def is_tapback_text(body: str) -> bool:
    return bool(_TAPBACK_TEXT.match(body.strip()))


# The most messages one poll may return. Bounds mirror a caller's on purpose;
# a bridge that trusts its caller's limits has no limits.
MAX_INCOMING_PER_POLL = 25

# How long a row is presumed still-being-written if its body will not decode.
#
# Messages inserts a row before it finishes writing attributedBody, so a poll
# arriving in that gap reads the body as undecodable — and a cursor that
# advances past an undecodable row loses the message forever. That happened to
# a real message: a resend's own date came back as the cursor of a poll that
# never returned it, and the same row decoded fine seconds later.
#
# The rule is by decodability, not a blanket age gate, so a message whose body
# is readable is returned at once rather than waiting out this window: a row
# that decodes is delivered immediately; a row younger than this that does NOT
# decode is left for the next poll with the cursor held before it (a mid-write
# in progress); a row older than this that still does not decode is presumed
# genuinely unreadable and skipped past, so one bad row cannot stall the poll
# forever. This removes the settle delay from every ordinary message while
# keeping the mid-write race fixed.
SETTLE_SECONDS = 3


# Every participant of a room, as normalized addresses, so the caller can
# check that each one is somebody it knows. Read only for allowlisted rooms.
def _participants(connection: sqlite3.Connection, chat_rowid: int) -> list[str]:
    try:
        rows = connection.execute(
            """
            SELECT h.id FROM chat_handle_join chj
            JOIN handle h ON h.ROWID = chj.handle_id
            WHERE chj.chat_id = ?
            """,
            (chat_rowid,),
        ).fetchall()
    except sqlite3.Error:
        return []
    return sorted({normalize_recipient(str(row[0] or "")) for row in rows if row[0]})


# The bubbles this account sent in a room over the last month: the anchors a
# reply thread may point at. chat.db is the ledger, so the bridge keeps none.
def _sent_guids_in_chat(connection: sqlite3.Connection, chat_rowid: int) -> set[str]:
    since = _apple_time(datetime.now(timezone.utc) - timedelta(days=30))  # noqa: UP017
    try:
        rows = connection.execute(
            """
            SELECT m.guid FROM message m
            JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            WHERE cmj.chat_id = ? AND m.is_from_me = 1 AND m.date >= ?
            """,
            (chat_rowid, since),
        ).fetchall()
    except sqlite3.Error:
        return set()
    return {str(row[0]) for row in rows if row[0]}


# The handles a message mentions, read from its typedstream: each
# `__kIMMentionConfirmedMention` attribute is followed by the mentioned
# account's address (an email or a number), whatever name the sender's
# contacts rendered it as. Normalized; empty when there is no mention.
_MENTION_MARKER = b"__kIMMentionConfirmedMention"


def mention_targets(blob: object) -> set[str]:
    if blob is None:
        return set()
    data = bytes(blob)
    found: set[str] = set()
    for match in re.finditer(_MENTION_MARKER, data):
        # The address is the next printable run; a length byte that happens
        # to be printable (a 40-character address has length 0x28, "(") can
        # ride in front of it and is dropped.
        run = re.search(rb"[\x20-\x7e]{3,}", data[match.end():match.end() + 400])
        if not run:
            continue
        candidate = run.group(0).decode("ascii", "ignore")
        if candidate and not (candidate[0].isalnum() or candidate[0] == "+"):
            candidate = candidate[1:]
        normalized = normalize_recipient(candidate)
        if normalized:
            found.add(normalized)
    return found


# Why a room's message is for this account, or None when it is not. Three
# shapes, no intent: a reply whose thread is anchored on a bubble this account
# sent there; a mention of one of this account's addresses; the account's
# name as a word in the body, when a name was configured.
def _addressed_to_bot(
    originator: str,
    body: str,
    blob: object,
    sent_guids: set[str],
    display_name: str,
    addresses: frozenset[str] = frozenset(),
) -> str | None:
    if originator and originator in sent_guids:
        return "reply"
    if addresses and mention_targets(blob) & addresses:
        return "mention"
    name = (display_name or "").strip()
    if name and re.search(r"(?<![\w])" + re.escape(name) + r"(?![\w])", body, re.IGNORECASE):
        return "name"
    return None


# Incoming one-to-one messages from allowlisted senders, after a cursor.
#
# The bridge stays stateless: the caller owns the cursor, which is the raw
# Apple-epoch nanosecond `date` of the newest row scanned — scanned, not
# returned, so a stranger's messages advance it too and cannot stall the poll.
# A negative cursor means "start from now": a first-time caller gets no
# replayed history, only a cursor to poll forward from.
#
# Senders are filtered against the allowlist plus grants *here*, and the
# bodies of anyone else never leave this function. Group chats are excluded
# entirely — a room is not a person who was allowlisted. Tapbacks and other
# associated messages are not messages and are excluded in SQL.
def incoming_messages(
    config: BridgeConfig, since_ns: int, limit: int = MAX_INCOMING_PER_POLL
) -> dict[str, object]:
    bounded = max(1, min(int(limit), MAX_INCOMING_PER_POLL))
    now_ns = _apple_time(datetime.now(timezone.utc))  # noqa: UP017
    young_after = now_ns - SETTLE_SECONDS * 1_000_000_000
    if since_ns is None or int(since_ns) < 0:
        # Start from just before now, not now: a message landing during this
        # first connect should be caught by the next poll, not stepped over.
        return {"messages": [], "cursor": young_after}
    cursor = int(since_ns)
    connection, _ = _open_db_reporting(config.incoming_db)
    if connection is None:
        return {"messages": [], "cursor": cursor}
    try:
        # The handle join is correct here, unlike the outgoing queries above:
        # an incoming row's handle_id is the sender, and Apple's canonical
        # `handle.id` is exactly the address a reply should be sent to. No age
        # ceiling in SQL: decodability, checked per row below, decides what is
        # ready — an age gate would delay every message, not just mid-write ones.
        # One-to-one rows always; rows from allowlisted rooms only when group
        # reading is on. With it off the query is the one it always was.
        group_ids = sorted(config.groups) if config.read_groups else []
        room_clause = (
            "AND (c.room_name IS NULL OR (c.style = 43 AND c.chat_identifier IN ("
            + ",".join("?" for _ in group_ids)
            + ")))"
            if group_ids
            else "AND c.room_name IS NULL"
        )
        rows = connection.execute(
            f"""
            SELECT m.ROWID, m.guid, m.date, m.text, m.attributedBody, h.id,
                   m.thread_originator_guid, c.ROWID, c.style, c.chat_identifier,
                   c.display_name
            FROM message m
            JOIN handle h ON h.ROWID = m.handle_id
            JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            JOIN chat c ON c.ROWID = cmj.chat_id
            WHERE m.is_from_me = 0
              AND m.associated_message_type = 0
              AND m.item_type = 0
              AND m.date > ?
              {room_clause}
            ORDER BY m.date ASC
            LIMIT ?
            """,
            (cursor, *group_ids, bounded),
        ).fetchall()
        # What deciding "addressed" needs, read while the connection is open:
        # each room's participants and the bubbles this account sent there.
        rooms = {int(row[7]) for row in rows if int(row[8] or 0) == 43}
        participants = {room: _participants(connection, room) for room in rooms}
        sent_in_room = {room: _sent_guids_in_chat(connection, room) for room in rooms}
        listings = (
            _attachment_listings(connection, [int(row[0]) for row in rows])
            if config.attachments_enabled and rows
            else {}
        )
    except sqlite3.Error:
        return {"messages": [], "cursor": cursor}
    finally:
        connection.close()

    allowed = config.allowed_recipients | load_grants(config)
    messages: list[dict[str, object]] = []
    for rowid, guid, date, text, blob, handle, originator, chat_rowid, style, chat_identifier, chat_name in rows:
        attached = listings.get(int(rowid), [])
        body = extract_body(text, blob)
        # A photo with no caption has no body but is still a message; a row is
        # "ready" when it has either a readable body or a listed attachment.
        ready = body is not None or bool(attached)
        if not ready and int(date) > young_after:
            # Young and not yet readable: a write in progress. Stop here without
            # advancing the cursor past it — rows are ascending, so everything
            # after is younger still — and let the next poll pick it up whole.
            break
        cursor = max(cursor, int(date))
        sender = normalize_recipient(str(handle or ""))
        if sender not in allowed:
            continue
        if not ready:
            # Old and still unreadable: presumed genuinely unreadable, skipped
            # with the cursor already advanced so it cannot stall the poll.
            continue
        if not attached and body is not None and is_tapback_text(body):
            # A reaction rendered as text - "Reacted ❤️ to “...”", "Liked
            # “...”" - arrives from some senders as an ordinary row with
            # associated_message_type 0. It is not something the person said:
            # routed as a message on 2026-08-25 it was answered with a salsa
            # recommendation. Shape, not intent, so a pattern is the right tool.
            continue
        in_room = int(style or 0) == 43
        addressed_by = None
        if in_room:
            # Every allowlisted member's message in a listed room is forwarded
            # - the operator's decision (2026-08-28): the assistant reads the
            # whole room for context and replies only when addressed. How it
            # was addressed, when it was: a reply in a thread anchored on one
            # of its bubbles, a mention, or its name; empty otherwise.
            addressed_by = _addressed_to_bot(
                str(originator or ""),
                body or "",
                blob,
                sent_in_room.get(int(chat_rowid), set()),
                config.display_name,
                config.addresses,
            ) or ""
        message: dict[str, object] = {
            "guid": str(guid),
            "sender": sender,
            # A room is answered in the room: the reply address is the chat.
            "reply_to": chat_guid_for(str(chat_identifier)) if in_room else str(handle),
            "text": body or "",
            "sent_at": _apple_epoch(date),
        }
        if in_room:
            message["chat_guid"] = chat_guid_for(str(chat_identifier))
            message["chat_identifier"] = str(chat_identifier)
            message["chat_name"] = str(chat_name or "")
            message["participants"] = participants.get(int(chat_rowid), [])
            message["addressed_by"] = addressed_by
            # What people in the room call this account - the name a mention
            # renders - so the reply knows whom "Scout, ..." is addressing.
            message["assistant_name"] = config.display_name
        if attached:
            message["attachments"] = attached
        # A native long-press reply carries the guid of the bubble it answers.
        # It lets the caller target a specific earlier picture explicitly,
        # rather than always the most recent one. Absent on ordinary messages.
        if originator:
            message["reply_to_guid"] = str(originator)
        messages.append(message)
    return {"messages": messages, "cursor": cursor}


# The attachments listed on each of these messages: metadata only, never
# bytes. Bytes leave only through attachment_payload, which re-proves who
# sent the file before reading it.
def _attachment_listings(
    connection: sqlite3.Connection, message_rowids: list[int]
) -> dict[int, list[dict[str, object]]]:
    if not message_rowids:
        return {}
    placeholders = ",".join("?" for _ in message_rowids)
    try:
        rows = connection.execute(
            f"""
            SELECT maj.message_id, a.ROWID, a.mime_type, a.transfer_name,
                   a.total_bytes
            FROM message_attachment_join maj
            JOIN attachment a ON a.ROWID = maj.attachment_id
            WHERE maj.message_id IN ({placeholders})
            """,
            message_rowids,
        ).fetchall()
    except sqlite3.Error:
        return {}
    listings: dict[int, list[dict[str, object]]] = {}
    for message_id, attachment_id, mime, name, total in rows:
        listings.setdefault(int(message_id), []).append(
            {
                "attachment_id": str(attachment_id),
                "media_type": str(mime or ""),
                "name": str(name or ""),
                "bytes": int(total or 0),
            }
        )
    return listings


# The most bytes one fetched attachment may be, after any conversion.
MAX_INBOUND_ATTACHMENT_BYTES = 10 * 1024 * 1024

# The only media types an inbound attachment may come back as. Images only:
# a video is a much larger disclosure and nothing downstream can use one yet.
INBOUND_IMAGE_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/gif", "image/webp", "image/heic", "image/heif"}
)

# The media type a file's suffix implies, when the database recorded none.
def _suffix_media(path: Path) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".heic": "image/heic",
        ".heif": "image/heif",
    }.get(path.suffix.lower(), "")


# One HEIC file as a JPEG, converted by the system's own tool, or None.
#
# `sips` ships with macOS, so the conversion adds no dependency, and it runs
# on a copy path: the source in the Messages store is never written to.
def _heic_to_jpeg(source: Path, directory: Path) -> Path | None:
    target = directory / (source.stem + ".jpeg")
    try:
        result = subprocess.run(
            ["sips", "-s", "format", "jpeg", str(source), "--out", str(target)],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not target.exists():
        return None
    return target


# One attachment an allowlisted sender sent, as base64, or a refusal.
#
# The identifier alone is never a capability: the fetch re-proves, in one
# query, that the file arrived on an incoming one-to-one message from a
# sender on the allowlist — and every refusal reads "not_found", so an
# identifier cannot be probed for whether it exists. The file path recorded
# in the database is honored only inside the Messages attachment store, so a
# hostile row cannot point this bridge at an arbitrary file on the Mac.
def attachment_payload(config: BridgeConfig, attachment_id: str) -> dict[str, object]:
    if not config.attachments_enabled or config.incoming_db is None:
        return {"error": "not_found"}
    try:
        rowid = int(str(attachment_id).strip())
    except (TypeError, ValueError):
        return {"error": "not_found"}
    owned = _owned_attachment(config, rowid)
    if owned is None:
        return {"error": "not_found"}
    resolved, media, name = owned
    if media not in INBOUND_IMAGE_TYPES:
        return {"error": "unsupported_type", "media_type": media}
    return _attachment_bytes(resolved, media, name)


# The file, media type and name of one attachment — but only if it arrived on
# an incoming one-to-one message from an allowlisted sender, and only if its
# recorded path stays inside the Messages store. None otherwise, always.
def _owned_attachment(
    config: BridgeConfig, rowid: int
) -> tuple[Path, str, str] | None:
    connection, _ = _open_db_reporting(config.incoming_db)
    if connection is None:
        return None
    # A picture from an allowlisted room is read like a one-to-one one; the
    # sender is re-proved below either way.
    room_ids = sorted(config.groups) if config.read_groups else []
    try:
        row = connection.execute(
            """
            SELECT a.filename, a.mime_type, a.transfer_name, h.id
            FROM attachment a
            JOIN message_attachment_join maj ON maj.attachment_id = a.ROWID
            JOIN message m ON m.ROWID = maj.message_id
            JOIN handle h ON h.ROWID = m.handle_id
            JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            JOIN chat c ON c.ROWID = cmj.chat_id
            WHERE a.ROWID = ?
              AND m.is_from_me = 0
              AND (c.room_name IS NULL OR (c.style = 43 AND c.chat_identifier IN ({rooms})))
            LIMIT 1
            """.replace(
                "{rooms}",
                ",".join("?" for _ in room_ids) if room_ids else "''",
            ),
            (rowid, *room_ids),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    if row is None:
        return None
    filename, mime, transfer_name, handle = row
    if normalize_recipient(str(handle or "")) not in (
        config.allowed_recipients | load_grants(config)
    ):
        return None
    if not filename:
        return None
    root = config.attachments_root.expanduser().resolve()
    try:
        resolved = Path(str(filename)).expanduser().resolve(strict=True)
    except OSError:
        return None
    if not resolved.is_relative_to(root):
        return None
    media = str(mime or "") or _suffix_media(resolved)
    return resolved, media, str(transfer_name or resolved.name)


# The file's bytes as a payload, converting HEIC to JPEG on the way out.
def _attachment_bytes(
    resolved: Path, media: str, name: str
) -> dict[str, object]:
    if media in {"image/heic", "image/heif"}:
        # Converted in a directory that is removed however this returns, so a
        # failed fetch leaves nothing behind.
        with tempfile.TemporaryDirectory(prefix="anios-attachment-") as directory:
            converted = _heic_to_jpeg(resolved, Path(directory))
            if converted is None:
                return {"error": "unreadable"}
            data = converted.read_bytes()
        media = "image/jpeg"
        name = str(Path(name).stem) + ".jpeg"
    else:
        try:
            data = resolved.read_bytes()
        except OSError:
            return {"error": "unreadable"}
    if len(data) > MAX_INBOUND_ATTACHMENT_BYTES:
        return {"error": "too_large", "bytes": len(data)}
    return {
        "media_type": media,
        "name": name,
        "data_base64": base64.b64encode(data).decode("ascii"),
    }


# Whether incoming reading is configured and working, as counts only.
#
# Same posture as diagnose() below: shapes answer every setup question that
# matters, and the decodable count is the one number that tells whether the
# typedstream extractor is keeping up with real traffic — without it, poor
# coverage would read as allowlisted people being ignored.
def describe_incoming(config: BridgeConfig) -> dict[str, object]:
    if config.incoming_db is None:
        return {
            "readable": False,
            "why": "IMESSAGE_BRIDGE_READ_INCOMING is off, or the database path "
            "does not exist.",
        }
    connection, how = _open_db_reporting(config.incoming_db)
    if connection is None:
        return {"readable": False, "why": how}
    since = _apple_time(datetime.now(timezone.utc) - timedelta(days=1))  # noqa: UP017
    try:
        rows = connection.execute(
            """
            SELECT text, attributedBody FROM message
            WHERE is_from_me = 0 AND associated_message_type = 0 AND date >= ?
            """,
            (since,),
        ).fetchall()
    except sqlite3.Error as error:
        return {"readable": False, "why": f"Query failed: {type(error).__name__}"}
    finally:
        connection.close()
    decodable = sum(1 for text, blob in rows if extract_body(text, blob) is not None)
    groups_note = {
        "groups_readable": config.read_groups,
        "groups_allowlisted": len(config.groups),
        "mention_addresses": len(config.addresses),
    }
    return {
        **groups_note,
        "readable": True,
        "opened_with": how,
        "incoming_last_day": len(rows),
        "incoming_decodable_last_day": decodable,
    }


# Which of the given message bodies were thumbed up or down, by position.
#
# Matching on the body rather than on an identifier is the whole point. Apple
# hands back no identifier at send time, the one this bridge looked up afterwards
# proved wrong, and a reaction made on a phone can point at a copy of the message
# this Mac never stored. The body is the one thing both copies share and the
# caller already knows.
#
# Only positions are returned. Nothing about any message, and nothing about any
# message the caller did not itself send, leaves here.
def reactions_for_bodies(
    config: BridgeConfig, bodies: list[str]
) -> list[dict[str, object]]:
    wanted = {
        index: " ".join(body.split())[:BODY_MATCH_CHARS]
        for index, body in enumerate(bodies or [])
        if body and body.strip()
    }
    if not wanted:
        return []
    connection, _ = _open_messages_reporting(config)
    if connection is None:
        return []
    try:
        rows = connection.execute(
            """
            SELECT guid, text, attributedBody FROM message
            WHERE date >= ?
            ORDER BY date DESC LIMIT 600
            """,
            (_apple_time(datetime.now(timezone.utc) - timedelta(days=FEEDBACK_DAYS)),),  # noqa: UP017
        ).fetchall()
        by_guid = _copies_of(rows, wanted)
        if not by_guid:
            return []

        clauses = " OR ".join("associated_message_guid LIKE ?" for _ in by_guid)
        reacted = connection.execute(
            f"""
            SELECT associated_message_guid, associated_message_type, date
            FROM message
            WHERE associated_message_type IN (2001, 2002, 3001, 3002)
              AND ({clauses})
            ORDER BY date ASC
            """,
            [f"%{guid}" for guid in by_guid],
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()

    # Latest wins: a thumb added and then removed is no opinion, and one changed
    # from down to up is a changed mind.
    latest: dict[int, dict[str, object]] = {}
    for associated, kind, when in reacted:
        index = by_guid.get(str(associated or "").split("/")[-1])
        if index is None:
            continue
        if kind in (3001, 3002):
            latest.pop(index, None)
            continue
        latest[index] = {
            "index": index,
            "reaction": "liked" if kind == 2001 else "disliked",
            "at": _apple_epoch(when),
        }
    return list(latest.values())


# Every copy of every body asked about, mapped to the position it was given at.
#
# Both directions on purpose: the row this Mac sent and the row a phone received
# are different rows with different identifiers, and a reaction can land on
# either.
def _copies_of(
    rows: list[tuple[object, object, object]], wanted: dict[int, str]
) -> dict[str, int]:
    found: dict[str, int] = {}
    for guid, text, blob in rows:
        body = (str(text or "").strip()) or (_readable(bytes(blob)) if blob else "")
        if not body:
            continue
        flat = " ".join(body.split())
        for index, prefix in wanted.items():
            if prefix and prefix in flat:
                found[str(guid).split(";")[-1]] = index
                break
    return found


# How much of a body is compared, and how far back a reaction is looked for.
# Both mirror the caller's own bounds; a bridge that trusts its caller's limits
# has no limits.
BODY_MATCH_CHARS = 80
FEEDBACK_DAYS = 8


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
        # Inside the try, because the finally below closes the connection before
        # the return statement runs — which is exactly how the first version of
        # this failed with "cannot operate on a closed database".
        targets = [
            str(target)
            for (target,) in connection.execute(
                """
                SELECT associated_message_guid FROM message
                WHERE associated_message_type IN (2001, 2002)
                ORDER BY date DESC LIMIT 5
                """
            ).fetchall()
        ]
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
        # What the recent thumbs actually point at.
        #
        # A reaction was left, arrived as type 2001, and still matched none of
        # the identifiers this bridge had handed out — so the question is no
        # longer "is it there" but "is it pointing at the message we think we
        # sent". These are opaque identifiers carrying no content, and comparing
        # them against what was stored is the only way to see the mismatch.
        "recent_thumb_targets": targets,
        # For each of those targets: is the message it points at even on this
        # Mac, and did this Mac send it?
        #
        # Expanding an identifier to its twin assumes both copies are here. If
        # a reaction made on the phone points at a row this Mac never stored,
        # no amount of matching will find it and the design has to change rather
        # than the query. Existence and direction only — no content.
        "thumb_target_rows": _describe_targets(config, targets),
    }


# Whether each reaction target exists here, and which direction it went.
def _describe_targets(
    config: BridgeConfig, targets: list[str]
) -> list[dict[str, object]]:
    connection, _ = _open_messages_reporting(config)
    if connection is None:
        return []
    described: list[dict[str, object]] = []
    try:
        for target in targets:
            suffix = str(target).split("/")[-1]
            row = connection.execute(
                "SELECT is_from_me, length(text) FROM message"
                " WHERE guid LIKE ? LIMIT 1",
                (f"%{suffix}",),
            ).fetchone()
            described.append(
                {
                    "target": suffix[:8],
                    "found": row is not None,
                    "is_from_me": None if row is None else int(row[0] or 0),
                    "has_plain_text": None if row is None else bool(row[1]),
                }
            )
    except sqlite3.Error:
        return described
    finally:
        connection.close()
    return described


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
    chat = normalize_chat_target(recipient)
    to_chat = chat is not None
    text = body.strip()
    if len(text) > MAX_BODY_CHARS:
        raise BridgeError("Message body is too long.")

    attachment = decode_attachment(
        attachment_name, attachment_media_type, attachment_base64
    )
    if attachment is None:
        # A body is required only for a plain text send. A picture with no
        # caption is a message too, and the worker sends exactly that - so
        # requiring a body here rejected every attachment-only send before it
        # reached the attachment branch, and no image the bridge sent that way
        # ever left the Mac.
        if not text:
            raise BridgeError("A message body is required.")
        run_osascript(
            _SEND_TEXT_TO_CHAT if to_chat else _SEND_TEXT,
            [config.account_id, recipient, text],
        )
        # The identifier a tapback will point at, when this Mac allows it to be
        # read. "sent" otherwise, which is what every caller understood before
        # feedback existed and still handles.
        return latest_sent_guid(config, recipient, text, chat_identifier=chat) or "sent"

    safe_name, content = attachment
    # Spooled, not temp-filed, and spooled somewhere Messages may read (see
    # _spool_directory). Messages' `send` returns once the message is queued
    # and reads the file afterwards to upload it — deleting the file as soon
    # as osascript returns races the upload, and a path outside Messages'
    # sandbox never uploads at all while still reporting success. The spool
    # is cleaned of old files on the next attachment send, once Messages has
    # either uploaded them or never will.
    _clean_spool()
    directory = Path(tempfile.mkdtemp(prefix="send-", dir=_spool_directory()))
    path = directory / safe_name
    path.write_bytes(content)
    run_osascript(
        _SEND_WITH_ATTACHMENT_TO_CHAT if to_chat else _SEND_WITH_ATTACHMENT,
        [config.account_id, recipient, text, str(path)],
    )
    # The guid readback, so a caller can remember which bubble carried which
    # picture. A captioned send matches on its body like a text send; an
    # attachment with no caption has no body to match, so it reads back the
    # newest outgoing row that carries an attachment instead. "sent with
    # attachment" only when the guid cannot be read - what callers saw before.
    guid = (
        latest_sent_guid(config, recipient, text, chat_identifier=chat)
        if text
        else latest_sent_attachment_guid(config, chat_identifier=chat)
    )
    return guid or "sent with attachment"


# Where outbound attachments wait for Messages to pick them up.
#
# Under ~/Pictures, and that location is load-bearing: Messages is sandboxed,
# and a scripted send hands it a bare path it must be entitled to read. Its
# sandbox reads ~/Pictures; it does not read hidden home folders or the
# system temp tree — a transfer sourced from either queues as "waiting"
# forever and renders as a bubble that does nothing when clicked, while the
# send itself reports success. Proven live both ways: the same file stuck
# from the old dot-folder and finished from here.
def _spool_directory() -> Path:
    spool = Path.home() / "Pictures" / "anios-outbox"
    spool.mkdir(parents=True, exist_ok=True)
    return spool


# How long a spooled attachment may wait before it is presumed uploaded.
SPOOL_MAX_AGE_SECONDS = 3600


# Remove spooled attachments old enough that Messages is done with them.
#
# Cleaning happens on the next send rather than on a timer, so the bridge
# stays free of background work — and a failed cleanup never fails a send,
# because a stray old file costs disk, not correctness.
def _clean_spool() -> None:
    import shutil
    import time

    spool = _spool_directory()
    cutoff = time.time() - SPOOL_MAX_AGE_SECONDS
    try:
        entries = list(spool.iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue


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
        """Send one iMessage, optionally with a calendar file or picture."""
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
        # to read the Mac. The incoming block reports the same for the
        # conversation grant, including extractor coverage on real traffic.
        return json.dumps({**diagnose(config), "incoming": describe_incoming(config)})

    @server.tool()
    def read_messages(since_ns: int = -1, limit: int = 25) -> str:
        """Report incoming messages from allowlisted senders, after a cursor."""
        # The one tool that returns message bodies, and only under its own
        # grant: IMESSAGE_BRIDGE_READ_INCOMING off means an empty answer, not
        # an error. Who may be heard is decided here on the Mac — allowlist
        # plus grants — never by the caller. The caller owns the cursor;
        # since_ns=-1 starts from now so no history is ever replayed.
        return json.dumps(incoming_messages(config, since_ns, limit))

    @server.tool()
    def read_attachment(attachment_id: str) -> str:
        """Fetch one image an allowlisted sender attached, as base64."""
        # Bytes leave the Mac only through here, only under the attachments
        # grant, and only after the fetch re-proves the file arrived from an
        # allowlisted sender. Every refusal reads "not_found" so identifiers
        # cannot be probed.
        return json.dumps(attachment_payload(config, attachment_id))

    @server.tool()
    def read_reactions(bodies: list[str]) -> str:
        """Report thumbs-up and thumbs-down tapbacks on messages this sent."""
        # Answers positionally: "the third body you gave me was thumbed up".
        # The caller already knows what it sent, so nothing about any message
        # needs to come back — and asking by body rather than by identifier is
        # what makes this work at all, since a reaction can point at a copy of
        # the message this Mac never stored.
        return json.dumps({"reactions": reactions_for_bodies(config, bodies)})

    @server.tool()
    def read_reactions_by_guid(message_guids: list[str]) -> str:
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
    "attachment_payload",
    "build_app",
    "BridgeError",
    "check_recipient",
    "create_bridge",
    "decode_attachment",
    "describe_incoming",
    "extract_body",
    "incoming_messages",
    "latest_sent_attachment_guid",
    "load_grants",
    "normalize_recipient",
    "send_message",
    "store_grant",
]
