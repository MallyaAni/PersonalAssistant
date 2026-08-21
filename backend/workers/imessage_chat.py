"""The conversation, over iMessage.

The web chat is one client of `/chat`; this worker makes the Mac bridge
another. It polls the bridge for new inbound texts from allowlisted
senders, maps each sender to the account that subscribed that address,
runs the text through the same `/chat` endpoint the browser uses - full
production path: auth, model gate, memory, tools, the lot - and sends the
reply back through `send_imessage`. Nothing conversational is reimplemented
here; this is transport.

Identity is the subscriber allowlist. A sender whose normalized address is
not an active, approved subscriber of some account is ignored outright -
the bridge already filters to allowlisted senders, so this is the second
of two walls, and the reply goes to the bridge's `reply_to` handle, never
to anything the model wrote.

Auth into `/chat` is a short-lived bearer minted per message with the one
scope this worker needs. The worker holds SECRET_KEY like every backend
process; what the token buys is that the request travels the same
authorization path as every other client instead of around it.

State lives in Redis and fails soft: the bridge cursor (so a restart never
replays history), seen guids (belt-and-braces dedup over the cursor's
strict ordering), and one conversation id per account (so texting feels
like one ongoing thread, exactly like the web sidebar).
"""

import asyncio
import json
import re

import httpx
from redis.asyncio import Redis
from sqlalchemy import select

from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.core.logging_config import get_logger
from backend.database.session import AsyncSessionLocal
from backend.discovery.addressing import normalize_address

logger = get_logger(__name__)

_CURSOR_KEY = "imessage:chat:cursor"
_SEEN_KEY = "imessage:chat:seen:{guid}"
_CONVERSATION_KEY = "imessage:chat:conversation:{user_id}"
_SEEN_TTL_SECONDS = 3 * 24 * 3600

# One reply can take a while on the local model; the read timeout has to
# outlive a long generation, not a network hiccup.
_CHAT_TIMEOUT_SECONDS = 300.0

# Fixed wording for a failed turn, for the same reason the assembled digest
# greeting is fixed: a model composing an apology afresh would vary it for
# no reason and could vary it into something wrong.
_FAILURE_REPLY = "I hit a problem answering that. Give me a minute and try again."


class IMessageChatWorker:
    """Poll inbound texts, converse through /chat, reply through the bridge."""

    def __init__(
        self,
        invoke_tool,
        base_url: str | None = None,
        redis: Redis | None = None,
    ) -> None:
        self.invoke_tool = invoke_tool
        self.base_url = (base_url or settings.IMESSAGE_CHAT_BASE_URL).rstrip("/")
        self.redis = redis or Redis.from_url(settings.REDIS_URL, decode_responses=True)

    # One poll: read what arrived, answer what maps to an account, advance
    # the cursor. Returns how many messages were answered, for the log line.
    async def tick(self) -> int:
        cursor = await self._cursor()
        try:
            answer = await self.invoke_tool(
                settings.IMESSAGE_CHAT_READ_TOOL,
                {"since_ns": cursor, "limit": 25},
            )
        except Exception:
            # An unreachable Mac or a bridge without the tool means "nothing
            # this time", exactly as it does for reactions.
            return 0
        payload = _payload(answer)
        answered = 0
        for message in payload.get("messages", []):
            guid = str(message.get("guid") or "")
            text = str(message.get("text") or "").strip()
            reply_to = str(message.get("reply_to") or "")
            if not guid or not text or not reply_to:
                continue
            if not await self._first_sighting(guid):
                continue
            user_id = await self._account_for(str(message.get("sender") or ""))
            if user_id is None:
                continue
            reply = await self._converse(user_id, text)
            try:
                await self.invoke_tool(
                    settings.DISCOVERY_IMESSAGE_TOOL,
                    # Flattened at the send boundary: the model writes
                    # markdown for the web UI, and an iMessage bubble
                    # renders none of it.
                    {"to": reply_to, "body": plain_text(reply)},
                )
                answered += 1
            except Exception:
                logger.warning("imessage_chat_reply_failed", extra={"user": user_id})
        new_cursor = payload.get("cursor")
        if isinstance(new_cursor, int):
            await self._remember_cursor(new_cursor)
        return answered

    # The account that subscribed this address, or None. Looked up by the
    # address digest the subscriber table already indexes - no decryption -
    # and only an active, approved subscription counts: an address that was
    # revoked stops being an identity the moment it stops being a recipient.
    async def _account_for(self, sender: str) -> str | None:
        normalized = normalize_address(sender)
        if not normalized:
            return None
        from backend.discovery.types import label_digest
        from backend.models.discovery_subscriber import DiscoverySubscriber

        async with AsyncSessionLocal() as db:
            rows = (
                (
                    await db.execute(
                        select(DiscoverySubscriber).where(
                            DiscoverySubscriber.address_digest
                            == label_digest(normalized),
                            DiscoverySubscriber.active.is_(True),
                            DiscoverySubscriber.approved_at.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
        return str(rows[0].user_id) if rows else None

    # One turn through the same endpoint the browser uses. The reply is the
    # concatenated deltas; the conversation id from the stream's start event
    # is remembered so the next text continues the same thread.
    async def _converse(self, user_id: str, text: str) -> str:
        token = issue_user_token(user_id, ttl_seconds=600, scopes=["chat"])
        body: dict[str, object] = {"user_id": user_id, "query": text}
        stored = await self._stored_conversation(user_id)
        if stored:
            body["conversation_id"] = stored
        collected: list[str] = []
        try:
            async with (
                httpx.AsyncClient(timeout=_CHAT_TIMEOUT_SECONDS) as client,
                client.stream(
                    "POST",
                    f"{self.base_url}/api/v1/chat",
                    json=body,
                    headers={"Authorization": f"Bearer {token}"},
                ) as response,
            ):
                response.raise_for_status()
                event = ""
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        event = line[7:].strip()
                    elif line.startswith("data: "):
                        data = _loads(line[6:])
                        if event == "start" and data.get("conversation_id"):
                            await self._remember_conversation(
                                user_id, str(data["conversation_id"])
                            )
                        elif event == "delta" and isinstance(
                            data.get("content"), str
                        ):
                            collected.append(data["content"])
        except Exception:
            logger.warning("imessage_chat_turn_failed", extra={"user": user_id})
            return _FAILURE_REPLY
        reply = "".join(collected).strip()
        return reply or _FAILURE_REPLY

    async def _cursor(self) -> int:
        try:
            raw = await self.redis.get(_CURSOR_KEY)
            return int(raw) if raw is not None else -1
        except Exception:
            return -1

    async def _remember_cursor(self, cursor: int) -> None:
        try:
            await self.redis.set(_CURSOR_KEY, str(cursor))
        except Exception:
            return

    # True exactly once per guid. With Redis down this admits repeats, which
    # the cursor's strict ordering already makes rare; answering a text twice
    # beats never answering under a degraded cache.
    async def _first_sighting(self, guid: str) -> bool:
        try:
            return bool(
                await self.redis.set(
                    _SEEN_KEY.format(guid=guid),
                    "1",
                    ex=_SEEN_TTL_SECONDS,
                    nx=True,
                )
            )
        except Exception:
            return True

    # The stored thread id expires after the idle window, and every use
    # renews it. iMessage has no "new chat" button, so the session boundary
    # is a lull - the way texting already works: keep replying and it stays
    # one conversation, go quiet for a day and the next text opens a fresh
    # one, with memory and recall carrying whatever mattered across.
    async def _stored_conversation(self, user_id: str) -> str | None:
        key = _CONVERSATION_KEY.format(user_id=user_id)
        try:
            stored = await self.redis.get(key)
            if stored:
                await self.redis.expire(key, self._idle_seconds())
            return stored
        except Exception:
            return None

    async def _remember_conversation(self, user_id: str, conversation_id: str) -> None:
        try:
            await self.redis.set(
                _CONVERSATION_KEY.format(user_id=user_id),
                conversation_id,
                ex=self._idle_seconds(),
            )
        except Exception:
            return

    @staticmethod
    def _idle_seconds() -> int:
        return int(settings.IMESSAGE_CHAT_SESSION_IDLE_HOURS * 3600)


# Markdown, flattened for a channel that renders none of it. The chat model
# writes for the web UI, where asterisks are bold and hashes are headings;
# in an iMessage bubble they are just noise the reader has to squint past.
# This is presentation plumbing, not judgement - the words are untouched,
# links keep their address, and bullets stay bullets in a form a text
# message can carry.
_FENCE = re.compile(r"^```[^\n]*$", re.MULTILINE)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_EMPHASIS = re.compile(r"(\*\*\*|\*\*|\*|___|__|_)(?=\S)(.+?)(?<=\S)\1")
_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_BULLET = re.compile(r"^(\s*)[-*+]\s+", re.MULTILINE)
_RULE = re.compile(r"^\s*([-*_]\s*){3,}$", re.MULTILINE)
_BLANKS = re.compile(r"\n{3,}")


def plain_text(reply: str) -> str:
    text = _FENCE.sub("", reply)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _IMAGE.sub(r"\1", text)
    # The label and the address both survive; iMessage links the bare URL.
    text = _LINK.sub(r"\1 (\2)", text)
    for _ in range(3):
        text = _EMPHASIS.sub(r"\2", text)
    text = _HEADING.sub("", text)
    text = _RULE.sub("", text)
    text = _BULLET.sub(r"\1• ", text)
    return _BLANKS.sub("\n\n", text).strip()


def _loads(text: str) -> dict:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except ValueError:
        return {}


# The bridge answers a JSON string inside the MCP result, in the same shapes
# the reactions reader tolerates.
def _payload(answer: object) -> dict:
    payload: object = answer
    if not isinstance(payload, dict):
        text = payload if isinstance(payload, str) else getattr(payload, "content", "")
        if not isinstance(text, str) or not text.strip():
            return {}
        try:
            payload = json.loads(text)
        except ValueError:
            return {}
    return payload if isinstance(payload, dict) else {}


# The polling loop, spawned alongside the discovery loop when the flag is on.
async def run_chat_loop() -> None:
    from backend.core.dependencies import _invoke_discovery_tool

    worker = IMessageChatWorker(_invoke_discovery_tool)
    logger.info("imessage_chat_started")
    while True:
        try:
            answered = await worker.tick()
            if answered:
                logger.info("imessage_chat_answered", extra={"count": answered})
        except Exception:
            logger.exception("imessage_chat_tick_failed")
        await asyncio.sleep(settings.IMESSAGE_CHAT_POLL_SECONDS)
