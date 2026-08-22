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
_SEEN_TTL_SECONDS = 3 * 24 * 3600
_BUBBLE_TTL_SECONDS = 7 * 24 * 3600

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
_FETCH_ATTEMPTS = 3
_FETCH_RETRY_SECONDS = 3.0

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
            answered += await self._handle_message(message)
        new_cursor = payload.get("cursor")
        if isinstance(new_cursor, int):
            await self._remember_cursor(new_cursor)
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
        if attachments:
            turn = await self._with_ack(
                self._photo_turn(user_id, text, attachments), reply_to
            )
        else:
            turn = await self._with_ack(
                self._converse(user_id, text, active_image=pinned), reply_to
            )
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

    # One turn's answer onto the thread: text flattened at the send boundary
    # and delivered the way a person texts a long thought - a few separate
    # bubbles at a typing pace - then any picture the turn made, as a photo
    # after the words that introduce it.
    async def _deliver(self, reply_to: str, turn: "TurnResult") -> None:
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

    # Any turn, with one acknowledgment when it runs long. The ack is
    # best-effort - a failure to send it must not cost the real answer -
    # and fires at most once per turn, only after the threshold, so a
    # quick reply stays a single bubble.
    async def _with_ack(self, work, reply_to: str) -> "TurnResult":
        turn = asyncio.create_task(work)
        done, _ = await asyncio.wait(
            {turn}, timeout=settings.IMESSAGE_CHAT_ACK_SECONDS
        )
        if not done:
            try:
                await self.invoke_tool(
                    settings.DISCOVERY_IMESSAGE_TOOL,
                    {"to": reply_to, "body": random.choice(_ACK_REPLIES)},
                )
            except Exception:
                logger.warning("imessage_chat_ack_failed", extra={"to": reply_to})
        return await turn

    # One turn through the same endpoint the browser uses. The reply is the
    # concatenated deltas plus any image artifacts the turn produced; the
    # conversation id from the stream's start event is remembered so the
    # next text continues the same thread.
    async def _converse(
        self, user_id: str, text: str, active_image: str | None = None
    ) -> "TurnResult":
        token = issue_user_token(user_id, ttl_seconds=600, scopes=["chat", "vision"])
        body: dict[str, object] = {
            "user_id": user_id,
            "query": text,
            # Tells the reply model where its words land, so it writes like
            # a text instead of a web page. The flattener downstream stays:
            # writing for the medium and repairing for it are both wanted.
            "metadata": {"channel": "imessage"},
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
                        data = _loads(line[6:])
                        if event == "start" and data.get("conversation_id"):
                            await self._remember_conversation(
                                user_id, str(data["conversation_id"])
                            )
                        elif event == "delta" and isinstance(
                            data.get("content"), str
                        ):
                            collected.append(data["content"])
                        elif event == "artifact_ready" and str(
                            data.get("mime_type") or ""
                        ).startswith("image/"):
                            images.append(
                                TurnImage(
                                    artifact_id=str(data.get("id") or ""),
                                    media_type=str(data["mime_type"]),
                                )
                            )
            # Fetched inside the turn while the token is fresh, through the
            # same owned-artifact endpoint the browser uses.
            for image in images:
                fetched = await self._fetch_artifact(
                    user_id, image.artifact_id, token
                )
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

    # A photo from the phone becomes a vision turn: the attachment is
    # fetched from the bridge, run through the same /vision/analyze path a
    # browser upload takes, and the analysis is the reply. The resulting
    # artifact is remembered as the thread's picture-in-view, so "make it
    # brighter" in the next text edits it exactly as it would in the web UI.
    async def _photo_turn(
        self, user_id: str, caption: str, attachments: list[dict]
    ) -> "TurnResult":
        fetched = await self._fetch_inbound_attachment(
            str(attachments[0].get("attachment_id") or "")
        )
        if fetched is None:
            return TurnResult(
                "I couldn't open that picture. Mind sending it again?", ()
            )
        media_type, name, data = fetched
        try:
            content, media_type = await asyncio.to_thread(
                _fit_for_vision, base64.b64decode(data)
            )
        except Exception:
            logger.warning("imessage_chat_photo_unreadable", extra={"user": user_id})
            return TurnResult(
                "I couldn't open that picture. Mind sending it again?", ()
            )
        token = issue_user_token(user_id, ttl_seconds=600, scopes=["chat", "vision"])
        conversation = await self._stored_conversation(user_id) or str(uuid.uuid4())
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
        except Exception:
            logger.warning("imessage_chat_photo_turn_failed", extra={"user": user_id})
            return TurnResult(_FAILURE_REPLY, ())
        await self._remember_conversation(user_id, conversation)
        artifact_id = str((result.get("artifact") or {}).get("id") or "")
        if artifact_id:
            await self._remember_image(user_id, artifact_id)
        reply = str(result.get("analysis") or "").strip()
        return TurnResult(reply or _FAILURE_REPLY, ())

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
            text = "".join(
                getattr(item, "text", "") for item in (result.content or [])
            )
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
        try:
            await self.redis.set(
                _BUBBLE_KEY.format(guid=guid), artifact_id, ex=_BUBBLE_TTL_SECONDS
            )
        except Exception:
            return

    async def _artifact_for_bubble(self, guid: str) -> str | None:
        if not guid:
            return None
        try:
            return await self.redis.get(_BUBBLE_KEY.format(guid=guid))
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
                ex=self._idle_seconds(),
            )
        except Exception:
            return

    async def _stored_image(self, user_id: str) -> str | None:
        try:
            return await self.redis.get(_IMAGE_KEY.format(user_id=user_id))
        except Exception:
            return None

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
                    f"{self.base_url}/api/v1/artifacts/{user_id}/"
                    f"{artifact_id}/content",
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
                media_type = str(
                    response.headers.get("content-type") or "image/png"
                )
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
            await self.redis.set(
                _SEEN_KEY.format(guid=guid), "1", ex=_SEEN_TTL_SECONDS
            )
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
# thing a thumb can react to.
_BUBBLE_THRESHOLD_CHARS = 420
_BUBBLE_TARGET_CHARS = 400
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
