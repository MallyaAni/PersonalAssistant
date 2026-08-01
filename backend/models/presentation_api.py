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
    # Omitted appends to the end; supplying a slide inserts directly after it.
    after_slide_id: str | None = Field(default=None, max_length=64)


class ReorderPresentationSlidesBody(BaseModel):
    """The complete new slide order for one known base revision."""

    base_revision_id: UUID
    # Every existing slide, exactly once, in the order wanted.
    slide_ids: list[str] = Field(min_length=1, max_length=30)


class GeneratePresentationSlideImageBody(BaseModel):
    """Validated request for optional local imagery on one selected slide."""

    base_revision_id: UUID
    prompt: str | None = Field(default=None, max_length=2_000)
