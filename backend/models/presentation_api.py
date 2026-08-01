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


class AddPresentationSlideBody(BaseModel):
    """Validated request to add one slide to a known base revision."""

    base_revision_id: UUID
    brief: str = Field(min_length=1, max_length=10_000)
    # 0-based index for the new slide. Omitted appends to the end. An index
    # rather than a neighbour reference so position 0 is expressible.
    position: int | None = Field(default=None, ge=0, le=30)


class ReorderPresentationSlidesBody(BaseModel):
    """The complete new slide order for one known base revision."""

    base_revision_id: UUID
    # Every existing slide, exactly once, in the order wanted.
    slide_ids: list[str] = Field(min_length=1, max_length=30)


class GeneratePresentationSlideImageBody(BaseModel):
    """Validated request for optional local imagery on one selected slide."""

    base_revision_id: UUID
    prompt: str | None = Field(default=None, max_length=2_000)
