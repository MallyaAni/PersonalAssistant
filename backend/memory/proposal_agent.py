"""Semantically classify one utterance into reviewable typed memory proposals."""

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.agents.memory.prompts import MEMORY_PROPOSAL_SYSTEM
from backend.core.llm import LLMClient
from backend.discovery.types import MAX_LABEL_CHARS, MAX_REGION_CHARS, normalize_label

MAX_PROPOSALS_PER_TURN = 8


class LocalityDecision(BaseModel):
    """One explicitly stated home locality."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    region: str | None = Field(default=None, max_length=MAX_REGION_CHARS)


class ScheduleDecision(BaseModel):
    """One explicitly stated cadence for the user's own scheduled sweep.

    Timezone is deliberately absent. It is not something people say, and asking
    the model to infer one from a city is asking it to guess a fact about the
    user; the locality already carries a real timezone and the application reads
    it from there.
    """

    model_config = ConfigDict(extra="forbid")

    cadence: Literal["daily", "weekly"]
    # 0-23 in the user's own local time. Required rather than optional: an
    # optional field in a response grammar is a field the model skips, and a
    # schedule with no hour is not a schedule.
    hour: int = Field(ge=0, le=23)
    # Minutes past the hour, so "9:25pm" is not silently rounded to 21:00.
    minute: int = Field(ge=0, le=59)
    # Monday is 0, matching datetime.weekday(). Ignored for a daily cadence.
    #
    # Required, with no default: given one the model skipped the field and every
    # weekly schedule landed on Monday, including "weekly on Sunday mornings".
    # An optional field in a response grammar is a field the model will skip.
    weekday: int = Field(ge=0, le=6)


class EntityDecision(BaseModel):
    """One explicitly identified person or organization relationship."""

    model_config = ConfigDict(extra="forbid")

    entity_type: Literal["person", "organization"]
    canonical_name: str = Field(min_length=1, max_length=200)
    relationship: str = Field(min_length=1, max_length=100)


class ProcedureDecision(BaseModel):
    """One explicitly requested reusable workflow."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)
    steps: list[str] = Field(min_length=2, max_length=20)


class KnowledgeDecision(BaseModel):
    """One explicitly requested titled reference."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=10_000)


class MemoryProposalDecision(BaseModel):
    """The grammar-constrained semantic interpretation of one user message."""

    model_config = ConfigDict(extra="forbid")

    preferred_name: str | None = Field(default=None, max_length=100)
    response_style: Literal["concise", "detailed"] | None = None
    locality: LocalityDecision | None = None
    interests: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Only activities, hobbies, subjects, or events the user likes.",
    )
    schedule: ScheduleDecision | None = None
    entity: EntityDecision | None = None
    procedure: ProcedureDecision | None = None
    knowledge: KnowledgeDecision | None = None
    semantic_fact: str | None = Field(
        default=None,
        max_length=400,
        description="One stable personal fact not represented by a narrower field.",
    )
    episodic_event: str | None = Field(default=None, max_length=300)


@dataclass(frozen=True, slots=True)
class MemoryProposalResult:
    """Validated proposal payloads with no persistence authority."""

    proposals: tuple[dict[str, Any], ...]


class MemoryProposalAgent:
    """Use a local model, not phrase matching, to understand memory intent."""

    # Configure the focused classifier without granting it storage authority.
    def __init__(self, llm: LLMClient, max_tokens: int = 256) -> None:
        self.llm = llm
        self.max_tokens = max_tokens

    # Interpret the whole utterance and return only bounded, typed proposals.
    async def propose(
        self,
        query: str,
        known_interests: tuple[str, ...] = (),
        previous_reply: str = "",
    ) -> MemoryProposalResult:
        catalogue = (
            "The user already follows these Scout interests: "
            + ", ".join(f'"{label}"' for label in known_interests)
            + ". Reuse an existing label exactly when a new phrase means the same "
            "interest or a narrower form of it. "
            if known_interests
            else ""
        )
        result = await asyncio.to_thread(
            self.llm.chat,
            [
                {
                    "role": "system",
                    "content": (
                        MEMORY_PROPOSAL_SYSTEM
                        + catalogue
                        + 'Meaning examples: "Remember that my dog is called '
                        'Biscuit" and "Please keep track of the fact that my dog is '
                        'called Biscuit" both produce semantic_fact "My dog is '
                        'called Biscuit." with no interest. "I love training dogs" '
                        'produces interest "dog training". "What is my dog called?" '
                        "produces no proposal. " + "Return only the required JSON."
                    ),
                },
                {"role": "user", "content": self._utterance(query, previous_reply)},
            ],
            self.max_tokens,
            MemoryProposalDecision.model_json_schema(),
            0,
        )
        decision = MemoryProposalDecision.model_validate(json.loads(result["content"]))
        return MemoryProposalResult(self._validated_proposals(decision))

    # The message to interpret, with the assistant's previous reply alongside
    # when there is one. "Adjust this to daily at 3pm" names its subject only
    # by "this"; read alone it was taken as the sweep's schedule whatever the
    # conversation was about (2026-08-26). The reply is labelled as a referent
    # aid, not a source of facts, and the prompt says the same.
    @staticmethod
    def _utterance(query: str, previous_reply: str) -> str:
        said = " ".join(previous_reply.split())[:400]
        if not said:
            return query
        return (
            "The assistant's previous reply, supplied only so that a reference "
            f"like 'this' or 'it' can be resolved - never a source of facts: {said}"
            f"\n\nThe user's current message: {query}"
        )

    # Convert the model decision into the existing typed API proposal payloads.
    def _validated_proposals(
        self,
        decision: MemoryProposalDecision,
    ) -> tuple[dict[str, Any], ...]:
        proposals: list[dict[str, Any]] = []
        preferred_name = self._clean_name(decision.preferred_name)
        if preferred_name:
            proposals.append({"kind": "preferred_name", "value": preferred_name})
        if decision.response_style:
            proposals.append(
                {"kind": "response_style", "value": decision.response_style}
            )
        if decision.locality:
            label = " ".join(decision.locality.label.split())
            region = (
                " ".join(decision.locality.region.split())
                if decision.locality.region
                else None
            )
            if label and len(label) <= 80:
                proposals.append(
                    {"kind": "discovery_locality", "label": label, "region": region}
                )
        interests = self._clean_interests(decision.interests)
        if interests:
            proposals.append({"kind": "discovery_interests", "labels": interests})
        if decision.schedule:
            proposals.append(
                {
                    "kind": "discovery_schedule",
                    "cadence": decision.schedule.cadence,
                    "hour": decision.schedule.hour,
                    "minute": decision.schedule.minute,
                    "weekday": decision.schedule.weekday,
                }
            )
        if not proposals:
            general = self._general_proposal(decision)
            if general:
                proposals.append(general)
        return tuple(proposals[:MAX_PROPOSALS_PER_TURN])

    # Keep a model-extracted name bounded and free of control-like punctuation.
    @staticmethod
    def _clean_name(value: str | None) -> str | None:
        if value is None:
            return None
        candidate = " ".join(value.split()).strip('"')
        if not candidate or len(candidate) > 100 or len(candidate.split()) > 6:
            return None
        supported = all(
            character.isalnum() or character in " '-" for character in candidate
        )
        if not supported:
            return None
        return candidate

    # Normalize and deduplicate semantically selected Scout labels.
    @staticmethod
    def _clean_interests(values: list[str]) -> list[str]:
        labels: list[str] = []
        seen: set[str] = set()
        for value in values:
            display = " ".join(value.split()).strip('"')
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
        return labels

    # Preserve the prior single-best rule for non-profile memory categories.
    @staticmethod
    def _general_proposal(decision: MemoryProposalDecision) -> dict[str, Any] | None:
        if decision.entity:
            return {
                "kind": "entity",
                "entity_type": decision.entity.entity_type,
                "canonical_name": decision.entity.canonical_name.strip(),
                "attributes": {"relationship": decision.entity.relationship.strip()},
            }
        if decision.procedure:
            steps = [" ".join(step.split()) for step in decision.procedure.steps]
            return {
                "kind": "procedure",
                "name": decision.procedure.name.strip(),
                "description": decision.procedure.description.strip()
                or f"User-approved workflow: {decision.procedure.name.strip()}",
                "steps": [
                    {"order": index, "instruction": step}
                    for index, step in enumerate(steps, start=1)
                ],
            }
        if decision.knowledge:
            return {
                "kind": "knowledge",
                "title": decision.knowledge.title.strip(),
                "content": decision.knowledge.content.strip(),
            }
        if decision.semantic_fact:
            return {"kind": "semantic_fact", "content": decision.semantic_fact.strip()}
        if decision.episodic_event:
            return {"kind": "episodic", "content": decision.episodic_event.strip()}
        return None
