"""Use a local language model to understand explicit Scout interests."""

import asyncio
import json
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from backend.core.llm import LLMClient
from backend.discovery.types import MAX_LABEL_CHARS, normalize_label

MAX_INTERESTS_PER_PROPOSAL = 8


class InterestDecision(BaseModel):
    """The grammar-constrained decision returned by the local model."""

    model_config = ConfigDict(extra="forbid")

    explicit: bool
    interests: list[str] = Field(
        default_factory=list,
        max_length=MAX_INTERESTS_PER_PROPOSAL,
    )


@dataclass(frozen=True, slots=True)
class ScoutInterestProposal:
    """A bounded set of interests the user explicitly stated about themself."""

    labels: tuple[str, ...]


class ScoutInterestProposalAgent:
    """Classify natural language into reviewable Scout-interest proposals."""

    # Configure the focused local classifier without granting it persistence.
    def __init__(self, llm: LLMClient, max_tokens: int = 128) -> None:
        self.llm = llm
        self.max_tokens = max_tokens

    # Understand one utterance and return only validated user-stated interests.
    async def propose(self, query: str) -> ScoutInterestProposal | None:
        result = await asyncio.to_thread(
            self.llm.chat,
            [
                {
                    "role": "system",
                    "content": (
                        "Read only the current user message. Set explicit=true when "
                        "the user states their own current interests, likes, hobbies, "
                        "or topics they enjoy. Extract every distinct interest as a "
                        "short topic label. A comma-separated list produces separate "
                        "labels. A request to remember the interests still counts. "
                        "Set explicit=false with an empty list when the message only "
                        "asks a question, discusses a topic, describes another person, "
                        "says the user dislikes something, or says a former interest "
                        "is no longer current. Do not infer unstated interests. "
                        'Examples: "My interests are basketball, soccer" -> true, '
                        '["basketball", "soccer"]. "What sports are nearby?" -> '
                        'false, []. "My daughter likes ballet, but I do not" -> '
                        "false, []. Return only the required JSON."
                    ),
                },
                {"role": "user", "content": query},
            ],
            self.max_tokens,
            InterestDecision.model_json_schema(),
            0,
        )
        decision = InterestDecision.model_validate(json.loads(result["content"]))
        if not decision.explicit:
            return None
        labels: list[str] = []
        seen: set[str] = set()
        for raw in decision.interests:
            display = " ".join(raw.split()).strip('"')
            identity = normalize_label(display)
            if (
                not display
                or len(display) > MAX_LABEL_CHARS
                or not identity
                or identity in seen
            ):
                continue
            seen.add(identity)
            labels.append(display)
        return ScoutInterestProposal(tuple(labels)) if labels else None
