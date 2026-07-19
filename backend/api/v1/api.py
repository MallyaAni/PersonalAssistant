import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.api.v1.agent_memory import router as agent_memory_router
from backend.api.v1.artifacts import router as artifacts_router
from backend.api.v1.conversations import router as conversations_router
from backend.api.v1.images import router as images_router
from backend.api.v1.memory import router as memory_router
from backend.api.v1.tool_memory import router as tool_memory_router
from backend.api.v1.vision import router as vision_router
from backend.core.auth import (
    IdentityDependency,
    authorize_user,
)
from backend.core.dependencies import DependencyConversationService
from backend.models.schemas import ChatRequest, ChatStreamEvent

logger = logging.getLogger(__name__)

router = APIRouter()

# Explicitly define the name expected by main.py
api_router = router
router.include_router(tool_memory_router)
router.include_router(agent_memory_router)
router.include_router(memory_router)
router.include_router(artifacts_router)
router.include_router(conversations_router)
router.include_router(images_router)
router.include_router(vision_router)


@router.get("/")
async def root() -> dict[str, str]:
    return {"message": "Welcome to AniOS API v1"}


@router.post("/chat")
async def chat(
    body: ChatRequest,
    service: DependencyConversationService,
    identity: IdentityDependency,
) -> StreamingResponse:
    authorize_user(body.user_id, identity)
    return StreamingResponse(
        _encode_sse(
            service.process_request(
                body.user_id,
                body.query,
                str(body.conversation_id) if body.conversation_id else None,
                body.metadata,
            )
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _encode_sse(
    events: AsyncGenerator[ChatStreamEvent, None],
) -> AsyncGenerator[str, None]:
    try:
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
