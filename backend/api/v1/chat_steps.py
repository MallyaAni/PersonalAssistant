"""The chat loop, one step at a time, for a run that continues a turn.

Two routes under the person's own authority (`chat` scope, own user id):
*decide* asks the router for the next step given the steps a turn already
took, under the later-step policy for the time left; *apply* carries one
step out through the turn's executor. The run worker in another process
drives them in sequence, recording each step before it runs, so a chat
turn's unfinished work gets the durable run's guarantees without the
worker having to build the assistant.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.core.auth import (
    SCOPE_CHAT,
    IdentityDependency,
    authorize_scope,
    authorize_user,
)
from backend.core.dependencies import DependencyConversationService

router = APIRouter(prefix="/chat/{user_id}/steps", tags=["chat-steps"])


class StepContext(BaseModel):
    """The turn a continuation step belongs to.

    A run is a turn continued in another process, and the executor there has
    no turn context of its own. The run carries the turn's channel, speaker,
    zone and replied-to message, and every step it applies is applied as that
    turn: a group's check-in guard sees the room, a reminder is saved on the
    channel it was asked in, and the change log is scoped to the thread.
    """

    channel: str | None = Field(default=None, max_length=20)
    speaker_user_id: str | None = Field(default=None, max_length=50)
    timezone: str | None = Field(default=None, max_length=60)
    replying_to: str | None = Field(default=None, max_length=300)


class DecideStep(BaseModel):
    query: str = Field(min_length=1, max_length=8_000)
    conversation_id: str | None = None
    lines: list[str] = Field(default_factory=list, max_length=200)
    remaining_seconds: float = Field(default=60.0, ge=0.0, le=7_200.0)
    context: StepContext | None = None


class ApplyStep(BaseModel):
    query: str = Field(min_length=1, max_length=8_000)
    conversation_id: str | None = None
    call: dict[str, Any]
    context: StepContext | None = None


@router.post("/decide")
async def decide_step(
    user_id: str,
    body: DecideStep,
    service: DependencyConversationService,
    identity: IdentityDependency,
) -> dict[str, Any]:
    authorize_user(user_id, identity)
    authorize_scope(identity, SCOPE_CHAT)
    return await service.decide_step(
        user_id,
        body.query,
        body.lines,
        body.remaining_seconds,
        conversation_id=body.conversation_id,
        context=body.context.model_dump() if body.context else None,
    )


@router.post("/apply")
async def apply_step(
    user_id: str,
    body: ApplyStep,
    service: DependencyConversationService,
    identity: IdentityDependency,
) -> dict[str, Any]:
    authorize_user(user_id, identity)
    authorize_scope(identity, SCOPE_CHAT)
    return await service.apply_step(
        user_id,
        body.query,
        body.conversation_id,
        body.call,
        context=body.context.model_dump() if body.context else None,
    )
