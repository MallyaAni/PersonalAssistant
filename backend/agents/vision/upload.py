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


# Join the fixed evidence contract to the user's bounded request.
def build_upload_inspection_prompt(question: str) -> str:
    return f"{UPLOAD_INSPECTION_PROMPT}\n\nUser request:\n{question.strip()}"
