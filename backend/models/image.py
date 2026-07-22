from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SUPPORTED_RESOLUTIONS = {
    (2048, 2048),
    (2304, 1728),
    (2304, 1792),
    (2496, 1664),
    (2560, 1440),
    (3104, 1312),
    (1728, 2304),
    (1792, 2304),
    (1664, 2496),
    (1440, 2560),
    (1312, 3104),
}


class ImageGenerationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=50)
    conversation_id: UUID
    prompt: str = Field(min_length=1, max_length=2_000)
    width: int = 2048
    height: int = 2048
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)

    # Trim identifiers and prompts while refusing whitespace-only values.
    @field_validator("user_id", "prompt")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    # Restrict requests to the resolutions used to train the selected image model.
    @model_validator(mode="after")
    def validate_resolution(self) -> "ImageGenerationBody":
        if (self.width, self.height) not in _SUPPORTED_RESOLUTIONS:
            raise ValueError(
                "resolution is not supported by the configured image model"
            )
        return self


class ImageQuestionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=50)
    prompt: str = Field(min_length=1, max_length=2_000)

    # Trim identifiers and prompts while refusing whitespace-only values.
    @field_validator("user_id", "prompt")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value
