from uuid import UUID

from pydantic import BaseModel, Field


class CreatePresentationBody(BaseModel):
    """Validated request for one new editable presentation."""

    user_id: str = Field(min_length=1, max_length=50)
    conversation_id: UUID
    prompt: str = Field(min_length=1, max_length=20_000)


class RevisePresentationSlideBody(BaseModel):
    """Validated feedback targeting one slide in one known base revision."""

    base_revision_id: UUID
    feedback: str = Field(min_length=1, max_length=10_000)


class GeneratePresentationSlideImageBody(BaseModel):
    """Validated request for optional local imagery on one selected slide."""

    base_revision_id: UUID
    prompt: str | None = Field(default=None, max_length=2_000)
