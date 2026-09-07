"""One bounded multimodal decision for a newly uploaded image."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.core.prompts import load

UPLOAD_INSPECTION_PROMPT = load("vision/upload_inspection").strip()


class UploadIdentifiedItem(BaseModel):
    """One item-level visual identification with an explicit evidence grade."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=120)
    confidence: Literal["high", "medium", "low"]
    basis: str = Field(min_length=1, max_length=300)


class UploadInspectionDecision(BaseModel):
    """Validated decisions returned by the single upload inspection."""

    model_config = ConfigDict(extra="forbid")

    intent: Literal["ask", "edit"]
    observation: str = Field(min_length=1, max_length=4000)
    answer: str = Field(min_length=1, max_length=3000)
    grounding: Literal["not_needed", "useful", "unsupported"]
    search_query: str = Field(max_length=500)
    needs_reasoning: bool
    unsupported_reason: Literal[
        "not_applicable",
        "missing_visual_evidence",
        "model_uncertain",
        "safety_sensitive",
    ]
    identified_items: list[UploadIdentifiedItem] = Field(max_length=12)
    # Handles the user gives this image or its subject, kept so a later
    # "the photo of gubacchi" can recall the picture by name. Empty when the
    # request names nothing and no name is visible in the pixels.
    names: list[str] = Field(default_factory=list, max_length=8)

    # Normalize the user-given handles: strip, drop empties and over-long
    # strings, and collapse case-variants so one subject is never stored twice.
    @model_validator(mode="after")
    def normalize_names(self) -> "UploadInspectionDecision":
        seen: set[str] = set()
        clean: list[str] = []
        for raw in self.names:
            value = " ".join(str(raw).split()).strip()
            if not value or len(value) > 60:
                continue
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            clean.append(value)
        self.names = clean
        return self

    # Normalize fields whose meaning is conditional on the grounding decision.
    @model_validator(mode="after")
    def validate_grounding_contract(self) -> "UploadInspectionDecision":
        if self.grounding == "useful" and not self.search_query.strip():
            raise ValueError("Useful visual grounding omitted its search query")
        if self.grounding == "unsupported":
            if self.unsupported_reason == "not_applicable":
                uncertain = any(
                    item.confidence in {"medium", "low"}
                    for item in self.identified_items
                )
                self.unsupported_reason = (
                    "model_uncertain" if uncertain else "missing_visual_evidence"
                )
        else:
            self.unsupported_reason = "not_applicable"
        if self.unsupported_reason == "safety_sensitive":
            self.identified_items = []
        if self.grounding != "useful":
            self.search_query = ""
        return self


UPLOAD_INSPECTION_SCHEMA = UploadInspectionDecision.model_json_schema()
# The VLM must always emit `names` (an empty list when there is nothing): an
# optional field in a strict response grammar is a field the model skips, and
# a name it skips is a handle that can never be recalled. The Python default
# stays so callers that build a decision without names keep working.
UPLOAD_INSPECTION_SCHEMA["required"] = [
    *(UPLOAD_INSPECTION_SCHEMA.get("required") or []),
    "names",
]


# Join the fixed evidence contract to the user's bounded request.
def build_upload_inspection_prompt(question: str) -> str:
    return f"{UPLOAD_INSPECTION_PROMPT}\n\nUser request:\n{question.strip()}"
