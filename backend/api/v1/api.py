import asyncio
import contextvars
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import suppress
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.api.v1.admin import router as admin_router
from backend.api.v1.agent_memory import router as agent_memory_router
from backend.api.v1.agents import router as agents_router
from backend.api.v1.artifacts import router as artifacts_router
from backend.api.v1.auth import router as auth_router
from backend.api.v1.automations import router as automations_router
from backend.api.v1.conversations import router as conversations_router
from backend.api.v1.discovery import feed_router as discovery_feed_router
from backend.api.v1.discovery import router as discovery_router
from backend.api.v1.images import router as images_router
from backend.api.v1.memory import router as memory_router
from backend.api.v1.presentations import router as presentations_router
from backend.api.v1.tool_memory import router as tool_memory_router
from backend.api.v1.tools import router as tools_router
from backend.api.v1.vision import router as vision_router
from backend.core.auth import (
    SCOPE_CHAT,
    IdentityDependency,
    authorize_scope,
    authorize_user,
)
from backend.core.dependencies import DependencyConversationService, ModelGateDependency
from backend.models.schemas import ChatRequest, ChatStreamEvent, ObserveRequest, ReadinessRequest

logger = logging.getLogger(__name__)

router = APIRouter()

# Explicitly define the name expected by main.py
api_router = router
router.include_router(auth_router)
router.include_router(tool_memory_router)
router.include_router(agent_memory_router)
router.include_router(memory_router)
router.include_router(artifacts_router)
router.include_router(conversations_router)
router.include_router(images_router)
router.include_router(vision_router)
router.include_router(tools_router)
router.include_router(presentations_router)
router.include_router(admin_router)
router.include_router(agents_router)
router.include_router(discovery_router)
router.include_router(discovery_feed_router)
router.include_router(automations_router)


@router.get("/")
async def root() -> dict[str, str]:
    return {"message": "Welcome to AniOS API v1"}


@router.post("/chat")
async def chat(
    body: ChatRequest,
    service: DependencyConversationService,
    model_gate: ModelGateDependency,
    identity: IdentityDependency,
) -> StreamingResponse:
    authorize_user(body.user_id, identity)
    authorize_scope(identity, SCOPE_CHAT)
    frames = _encode_sse(
        service.process_request(
            body.user_id,
            body.query,
            str(body.conversation_id) if body.conversation_id else None,
            body.metadata,
            **(
                {"active_image_artifact_id": str(body.active_image_artifact_id)}
                if body.active_image_artifact_id
                else {}
            ),
        ),
        model_gate,
    )
    return StreamingResponse(
        _with_heartbeat(frames),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# A room message the assistant reads without answering (operator's decision,
# 2026-08-28: the whole group is context; only what addresses the assistant
# is answered). Stored as a turn with no reply under the group, and
# classified for memory like any turn, so "we settled on Thai" said between
# two members sticks.
@router.post("/chat/observe")
async def chat_observe(
    body: ObserveRequest,
    service: DependencyConversationService,
    identity: IdentityDependency,
) -> dict[str, Any]:
    authorize_user(body.user_id, identity)
    authorize_scope(identity, SCOPE_CHAT)
    conversation_id = await service.observe(
        body.user_id, body.query, str(body.conversation_id) if body.conversation_id else None, body.metadata
    )
    return {"conversation_id": conversation_id}


# Whether a texting burst is finished and wants an answer, judged by the
# routing model (services/readiness.py). The iMessage worker asks this
# before every reply so "ok so" is not answered and "thanks!" is not either.
@router.post("/chat/readiness")
async def chat_readiness(
    body: ReadinessRequest,
    service: DependencyConversationService,
    identity: IdentityDependency,
) -> dict[str, Any]:
    authorize_user(body.user_id, identity)
    authorize_scope(identity, SCOPE_CHAT)
    verdict = await service.judge_readiness(
        body.previous_reply, list(body.fragments), in_group=body.in_group, addressed_by=body.addressed_by
    )
    return {
        "complete": verdict.complete,
        "needs_reply": verdict.needs_reply,
        "accepts_offer": verdict.accepts_offer,
        "reason": verdict.reason,
    }


async def _encode_sse(
    events: AsyncGenerator[ChatStreamEvent, None],
    model_gate: ModelGateDependency,
) -> AsyncGenerator[str, None]:
    try:
        async with model_gate.interactive():
            async for item in events:
                yield _sse_event(item["event"], item["data"])
    except Exception:
        logger.exception("Chat stream failed")
        yield _sse_event(
            "error",
            {"message": "Unable to complete the chat request."},
        )


def _sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# How long the stream may stay silent before sending a comment to hold the
# connection open. Generating or editing a picture takes one to two minutes
# during which the turn legitimately has nothing to say, and public access is a
# Cloudflare tunnel, which closes a proxied request that has sent nothing for
# roughly a hundred seconds. A real edit that took 116 seconds reached the user
# as "DeepMatter did not respond" while the backend went on to fetch the
# finished image successfully: the work was fine, the connection was gone.
_HEARTBEAT_SECONDS = 15.0

# The event after which the browser expects nothing further.
_TERMINAL_EVENT = "done"


# Keep the connection alive across a long silence.
#
# A line beginning with ":" is an SSE comment. It carries no event and no data,
# so it cannot be mistaken for one; it exists only so that something crosses
# the wire before an intermediary decides nothing ever will.
async def _with_heartbeat(
    frames: AsyncGenerator[str, None],
    interval: float = _HEARTBEAT_SECONDS,
) -> AsyncGenerator[str, None]:
    iterator = frames.__aiter__()
    # Every pull runs as its own task, and a task starts with a *copy* of the
    # context. Pulled with ensure_future, a ContextVar the turn set during one
    # pull - the previous reply for the task picker, the search identity and
    # limit, the events-format flag, the turn trace - was gone by the next,
    # in production only: an in-process test iterates the generator in one
    # task and never sees it (found 2026-08-26 by a throwaway-account check
    # of the saved trace, after every in-process test had passed). One
    # context, shared by every pull, is the whole fix.
    context = contextvars.copy_context()
    loop = asyncio.get_running_loop()

    async def _pull() -> str:
        return await anext(iterator)

    upcoming = loop.create_task(_pull(), context=context)
    # Whether the turn has already said everything it is going to say.
    #
    # The generator keeps running after the terminal event while it persists
    # the turn and updates memory, and heart-beating through that window sent
    # comments *after* `done`. The browser had stopped expecting anything, so a
    # stream closing mid-comment left a partial frame in its buffer and it
    # reported "ended with an incomplete event" on top of a complete answer -
    # visible as a stray error under a good reply, and worst on the long
    # streams an image generates. Nothing needs holding open once the answer
    # has been delivered.
    finished = False
    try:
        while True:
            timeout = None if finished else interval
            done, _still_waiting = await asyncio.wait({upcoming}, timeout=timeout)
            if not done:
                yield ": keepalive\n\n"
                continue
            try:
                frame = upcoming.result()
            except StopAsyncIteration:
                return
            yield frame
            finished = finished or frame.startswith(f"event: {_TERMINAL_EVENT}")
            upcoming = loop.create_task(_pull(), context=context)
    finally:
        # A caller can abandon this generator at any point - a closed browser
        # tab does exactly that - and the outstanding pull has to be cancelled
        # with it rather than left to resolve into nothing.
        upcoming.cancel()
        with suppress(BaseException):
            await upcoming
        await frames.aclose()
