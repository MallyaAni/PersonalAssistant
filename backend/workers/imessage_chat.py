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
import base64
import json
import random
import time
import re
import uuid
from dataclasses import dataclass, field

import httpx
from redis.asyncio import Redis
from sqlalchemy import select

from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.core.logging_config import get_logger
from backend.database.session import AsyncSessionLocal
from backend.discovery.addressing import normalize_address

# The digest channel's guid reader, reused rather than re-derived: it already
# tells an Apple message identifier apart from "sent with attachment", and
# two parsers for one bridge answer would drift.
from backend.discovery.channels import _guid as _message_guid

logger = get_logger(__name__)

_CURSOR_KEY = "imessage:chat:cursor"
_SEEN_KEY = "imessage:chat:seen:{guid}"
_CONVERSATION_KEY = "imessage:chat:conversation:{user_id}"
_IMAGE_KEY = "imessage:chat:image:{user_id}"
# Which artifact a sent image bubble carried, keyed by the bridge's message
# guid. This is what lets a native reply to that bubble pin that image as
# the ask/edit target, overriding recency.
_BUBBLE_KEY = "imessage:chat:bubble:{guid}"
# A burst in progress: the fragments a person has sent since the last reply
# that were judged unfinished, keyed by where the reply would go. The index
# lets a poll find bursts whose safety cap has passed.
_PENDING_KEY = "imessage:chat:pending:{to}"
_PENDING_INDEX_KEY = "imessage:chat:pending"
# The last bubble sent to an address, for the readiness judgement's "what
# the assistant said before these fragments".
_LAST_REPLY_KEY = "imessage:chat:last_reply:{to}"
# One operator alert per room per day about a room the assistant must stay
# quiet in.
_ROOM_ALERT_KEY = "imessage:chat:room_alert:{digest}"
# Turns that failed for an infrastructure reason - the backend refusing
# connections mid-deploy, the database unreachable - parked here and retried
# every poll until they answer or the window closes. Nothing addressed to the
# assistant is lost to a restart (operator's question, 2026-08-28).
_PARKED_KEY = "imessage:chat:parked"
_SEEN_TTL_SECONDS = 3 * 24 * 3600
_BUBBLE_TTL_SECONDS = 7 * 24 * 3600
_PENDING_TTL_SECONDS = 24 * 3600
_ROOM_ALERT_TTL_SECONDS = 24 * 3600
_PARKED_TTL_SECONDS = 24 * 3600
# Fixed wording, like the failure reply, for the same reason.
_PARKED_NOTICE = "Give me a minute - I'm mid-restart and will answer this shortly."

# Margin under the bridge's 5MB attachment cap, which bounds what a
# compromised backend could pump through the Mac and is not negotiated
# with - an oversized image is re-encoded to fit instead.
_MAX_OUTBOUND_IMAGE_BYTES = 4_500_000


# The bytes as they will be sent: unchanged when they fit, flattened to
# JPEG when they do not. Quality 85 puts even a detailed generation well
# under the cap. A diagram arrives as SVG, which the bridge rightly
# refuses (its attachment allowlist is jpeg/png/calendar), so it is
# rasterized first - a diagram's whole point over a generated picture is
# legible text, and it must not become the one artifact a phone cannot see.
def _shrink_for_send(content: bytes, media_type: str) -> tuple[bytes, str]:
    if "svg" in media_type:
        import resvg_py

        content = bytes(
            resvg_py.svg_to_bytes(svg_string=content.decode("utf-8"), zoom=2.0)
        )
        media_type = "image/png"
    if len(content) <= _MAX_OUTBOUND_IMAGE_BYTES:
        return content, media_type
    from io import BytesIO

    from PIL import Image

    with Image.open(BytesIO(content)) as image:
        flattened = image.convert("RGB")
        out = BytesIO()
        flattened.save(out, format="JPEG", quality=85)
    return out.getvalue(), "image/jpeg"


# A phone's camera original can be 48 megapixels; the vision pipeline
# accepts IMAGE_MAX_PIXELS (20MP default) and rejects bigger outright -
# which it did to a real photo question. The browser never hits this
# because its picker downscales; the bridge hands over the original, so
# the worker fits it before upload. Margin under the limit, not at it.
def _fit_for_vision(content: bytes) -> tuple[bytes, str]:
    from io import BytesIO

    from PIL import Image

    ceiling = int(settings.IMAGE_MAX_PIXELS * 0.9)
    with Image.open(BytesIO(content)) as image:
        width, height = image.size
        if width * height <= ceiling:
            return content, "image/jpeg"
        scale = (ceiling / (width * height)) ** 0.5
        resized = image.convert("RGB").resize(
            (max(1, int(width * scale)), max(1, int(height * scale)))
        )
        out = BytesIO()
        resized.save(out, format="JPEG", quality=88)
    return out.getvalue(), "image/jpeg"


# How patiently an attachment fetch waits out iCloud's lazy download:
# attempts x growing backoff covers the seconds a photo needs to land on
# the Mac without stalling the turn for a picture that never will.
# iCloud finishes downloading a photo on the Mac some time after the message
# row appears - a few seconds for one small photo, most of a minute for a
# burst of several large ones. Three tries over nine seconds (the original
# budget) lost three of four photos in one real burst on 2026-08-25; the
# backoff below waits a little over a minute in total before giving up.
_FETCH_ATTEMPTS = 7
_FETCH_RETRY_SECONDS = 3.0
# How many photos one message is answered for. Messages carries every photo
# of a burst on one row; each becomes its own vision turn, in order.
_MAX_PHOTOS_PER_MESSAGE = 4

# One reply can take a while on the local model; the read timeout has to
# outlive a long generation, not a network hiccup.
_CHAT_TIMEOUT_SECONDS = 300.0

# Fixed wording for a failed turn, for the same reason the assembled digest
# greeting is fixed: a model composing an apology afresh would vary it for
# no reason and could vary it into something wrong.
_FAILURE_REPLY = "I hit a problem answering that. Give me a minute and try again."

# A slow turn's one bubble, drawn from a small curated set - the same trick
# terminals use with their whimsical status words. Curated rather than
# model-written because the words carry no facts and a model call would add
# latency to the exact moment the point is masking latency; varied rather
# than fixed because the same canned line on every wait reads like a bot
# and different ones read like somebody typing.
# How often the turn is checked while deciding whether to send a bubble.
_ACK_POLL_SECONDS = 0.25
# Routes whose answer is seconds to minutes away once chosen.
# Weather is two or three lookups plus the reply - six to eight seconds - so
# its line at second three still buys real reassurance.
_SLOW_ROUTES = frozenset(
    ("Web search", "Weather", "New images", "Image edits", "Diagrams", "Presentations", "Past conversations", "Skill")
)

_ACK_REPLIES = (
    "On it — digging in 🔍",
    "Good one, give me a sec 🤔",
    "Looking into that for you 🕵️",
    "One sec — pulling that together ✨",
    "Checking the latest on that 📡",
    "Hmm, let me find out 🧭",
)


@dataclass
class TurnImage:
    """One image artifact a turn produced, fetched for the thread."""

    artifact_id: str
    media_type: str
    data_base64: str | None = None


@dataclass(frozen=True, slots=True)
class TurnResult:
    """What one conversational turn came back with."""

    reply: str
    images: tuple[TurnImage, ...] = field(default=())


class BackendUnavailable(Exception):
    """The backend could not be reached at all - a restart, not a bad turn."""


# Whether an exception from the chat call means "nobody is listening" (park
# and retry) rather than "the turn went wrong" (apologise). A read timeout is
# not unavailability: a slow model is still a model.
def _is_unavailable(exc: Exception) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (502, 503, 504)
    return False


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
        # Redis unreadable is not "start from now". Polling with -1 would tell
        # the bridge to skip everything that arrived during the outage and lose
        # it for good, silently. Skip this tick instead and re-read the cursor
        # next time; a missed poll costs latency, a reset cursor costs messages.
        if cursor is None:
            logger.warning("imessage_chat_cursor_unavailable; skipping this poll")
            return 0
        # What earlier polls could not answer, first: a person who asked
        # during a restart is answered before anyone who asked after it.
        answered_late = await self._retry_parked()
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
        answered = answered_late
        for message in payload.get("messages", []):
            answered += await self._handle_message(message)
        new_cursor = payload.get("cursor")
        if isinstance(new_cursor, int):
            await self._remember_cursor(new_cursor)
        # Bursts judged unfinished that nothing followed: answered once the
        # safety cap has passed, so a person left mid-thought still gets a reply.
        answered += await self._flush_stale_bursts()
        return answered

    # One inbound message, answered or skipped; returns 1 when a reply was
    # delivered. Seen is marked after the delivery attempt, not at read
    # time: a worker killed mid-turn - a deploy landed during a generation,
    # twice in one day - then replays the message on restart instead of
    # burning it. A delivery that failed in code is still marked,
    # deliberately: its failure was logged, and replaying a turn the bridge
    # refused would refuse forever.
    async def _handle_message(self, message: dict) -> int:
        guid = str(message.get("guid") or "")
        text = str(message.get("text") or "").strip()
        reply_to = str(message.get("reply_to") or "")
        attachments = [
            item
            for item in (message.get("attachments") or [])
            if isinstance(item, dict)
            and str(item.get("media_type") or "").startswith("image/")
        ]
        # A photo with no caption is a valid message - the picture is the
        # message - so emptiness only skips a row that carries neither.
        if not guid or not reply_to or (not text and not attachments):
            return 0
        if await self._already_seen(guid):
            return 0
        if message.get("chat_identifier"):
            # A room's message: the bridge already established it was
            # addressed to this account; the worker establishes the room.
            return await self._handle_room_message(message, guid, text, reply_to, attachments)
        user_id = await self._account_for(str(message.get("sender") or ""))
        if user_id is None:
            # A stranger's row must not replay forever; it is finished.
            await self._mark_seen(guid)
            return 0
        # A native reply to one of our image bubbles pins that image as the
        # target, overriding recency - "this one" beats "the latest one"
        # whenever the person says it.
        pinned = await self._artifact_for_bubble(
            str(message.get("reply_to_guid") or "")
        )
        # What the turn is doing, as the backend announces it, so a long
        # wait can be acknowledged with "🔎 Rummaging through the internet…"
        # rather than a random pleasantry.
        status: list[str] = []
        if attachments:
            turn = await self._with_ack(
                self._photo_turn(user_id, text, attachments), reply_to, status
            )
        else:
            # Judged by meaning before a reply: unfinished fragments wait for
            # the rest, a closing "thanks!" gets no reply, and a finished
            # burst is answered as one message.
            burst = await self._collect(user_id, reply_to, guid, text, in_group=False)
            if burst is None:
                return 0
            try:
                turn = await self._with_ack(
                    self._converse(user_id, burst, active_image=pinned, status=status),
                    reply_to,
                    status,
                )
            except BackendUnavailable:
                await self._park(guid, user_id, reply_to, burst, pinned=pinned)
                return 0
        if pinned:
            # Replying to a picture brings it back into view for the turns
            # that follow, exactly as focusing it would.
            await self._remember_image(user_id, pinned)
        answered = 0
        try:
            await self._deliver(reply_to, turn)
            answered = 1
            # A picture the turn generated becomes the thread's
            # picture-in-view, exactly as the web UI marks it active after
            # displaying it. Without this, a real "what is happening in the
            # background?" about a generated image was answered with the
            # agent roster - the only background the model could see.
            if turn.images:
                await self._remember_image(user_id, turn.images[-1].artifact_id)
        except Exception as exc:
            # The reason is the whole diagnosis: a refusal code names the
            # bridge's objection, and a bare warning cost a live incident a
            # round-trip that one line would have answered.
            logger.warning(
                "imessage_chat_reply_failed: %s: %s",
                type(exc).__name__,
                str(exc)[:200],
                extra={"user": user_id},
            )
        await self._mark_seen(guid)
        return answered

    # One message from a group chat. Every participant must be an approved
    # user, or the assistant stays silent in that room and tells the
    # operator once; the room is then provisioned as an account of its own
    # (ADR 0016), the turn runs as the group with the speaker attached, and
    # the reply goes back into the chat.
    async def _handle_room_message(
        self, message: dict, guid: str, text: str, reply_to: str, attachments: list[dict]
    ) -> int:
        chat_guid = str(message.get("chat_guid") or reply_to)
        chat_name = str(message.get("chat_name") or "")
        speaker = await self._account_for(str(message.get("sender") or ""))
        if speaker is None:
            await self._mark_seen(guid)
            return 0
        members: list[str] = []
        strangers = 0
        for participant in message.get("participants") or []:
            account = await self._account_for(str(participant or ""))
            if account is None:
                strangers += 1
            elif account not in members:
                members.append(account)
        if speaker not in members:
            members.append(speaker)
        if strangers:
            await self._alert_operator_about_room(chat_guid, chat_name, strangers)
            await self._mark_seen(guid)
            return 0
        group = await self._group_for(chat_guid, chat_name, tuple(members))
        if group is None:
            # The database, not the room: parked as the message it was and
            # handled again from the start once it answers.
            await self._park(guid, "", reply_to, text, message=message)
            return 0
        if not group.enabled:
            await self._mark_seen(guid)
            return 0
        room = {
            "chat_name": chat_name,
            "speaker_user_id": speaker,
            "members": list(group.members),
            "addressed_by": str(message.get("addressed_by") or ""),
            "assistant_name": str(message.get("assistant_name") or ""),
        }
        pinned = await self._artifact_for_bubble(str(message.get("reply_to_guid") or ""))
        status: list[str] = []
        if attachments:
            turn = await self._with_ack(
                self._photo_turn(group.user_id, text, attachments), reply_to, status
            )
        else:
            burst = await self._collect(group.user_id, reply_to, guid, text, in_group=True, room=room)
            if burst is None:
                return 0
            try:
                turn = await self._with_ack(
                    self._converse(group.user_id, burst, active_image=pinned, status=status, room=room),
                    reply_to,
                    status,
                )
            except BackendUnavailable:
                await self._park(guid, group.user_id, reply_to, burst, pinned=pinned, room=room)
                return 0
        if pinned:
            await self._remember_image(group.user_id, pinned)
        answered = 0
        try:
            await self._deliver(reply_to, turn)
            answered = 1
            if turn.images:
                await self._remember_image(group.user_id, turn.images[-1].artifact_id)
        except Exception as exc:
            logger.warning(
                "imessage_chat_room_reply_failed: %s: %s",
                type(exc).__name__,
                str(exc)[:200],
                extra={"user": group.user_id},
            )
        await self._mark_seen(guid)
        return answered

    # The group account for a chat: provisioned on first contact when every
    # participant is approved, its membership brought in line with the chat
    # on every message after. None when the database cannot be reached.
    async def _group_for(self, chat_guid: str, chat_name: str, members: tuple[str, ...]):
        from dataclasses import replace

        from backend.discovery.addressing import address_digest, normalize_address
        from backend.groups.repository import ConversationGroupRepository

        try:
            async with AsyncSessionLocal() as db:
                repository = ConversationGroupRepository(db)
                group = await repository.by_chat_digest(address_digest(normalize_address(chat_guid)))
                if group is None:
                    group = await repository.provision(normalize_address(chat_guid), chat_name, members)
                    logger.info("imessage_group_provisioned", extra={"user": group.user_id, "members": len(members)})
                elif set(group.members) != set(members):
                    group = replace(group, members=await repository.sync_members(group.user_id, members))
                await repository.touch(group.user_id)
                return group
        except Exception as exc:
            logger.warning(
                "imessage_group_unavailable: %s: %s", type(exc).__name__, str(exc)[:200]
            )
            return None

    # Tell the operator, once a day per room, that the assistant was added
    # to a chat it must stay quiet in. Nothing about the strangers is sent -
    # only that there are some.
    async def _alert_operator_about_room(self, chat_guid: str, chat_name: str, strangers: int) -> None:
        phone = settings.OPERATOR_ALERT_PHONE.strip()
        if not phone:
            return
        from backend.discovery.addressing import address_digest

        key = _ROOM_ALERT_KEY.format(digest=address_digest(chat_guid))
        try:
            if await self.redis.get(key):
                return
            await self.redis.set(key, "1", ex=_ROOM_ALERT_TTL_SECONDS)
        except Exception:
            pass
        title = f"“{chat_name}”" if chat_name else "a group chat"
        people = "one person" if strangers == 1 else f"{strangers} people"
        try:
            await self.invoke_tool(
                settings.DISCOVERY_IMESSAGE_TOOL,
                {
                    "to": phone,
                    "body": (
                        f"I was added to {title}, but {people} in it aren't approved "
                        "users, so I'm staying quiet there until they are."
                    ),
                },
            )
        except Exception:
            logger.warning("imessage_room_alert_failed")

    # What to answer, judged by meaning: the fragments since the last reply
    # as one message when the person has finished and wants an answer; None
    # when they have not finished (kept, answered after the cap) or when
    # what they sent wants no reply. The fragment is marked seen either
    # way - a kept fragment lives in the pending record, not in the cursor.
    async def _collect(
        self,
        user_id: str,
        reply_to: str,
        guid: str,
        text: str,
        *,
        in_group: bool,
        room: dict | None = None,
    ) -> str | None:
        if not settings.IMESSAGE_CHAT_READINESS_ENABLED:
            return text
        pending = await self._pending_add(reply_to, user_id, guid, text, in_group, room)
        fragments = [str(item.get("text") or "") for item in pending.get("fragments") or []]
        verdict = await self._readiness(user_id, reply_to, fragments, in_group)
        oldest = float((pending.get("fragments") or [{}])[0].get("at") or time.time())
        capped = time.time() - oldest >= settings.IMESSAGE_CHAT_BURST_CAP_SECONDS
        if not verdict["complete"] and not capped:
            await self._mark_seen(guid)
            logger.info("imessage_chat_burst_waiting", extra={"fragments": len(fragments)})
            return None
        await self._pending_clear(reply_to)
        if not verdict["needs_reply"]:
            await self._mark_seen(guid)
            logger.info("imessage_chat_no_reply_needed", extra={"fragments": len(fragments)})
            return None
        return "\n".join(fragment for fragment in fragments if fragment)

    # The judgement itself, through the backend so the routing model is
    # asked the way every other judgement is. Fails open to "answer it".
    async def _readiness(self, user_id: str, reply_to: str, fragments: list[str], in_group: bool) -> dict:
        previous = ""
        try:
            previous = await self.redis.get(_LAST_REPLY_KEY.format(to=reply_to)) or ""
        except Exception:
            pass
        token = issue_user_token(user_id, ttl_seconds=120, scopes=["chat"])
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/chat/readiness",
                    json={
                        "user_id": user_id,
                        "fragments": fragments[-12:],
                        "previous_reply": previous[-4000:],
                        "in_group": in_group,
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
                verdict = response.json()
            return {"complete": bool(verdict.get("complete", True)), "needs_reply": bool(verdict.get("needs_reply", True))}
        except Exception as exc:
            logger.warning("imessage_chat_readiness_failed: %s: %s", type(exc).__name__, str(exc)[:200])
            return {"complete": True, "needs_reply": True}

    # Append a fragment to the address's pending burst and return the burst.
    async def _pending_add(
        self, reply_to: str, user_id: str, guid: str, text: str, in_group: bool, room: dict | None
    ) -> dict:
        key = _PENDING_KEY.format(to=reply_to)
        record: dict = {"user_id": user_id, "reply_to": reply_to, "in_group": in_group, "room": room, "fragments": []}
        try:
            stored = await self.redis.get(key)
            if stored:
                record = json.loads(stored)
        except Exception:
            pass
        record["fragments"] = [*(record.get("fragments") or []), {"guid": guid, "text": text, "at": time.time()}][-12:]
        record["room"] = room or record.get("room")
        try:
            await self.redis.set(key, json.dumps(record), ex=_PENDING_TTL_SECONDS)
            await self.redis.sadd(_PENDING_INDEX_KEY, reply_to)
        except Exception:
            pass
        return record

    async def _pending_clear(self, reply_to: str) -> None:
        try:
            await self.redis.delete(_PENDING_KEY.format(to=reply_to))
            await self.redis.srem(_PENDING_INDEX_KEY, reply_to)
        except Exception:
            pass

    # Bursts whose oldest fragment has passed the safety cap, answered now
    # as one message each. Runs every poll; a quiet bridge finds nothing.
    async def _flush_stale_bursts(self) -> int:
        try:
            addresses = await self.redis.smembers(_PENDING_INDEX_KEY)
        except Exception:
            return 0
        answered = 0
        for reply_to in addresses or ():
            try:
                stored = await self.redis.get(_PENDING_KEY.format(to=reply_to))
            except Exception:
                continue
            if not stored:
                await self._pending_clear(reply_to)
                continue
            record = json.loads(stored)
            fragments = record.get("fragments") or []
            if not fragments:
                await self._pending_clear(reply_to)
                continue
            if time.time() - float(fragments[0].get("at") or 0) < settings.IMESSAGE_CHAT_BURST_CAP_SECONDS:
                continue
            await self._pending_clear(reply_to)
            text = "\n".join(str(item.get("text") or "") for item in fragments)
            user_id = str(record.get("user_id") or "")
            room = record.get("room") if record.get("in_group") else None
            status: list[str] = []
            turn = await self._with_ack(
                self._converse(user_id, text, status=status, room=room), reply_to, status
            )
            try:
                await self._deliver(reply_to, turn)
                answered += 1
            except Exception as exc:
                logger.warning("imessage_chat_burst_reply_failed: %s: %s", type(exc).__name__, str(exc)[:200])
        return answered

    # Park one turn (or, before a room could be resolved, one message) for
    # retry. Not marked seen: the guid stays open until it is answered or
    # given up on. Re-parking a guid replaces its record and keeps its clock.
    async def _park(
        self,
        guid: str,
        user_id: str,
        reply_to: str,
        text: str,
        *,
        pinned: str | None = None,
        room: dict | None = None,
        message: dict | None = None,
        previous: dict | None = None,
    ) -> None:
        records = await self._parked()
        previous = previous or next((item for item in records if item.get("guid") == guid), None)
        record = {
            "guid": guid,
            "user_id": user_id,
            "reply_to": reply_to,
            "text": text,
            "pinned": pinned,
            "room": room,
            "message": message,
            "since": float(previous.get("since") or time.time()) if previous else time.time(),
            "attempts": int(previous.get("attempts") or 0) + 1 if previous else 1,
            "noticed": bool(previous.get("noticed")) if previous else False,
        }
        records = [item for item in records if item.get("guid") != guid] + [record]
        await self._save_parked(records)
        logger.warning(
            "imessage_chat_parked", extra={"guid": guid[:12], "attempts": record["attempts"]}
        )

    # Every parked record, oldest first; empty when Redis cannot be read.
    async def _parked(self) -> list[dict]:
        try:
            stored = await self.redis.get(_PARKED_KEY)
        except Exception:
            return []
        if not stored:
            return []
        try:
            records = json.loads(stored)
        except ValueError:
            return []
        return [item for item in records if isinstance(item, dict)]

    async def _save_parked(self, records: list[dict]) -> None:
        try:
            if records:
                await self.redis.set(_PARKED_KEY, json.dumps(records), ex=_PARKED_TTL_SECONDS)
            else:
                await self.redis.delete(_PARKED_KEY)
        except Exception:
            return

    # Retry what is parked: answer it if the backend is back, give up with the
    # apology once the window closes, and after the first minute say once
    # that the answer is coming. Returns how many were answered.
    async def _retry_parked(self) -> int:
        records = await self._parked()
        if not records:
            return 0
        answered = 0
        window = settings.IMESSAGE_CHAT_RETRY_MINUTES * 60
        for record in list(records):
            guid = str(record.get("guid") or "")
            reply_to = str(record.get("reply_to") or "")
            age = time.time() - float(record.get("since") or time.time())
            # Taken off the list before the attempt; a failure parks it again
            # with its clock and count intact.
            await self._save_parked([item for item in await self._parked() if item.get("guid") != guid])
            if age > window:
                try:
                    await self._deliver(reply_to, TurnResult(_FAILURE_REPLY, ()))
                except Exception:
                    logger.warning("imessage_chat_parked_apology_failed")
                await self._mark_seen(guid)
                logger.warning("imessage_chat_parked_given_up", extra={"guid": guid[:12]})
                continue
            if record.get("message"):
                # Parked before the room could be resolved: the whole path again.
                answered += await self._handle_message(dict(record["message"]))
                continue
            status: list[str] = []
            try:
                turn = await self._with_ack(
                    self._converse(
                        str(record.get("user_id") or ""),
                        str(record.get("text") or ""),
                        active_image=record.get("pinned"),
                        status=status,
                        room=record.get("room"),
                    ),
                    reply_to,
                    status,
                )
            except BackendUnavailable:
                # Its clock and count carry over: the record was taken off
                # the list before the attempt.
                await self._park(
                    guid, str(record.get("user_id") or ""), reply_to, str(record.get("text") or ""),
                    pinned=record.get("pinned"), room=record.get("room"), previous=record,
                )
                if age > settings.IMESSAGE_CHAT_RETRY_NOTICE_SECONDS and not record.get("noticed"):
                    await self._notice_parked(guid, reply_to)
                continue
            try:
                await self._deliver(reply_to, turn)
                answered += 1
            except Exception as exc:
                logger.warning("imessage_chat_parked_reply_failed: %s: %s", type(exc).__name__, str(exc)[:200])
            await self._mark_seen(guid)
        return answered

    # One fixed bubble, once per parked turn, so a person is not left
    # wondering whether the message was seen.
    async def _notice_parked(self, guid: str, reply_to: str) -> None:
        try:
            await self.invoke_tool(settings.DISCOVERY_IMESSAGE_TOOL, {"to": reply_to, "body": _PARKED_NOTICE})
        except Exception:
            logger.warning("imessage_chat_parked_notice_failed")
            return
        records = await self._parked()
        for item in records:
            if item.get("guid") == guid:
                item["noticed"] = True
        await self._save_parked(records)

    # One turn's answer onto the thread: text flattened at the send boundary
    # and delivered the way a person texts a long thought - a few separate
    # bubbles at a typing pace - then any picture the turn made, as a photo
    # after the words that introduce it.
    async def _deliver(self, reply_to: str, turn: "TurnResult") -> None:
        try:
            await self.redis.set(
                _LAST_REPLY_KEY.format(to=reply_to), plain_text(turn.reply)[:4000], ex=_PENDING_TTL_SECONDS
            )
        except Exception:
            pass
        for position, piece in enumerate(bubbles(plain_text(turn.reply))):
            if position:
                await asyncio.sleep(_BUBBLE_PACE_SECONDS)
            await self.invoke_tool(
                settings.DISCOVERY_IMESSAGE_TOOL,
                {"to": reply_to, "body": piece},
            )
        for image in turn.images:
            await asyncio.sleep(_BUBBLE_PACE_SECONDS)
            extension = "jpg" if "jpeg" in image.media_type else "png"
            answer = await self.invoke_tool(
                settings.DISCOVERY_IMESSAGE_TOOL,
                {
                    "to": reply_to,
                    "body": "",
                    "attachment_name": f"{image.artifact_id}.{extension}",
                    "attachment_media_type": image.media_type,
                    "attachment_base64": image.data_base64,
                },
            )
            # Remember which bubble carried which picture, so a native reply
            # to that bubble can pin it later. The bridge answers a message
            # guid on the paths that know it; a plain "sent" stores nothing
            # and the reply-to override simply has nothing to resolve.
            guid = _message_guid(answer)
            if guid:
                await self._remember_bubble(guid, image.artifact_id)

    # The account that subscribed this address, or None. Looked up by the
    # address digest the subscriber table already indexes - no decryption -
    # and only an active, approved subscription counts: an address that was
    # revoked stops being an identity the moment it stops being a recipient.
    async def _account_for(self, sender: str) -> str | None:
        normalized = normalize_address(sender)
        if not normalized:
            return None
        from backend.discovery.addressing import address_digest
        from backend.models.discovery_subscriber import DiscoverySubscriber

        async with AsyncSessionLocal() as db:
            rows = (
                (
                    await db.execute(
                        select(DiscoverySubscriber).where(
                            DiscoverySubscriber.address_digest
                            == address_digest(normalized),
                            DiscoverySubscriber.active.is_(True),
                            DiscoverySubscriber.approved_at.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
        # A number resolving to more than one account is an identity the bridge
        # cannot honour: whose conversation this belongs to would be decided by
        # Postgres row order, which is no decision at all. Drop the message and
        # say so, rather than guessing and routing a stranger's words into
        # whichever account happened to sort first.
        owners = {str(row.user_id) for row in rows}
        if len(owners) > 1:
            logger.warning(
                "iMessage sender resolves to %d accounts; dropping the message "
                "rather than guessing which it belongs to",
                len(owners),
            )
            return None
        return str(rows[0].user_id) if rows else None

    # Any turn, with one acknowledgment when it runs long. The ack is
    # best-effort - a failure to send it must not cost the real answer -
    # and fires at most once per turn, only after the threshold, so a
    # quick reply stays a single bubble.
    async def _with_ack(
        self, work, reply_to: str, status: list[str] | None = None
    ) -> "TurnResult":
        turn = asyncio.create_task(work)
        started = time.monotonic()
        threshold = settings.IMESSAGE_CHAT_ACK_SECONDS
        body: str | None = None
        # Watch the turn in short slices. The bubble is timed against what is
        # known: a slow route names its own line as soon as the router chose
        # it (the backend's action event, a few seconds in), and a turn with
        # no such route gets the generic line only once it has run past the
        # threshold - a quick reply stays one bubble either way.
        while True:
            remaining = threshold - (time.monotonic() - started)
            done, _ = await asyncio.wait({turn}, timeout=max(0.01, min(_ACK_POLL_SECONDS, remaining)))
            if done:
                break
            if status:
                body = status[-1]
                break
            if time.monotonic() - started >= threshold:
                body = random.choice(_ACK_REPLIES)
                break
        if body is not None:
            try:
                await self.invoke_tool(
                    settings.DISCOVERY_IMESSAGE_TOOL,
                    {"to": reply_to, "body": body},
                )
            except Exception:
                logger.warning("imessage_chat_ack_failed", extra={"to": reply_to})
        return await turn

    # One turn through the same endpoint the browser uses. The reply is the
    # concatenated deltas plus any image artifacts the turn produced; the
    # conversation id from the stream's start event is remembered so the
    # next text continues the same thread.
    async def _converse(
        self,
        user_id: str,
        text: str,
        active_image: str | None = None,
        status: list[str] | None = None,
        room: dict | None = None,
    ) -> "TurnResult":
        token = issue_user_token(user_id, ttl_seconds=600, scopes=["chat", "vision"])
        body: dict[str, object] = {
            "user_id": user_id,
            "query": text,
            # Tells the reply model where its words land, so it writes like
            # a text instead of a web page. The flattener downstream stays:
            # writing for the medium and repairing for it are both wanted.
            # A room says so, and who is in it and who is speaking.
            "metadata": (
                {"channel": "imessage_group", "group": dict(room)} if room else {"channel": "imessage"}
            ),
        }
        body.update(await self._thread_state(user_id, pinned=active_image))
        collected: list[str] = []
        images: list[TurnImage] = []
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
                        await self._consume_event(
                            user_id,
                            event,
                            _loads(line[6:]),
                            collected,
                            images,
                            status,
                        )
            # Fetched inside the turn while the token is fresh, through the
            # same owned-artifact endpoint the browser uses. A diagram
            # arrives already rendered and is not re-fetched - it has no
            # stored content to fetch.
            for image in images:
                if image.data_base64 is not None:
                    continue
                fetched = await self._fetch_artifact(user_id, image.artifact_id, token)
                if fetched is not None:
                    image.data_base64, image.media_type = fetched
        except Exception as exc:
            # The reason rides the warning; a bare line cost a live incident
            # a diagnosis round-trip once already.
            logger.warning(
                "imessage_chat_turn_failed: %s: %s",
                type(exc).__name__,
                str(exc)[:200],
                extra={"user": user_id},
            )
            if _is_unavailable(exc):
                # Nobody answered at all: the caller parks the turn and asks
                # again next poll rather than apologising for a restart.
                raise BackendUnavailable(str(exc)[:200]) from exc
            return TurnResult(_FAILURE_REPLY, ())
        reply = "".join(collected).strip()
        carried = tuple(image for image in images if image.data_base64)
        return TurnResult(reply or _FAILURE_REPLY, carried)

    # What the thread already established: its conversation id and, when a
    # photo was sent recently, the picture-in-view a follow-up text edits.
    async def _thread_state(
        self, user_id: str, pinned: str | None = None
    ) -> dict[str, str]:
        state: dict[str, str] = {}
        stored = await self._stored_conversation(user_id)
        if stored:
            state["conversation_id"] = stored
        # An explicit pin - a native reply to a specific image bubble - beats
        # whatever recency had in view.
        active_image = pinned or await self._stored_image(user_id)
        if active_image:
            state["active_image_artifact_id"] = active_image
        return state

    # Photos from the phone become vision turns: each attachment is fetched
    # from the bridge, run through the same /vision/analyze path a browser
    # upload takes, and the analyses are the reply - one bubble per photo when
    # several came at once, numbered so the reader can tell which is which.
    # The last artifact is remembered as the thread's picture-in-view, so
    # "make it brighter" in the next text edits it exactly as it would in the
    # web UI. A burst of photos used to be answered for its first photo only,
    # silently: Messages puts every photo of a burst on one row.
    async def _photo_turn(
        self, user_id: str, caption: str, attachments: list[dict]
    ) -> "TurnResult":
        conversation = await self._stored_conversation(user_id) or str(uuid.uuid4())
        photos = attachments[:_MAX_PHOTOS_PER_MESSAGE]
        replies: list[str] = []
        remembered = ""
        for position, attachment in enumerate(photos, start=1):
            reply, artifact_id = await self._analyze_photo(
                user_id, caption, attachment, conversation
            )
            if artifact_id:
                remembered = artifact_id
            replies.append(f"Picture {position}: {reply}" if len(photos) > 1 else reply)
        if len(attachments) > len(photos):
            replies.append(
                f"I looked at the first {len(photos)} - send the rest separately "
                "if you want those described too."
            )
        if remembered:
            await self._remember_conversation(user_id, conversation)
            await self._remember_image(user_id, remembered)
        return TurnResult("\n\n".join(replies) or _FAILURE_REPLY, ())

    # One photo's answer and the artifact it became, or a sentence saying why
    # not. Returned as words rather than raised so a burst with one bad photo
    # still answers the others.
    async def _analyze_photo(
        self, user_id: str, caption: str, attachment: dict, conversation: str
    ) -> tuple[str, str]:
        fetched = await self._fetch_inbound_attachment(
            str(attachment.get("attachment_id") or "")
        )
        if fetched is None:
            # Most often the photo is still on its way down from iCloud - the
            # bridge cannot yet see the file - and the honest reply says so
            # rather than blaming the picture.
            return (
                "That photo hasn't finished downloading on my end yet - "
                "send it again in a minute?",
                "",
            )
        media_type, name, data = fetched
        try:
            content, media_type = await asyncio.to_thread(
                _fit_for_vision, base64.b64decode(data)
            )
        except Exception:
            logger.warning("imessage_chat_photo_unreadable", extra={"user": user_id})
            return "I couldn't open that picture. Mind sending it again?", ""
        token = issue_user_token(user_id, ttl_seconds=600, scopes=["chat", "vision"])
        # A captionless photo still needs the vision call an instruction;
        # fixed wording, like every functional sentence the app writes.
        prompt = caption or "Describe what you see in this picture, briefly."
        try:
            async with httpx.AsyncClient(timeout=_CHAT_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/vision/analyze",
                    data={
                        "user_id": user_id,
                        "conversation_id": conversation,
                        "prompt": prompt,
                        # The bubble this turn sends is the only answer its
                        # reader will ever see - there is no artifact panel
                        # to look at again - so the reasoned answer must be
                        # the one that comes back, not the quick pass the
                        # browser shows while reasoning lands behind it.
                        "defer_reasoning": "false",
                    },
                    files={"image": (name, content, media_type)},
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
                result = response.json()
        except Exception as exc:
            # The reason rides the warning: a bare line once hid that the
            # backend was simply restarting under a deploy.
            logger.warning(
                "imessage_chat_photo_turn_failed: %s: %s",
                type(exc).__name__,
                str(exc)[:200],
                extra={"user": user_id},
            )
            return _FAILURE_REPLY, ""
        artifact_id = str((result.get("artifact") or {}).get("id") or "")
        reply = str(result.get("analysis") or "").strip()
        return reply or _FAILURE_REPLY, artifact_id

    # One inbound attachment's bytes. Messages lazy-downloads attachments
    # from iCloud, so a fetch racing the download answers not_found for a
    # file that will exist seconds later - and the bridge deliberately makes
    # that indistinguishable from never-existed as a probe defense. An id
    # from a listing we just read is trustworthy, so not_found alone earns a
    # short backoff and retry; every other refusal is final.
    async def _fetch_inbound_attachment(
        self, attachment_id: str
    ) -> tuple[str, str, str] | None:
        if not attachment_id:
            return None
        for attempt in range(_FETCH_ATTEMPTS):
            outcome = await self._read_attachment_once(attachment_id)
            if outcome != "not_found":
                return outcome if isinstance(outcome, tuple) else None
            if attempt + 1 < _FETCH_ATTEMPTS:
                await asyncio.sleep(_FETCH_RETRY_SECONDS * (attempt + 1))
        logger.warning("imessage_chat_attachment_never_arrived")
        return None

    # One call over a direct MCP session rather than the invocation service:
    # MCP_MAX_RESULT_CHARS ceilings at 60K by design to protect model
    # contexts, and attachment payloads are plumbing for this worker, not
    # text for a model. The session still comes from the same server config
    # - token headers, moved-bridge rediscovery and all. Returns the fetched
    # tuple, the literal string "not_found" (retryable), or None (final).
    async def _read_attachment_once(
        self, attachment_id: str
    ) -> "tuple[str, str, str] | str | None":
        from backend.mcp.config import parse_server_configs
        from backend.mcp.session import open_session

        server = next(
            (
                config
                for config in parse_server_configs(settings.MCP_SERVERS_JSON)
                if config.server_id == settings.DISCOVERY_IMESSAGE_SERVER_ID
            ),
            None,
        )
        if server is None:
            return None
        try:
            async with open_session(server, timeout_seconds=60) as session:
                result = await session.call_tool(
                    "read_attachment", {"attachment_id": attachment_id}
                )
            text = "".join(getattr(item, "text", "") for item in (result.content or []))
            payload = json.loads(text)
            if payload.get("error") == "not_found":
                return "not_found"
            if payload.get("error"):
                logger.warning(
                    "imessage_chat_attachment_refused",
                    extra={"reason": str(payload["error"])},
                )
                return None
            return (
                str(payload["media_type"]),
                str(payload.get("name") or "photo.jpeg"),
                str(payload["data_base64"]),
            )
        except Exception:
            logger.warning("imessage_chat_attachment_fetch_failed")
            return None

    # The bubble ledger: which artifact a sent image bubble carried, and the
    # lookup a native reply resolves through. Both fail soft - no guid, no
    # entry, or Redis down all mean the reply-to override quietly does not
    # apply and recency stands.
    async def _remember_bubble(self, guid: str, artifact_id: str) -> None:
        key = _bare_guid(guid)
        if not key:
            return
        try:
            await self.redis.set(
                _BUBBLE_KEY.format(guid=key), artifact_id, ex=_BUBBLE_TTL_SECONDS
            )
        except Exception:
            return

    async def _artifact_for_bubble(self, guid: str) -> str | None:
        key = _bare_guid(guid)
        if not key:
            return None
        try:
            return await self.redis.get(_BUBBLE_KEY.format(guid=key))
        except Exception:
            return None

    # The thread's picture-in-view, remembered on the same clock as the
    # conversation itself: a follow-up text edits the photo they just sent,
    # and after the lull both start fresh together.
    async def _remember_image(self, user_id: str, artifact_id: str) -> None:
        try:
            await self.redis.set(
                _IMAGE_KEY.format(user_id=user_id),
                artifact_id,
                ex=self._image_idle_seconds(),
            )
        except Exception:
            return

    @staticmethod
    def _image_idle_seconds() -> int:
        return int(settings.IMESSAGE_CHAT_IMAGE_IDLE_MINUTES * 60)

    # Read without renewing: only an image EVENT (sent, uploaded, pinned)
    # restarts the window. Renewing on read kept an eight-hour-old photo in
    # view through a whole conversation about something else, and a bare
    # "yes" was answered as if it confirmed that old picture's question.
    async def _stored_image(self, user_id: str) -> str | None:
        try:
            return await self.redis.get(_IMAGE_KEY.format(user_id=user_id))
        except Exception:
            return None

    # One SSE event into the turn's accumulators. A diagram stores mermaid
    # source and no rendered bytes anywhere - the browser renders it
    # client-side, and a bubble has no browser - so it is rendered here; a
    # source outside the renderer's subset costs the picture, never the
    # reply.
    async def _consume_event(
        self,
        user_id: str,
        event: str,
        data: dict,
        collected: list,
        images: list,
        status: list | None = None,
    ) -> None:
        if event == "start" and data.get("conversation_id"):
            await self._remember_conversation(user_id, str(data["conversation_id"]))
        elif event == "action" and status is not None:
            waiting = str(data.get("waiting") or "").strip()
            # Only a route that will take a while earns an immediate bubble;
            # a reminder or a schedule change answers within a second or two
            # and a bubble before it would arrive on top of the answer.
            if waiting and str(data.get("label") or "") in _SLOW_ROUTES:
                status.append(waiting)
        elif event == "delta" and isinstance(data.get("content"), str):
            collected.append(data["content"])
        elif event == "artifact_ready" and data.get("kind") == "diagram":
            rendered = await self._render_diagram(data)
            if rendered is not None:
                images.append(rendered)
        elif event == "artifact_ready" and str(data.get("mime_type") or "").startswith(
            "image/"
        ):
            images.append(
                TurnImage(
                    artifact_id=str(data.get("id") or ""),
                    media_type=str(data["mime_type"]),
                )
            )

    # A diagram artifact rendered to a PNG the thread can carry, or None
    # when the source is outside the renderer's flowchart subset - in which
    # case the words still arrive and the diagram stays viewable on the web.
    async def _render_diagram(self, data: dict) -> "TurnImage | None":
        from backend.workers.mermaid_render import render_flowchart_png

        source = str(data.get("source") or "")
        if not source:
            return None
        try:
            png = await asyncio.to_thread(render_flowchart_png, source)
        except Exception as exc:
            logger.warning(
                "imessage_chat_diagram_render_failed: %s: %s",
                type(exc).__name__,
                str(exc)[:150],
            )
            return None
        return TurnImage(
            artifact_id=str(data.get("id") or "diagram"),
            media_type="image/png",
            data_base64=base64.b64encode(png).decode("ascii"),
        )

    # One owned artifact's bytes as base64 with its final media type, or
    # None - a picture that cannot be fetched costs the attachment, never
    # the reply around it. An image over the bridge's size cap is
    # re-encoded as JPEG rather than refused: a detailed generated PNG can
    # pass 5MB, a phone screen does not miss the alpha channel, and the
    # cap itself stays where it is - it bounds what a compromised backend
    # could pump through the Mac, which is not a limit to negotiate with.
    async def _fetch_artifact(
        self, user_id: str, artifact_id: str, token: str
    ) -> tuple[str, str] | None:
        if not artifact_id:
            return None
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/artifacts/{user_id}/{artifact_id}/content",
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
                media_type = str(response.headers.get("content-type") or "image/png")
                content, media_type = await asyncio.to_thread(
                    _shrink_for_send, response.content, media_type
                )
                return base64.b64encode(content).decode("ascii"), media_type
        except Exception:
            logger.warning(
                "imessage_chat_artifact_fetch_failed",
                extra={"artifact": artifact_id},
            )
            return None

    # The stored cursor, -1 when there is none (a first run legitimately starts
    # from now), or None when Redis itself could not be read - which the caller
    # must treat as "do not poll", not as "start from now".
    async def _cursor(self) -> int | None:
        try:
            raw = await self.redis.get(_CURSOR_KEY)
        except Exception:
            return None
        return int(raw) if raw is not None else -1

    async def _remember_cursor(self, cursor: int) -> None:
        try:
            await self.redis.set(_CURSOR_KEY, str(cursor))
        except Exception:
            return

    # Dedup in two halves around the turn: checked before work begins,
    # marked only after the delivery attempt, so a worker killed mid-turn
    # replays the message on restart. With Redis down this admits repeats,
    # which the cursor's strict ordering already makes rare; answering a
    # text twice beats never answering under a degraded cache.
    async def _already_seen(self, guid: str) -> bool:
        try:
            return bool(await self.redis.get(_SEEN_KEY.format(guid=guid)))
        except Exception:
            return False

    async def _mark_seen(self, guid: str) -> None:
        try:
            await self.redis.set(_SEEN_KEY.format(guid=guid), "1", ex=_SEEN_TTL_SECONDS)
        except Exception:
            return

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


# How a long reply is paced and portioned. A short answer stays one bubble;
# past the threshold it splits at paragraph boundaries into a few messages,
# because that is how a person texts a long thought - and each bubble is a
# thing a thumb can react to. The threshold was 420 and a 546-character
# reply arrived as two near-equal halves that each read like a complete
# answer - "it answered twice". A phone bubble carries 600-800 characters
# comfortably, so only a genuinely long reply is portioned now.
_BUBBLE_THRESHOLD_CHARS = 800
_BUBBLE_TARGET_CHARS = 600
_MAX_BUBBLES = 4
_BUBBLE_PACE_SECONDS = 1.2


def bubbles(reply: str) -> list[str]:
    text = reply.strip()
    if len(text) <= _BUBBLE_THRESHOLD_CHARS:
        return [text] if text else []
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    pieces: list[str] = []
    for paragraph in paragraphs:
        if pieces and len(pieces[-1]) + len(paragraph) + 2 <= _BUBBLE_TARGET_CHARS:
            pieces[-1] = f"{pieces[-1]}\n\n{paragraph}"
        else:
            pieces.append(paragraph)
    # The cap is a floor on dignity, not a truncation: everything past it
    # rides in the final bubble rather than being dropped.
    if len(pieces) > _MAX_BUBBLES:
        pieces[_MAX_BUBBLES - 1 :] = ["\n\n".join(pieces[_MAX_BUBBLES - 1 :])]
    return pieces


def _loads(text: str) -> dict:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except ValueError:
        return {}


# The bare message guid, stripped of the two prefixes iMessage wraps it in.
#
# The same message reaches the ledger written two ways: the send-answer carries
# a service prefix ("iMessage;-;<guid>") and a native reply's originator can
# carry an association prefix ("p:0/<guid>"). Keying on either verbatim means a
# reply silently never resolves to the bubble it answers. Reduce both to the
# guid the bridge itself matches on everywhere else.
def _bare_guid(guid: str) -> str:
    return (guid or "").split(";")[-1].split("/")[-1].strip()


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
    import time

    from backend.core.dependencies import _invoke_discovery_tool

    worker = IMessageChatWorker(_invoke_discovery_tool)
    logger.info("imessage_chat_started")
    # -inf, not 0: at start-up nothing has been answered, so the first idle_for
    # is enormous and the loop begins on the idle cadence rather than treating
    # boot as recent activity.
    last_active = float("-inf")
    while True:
        try:
            answered = await worker.tick()
            if answered:
                last_active = time.monotonic()
                logger.info("imessage_chat_answered", extra={"count": answered})
        except Exception:
            logger.exception("imessage_chat_tick_failed")
        await asyncio.sleep(
            _poll_delay(
                time.monotonic() - last_active,
                fast=settings.IMESSAGE_CHAT_ACTIVE_POLL_SECONDS,
                slow=settings.IMESSAGE_CHAT_POLL_SECONDS,
                window=settings.IMESSAGE_CHAT_ACTIVE_WINDOW_SECONDS,
            )
        )


# How long to wait before the next poll: the fast cadence for `window` seconds
# after the last answered message, the idle cadence otherwise. A back-and-forth
# stays responsive; a quiet bridge is left alone.
def _poll_delay(idle_for: float, *, fast: float, slow: float, window: float) -> float:
    return fast if idle_for < window else slow
