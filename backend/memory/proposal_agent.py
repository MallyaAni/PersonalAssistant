"""Semantically classify one utterance into reviewable typed memory proposals."""

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.agents.memory.prompts import MEMORY_PROPOSAL_SYSTEM
from backend.core.llm import LLMClient
from backend.core.prompts import render
from backend.discovery.types import MAX_LABEL_CHARS, MAX_REGION_CHARS, normalize_label

MAX_PROPOSALS_PER_TURN = 8


class LocalityDecision(BaseModel):
    """One explicitly stated home locality."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    region: str | None = Field(default=None, max_length=MAX_REGION_CHARS)


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
    entity: EntityDecision | None = None
    procedure: ProcedureDecision | None = None
    knowledge: KnowledgeDecision | None = None
    semantic_fact: str | None = Field(
        default=None,
        max_length=400,
        description="One stable personal fact not represented by a narrower field.",
    )
    # Whether that fact is a standing preference rather than a plain fact.
    #
    # Measured 2026-08-29/30: on a recommendation-shaped question - "what's on
    # this weekend", "recommend a salsa night" - nothing was retrieved at all,
    # because the two memories that would have mattered sit at cosine 0.371 and
    # 0.467 while an unrelated question about Peru sits at 0.499. Signal and
    # noise overlap, so no threshold separates them and the deployed reranker
    # separates them worse. What distinguishes them is not distance, it is
    # kind: "prefers venues on the metro but will drive for something really
    # good" is a preference; "I own a 2022 Tesla Model 3" is not. So the model
    # that already classifies the fact says which it is, and retrieval selects
    # by that rather than by distance.
    semantic_fact_is_preference: bool = Field(
        default=False,
        description=(
            "True when the fact is a standing preference about what they like, "
            "avoid, or want - taste, tolerance, constraint, budget. False for a "
            "plain fact about them or the world, and false for how they feel "
            "today or what they want on one particular day: a preference has to "
            "be true next month as well, or acting on it later acts on "
            "something that stopped being true."
        ),
    )
    # Whether that fact is a temporary state rather than a durable trait.
    #
    # A fact that describes how things are right now - "feeling tired today",
    # "busy this week, keep it light", "currently avoiding X" - stops being
    # true on its own, so it is stored with a short life and then stops
    # shaping anything, least of all an unattended weekly recommendation.
    # False for a fact that stays true (owns a Tesla, lives in X, is 30).
    # Measured 2026-08-31: a "feeling a little tired today" statement from
    # two days earlier steered a discovery sweep toward easy scenic walks,
    # which is how a hiking-guide page outranked the dance events the user
    # actually asks for. The classifier already knew the statement was not a
    # preference; it still never expired, so it kept acting.
    semantic_fact_is_transient: bool = Field(
        default=False,
        description=(
            "True when the fact describes a temporary state - how they feel "
            "today, what they want this week - that will not be true next "
            "month. False when it stays true: a trait, an ownership, a "
            "preference. A fact that is transient is stored with a short "
            "life so it cannot steer a later recommendation."
        ),
    )
    episodic_event: str | None = Field(default=None, max_length=300)


class GroupMemoryProposalDecision(MemoryProposalDecision):
    """The same interpretation, plus who each fact is about (a group turn)."""

    about: list[str] = Field(
        default_factory=list,
        max_length=8,
        description='Roster names the captured facts are about, or "the group".',
    )


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
        # A group turn: who is speaking and who is in the room. With a
        # roster the decision carries `about`, and every proposal says who
        # it concerns; without one the call is exactly what it always was.
        speaker: str = "",
        roster: tuple[str, ...] = (),
    ) -> MemoryProposalResult:
        in_group = bool(roster)
        # The catalogue exists so a new phrasing of an interest reuses its
        # label instead of creating a near-duplicate. It said nothing about
        # the other kinds, and the model read it as "this is already known":
        # with "Thai food" in the list, "we all settled on thai for friday
        # dinner" produced no proposal at all 3 times in 6 - the group's plan
        # lost because a member liked Thai food (2026-08-28, deploy #20).
        catalogue = (
            "The user has these Scout interest labels: "
            + ", ".join(f'"{label}"' for label in known_interests)
            + ". When a new phrase means one of these labels, or a narrower form "
            "of it, reuse that label. These are labels for interests only: they say "
            "nothing about whether any fact, plan, decision or event is already "
            "known, so a statement worth remembering is still captured in its own "
            "field even when it mentions one of these labels. "
            if known_interests
            else ""
        )
        # A group turn asks a second, separate question - who is each fact
        # about, and what does a member say about another member - instead of
        # adding text to this one. Prompt added for the group crowded out
        # ordinary capture ("I love hiking, honestly it's my favourite thing"
        # produced an interest 6/6 in a private message and 2/6 in a room),
        # and one stray space alone flipped a pinned case at temperature 0
        # (both measured 2026-08-28). Started first so the two calls overlap:
        # a room costs no extra wait, and this prompt stays byte-identical to
        # the one-to-one path it has always been.
        group_call = (
            asyncio.create_task(self._group_reading(query, speaker, roster, previous_reply))
            if in_group
            else None
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
                        'produces no proposal. Set semantic_fact_is_preference '
                        'true when the fact is a standing preference - what they '
                        'like, avoid, or want, including taste, tolerance, budget '
                        'and constraints: "prefers quiet places", "will drive for '
                        'something really good", "cost is not a concern". False '
                        'for a plain fact - "owns a Tesla Model 3" - and false for '
                        'how they feel today: "tired today and wants something '
                        'chill" is not a preference, because it stops being true. '
                        "Set semantic_fact_is_transient true when the fact "
                        "describes a temporary state - how they feel today, what "
                        "they want this week - that will not be true next month; "
                        "false for a durable fact or preference. A transient "
                        "fact is stored with a short life so it stops shaping "
                        "recommendations after it stops being true. "
                        "Return only the required JSON."
                    ),
                },
                {"role": "user", "content": self._utterance(query, previous_reply)},
            ],
            self.max_tokens,
            MemoryProposalDecision.model_json_schema(),
            0,
        )
        decision = MemoryProposalDecision.model_validate(json.loads(result["content"]))
        proposals = self._validated_proposals(decision)
        if group_call is None:
            return MemoryProposalResult(proposals)
        about, others = await group_call
        return MemoryProposalResult(self._merged(proposals, about, others))

    # The group's second question: who the captured facts are about, and what
    # this member said about another member. Never raises into the turn - a
    # failure leaves the ordinary proposals unattributed, which the owner
    # rule reads as the speaker's own words.
    async def _group_reading(
        self, query: str, speaker: str, roster: tuple[str, ...], previous_reply: str
    ) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...]]:
        try:
            result = await asyncio.to_thread(
                self.llm.chat,
                [
                    {
                        "role": "system",
                        "content": render(
                            "memory/proposal_group",
                            speaker=speaker or "a member",
                            roster=", ".join(roster),
                        )
                        + " Return only the required JSON.",
                    },
                    {"role": "user", "content": self._utterance(query, previous_reply)},
                ],
                self.max_tokens,
                GroupMemoryProposalDecision.model_json_schema(),
                0,
            )
            group_decision = GroupMemoryProposalDecision.model_validate(
                json.loads(result["content"])
            )
        except Exception:
            return (), ()
        about = tuple(
            " ".join(str(name).split()) for name in group_decision.about if str(name).strip()
        )
        return about, self._validated_proposals(group_decision)

    # The ordinary proposals, each stamped with who it is about, plus
    # anything the group reading found that the ordinary one could not - a
    # fact about another member, which the one-to-one rules rightly drop.
    @staticmethod
    def _merged(
        proposals: tuple[dict[str, Any], ...],
        about: tuple[str, ...],
        others: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, Any], ...]:
        def identity(proposal: dict[str, Any]) -> tuple[Any, ...]:
            return (
                str(proposal.get("kind") or ""),
                str(proposal.get("content") or proposal.get("value") or proposal.get("name") or proposal.get("title") or ""),
                tuple(sorted(str(label) for label in proposal.get("labels") or ())),
            )

        merged = [{**proposal, "about": list(about)} for proposal in proposals]
        seen = {identity(proposal) for proposal in merged}
        for proposal in others:
            if identity(proposal) in seen:
                continue
            seen.add(identity(proposal))
            merged.append({**proposal, "about": list(about)})
        return tuple(merged[:MAX_PROPOSALS_PER_TURN])

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
        # No schedule field: when Scout's sweep runs is set by the routed
        # scout_schedule tool, the one writer. A second writer here captured
        # "send another don tito reminder at 7" as the sweep's cadence
        # (2026-08-26); two paths to the same row is one too many.
        # Profile fields and one general memory category are compatible. The
        # previous all-or-nothing guard silently lost a stable fact whenever the
        # same introduction also contained a name, interest, locality, or style.
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
            return {
                "kind": "semantic_fact",
                "content": decision.semantic_fact.strip(),
                "is_preference": bool(decision.semantic_fact_is_preference),
                "is_transient": bool(decision.semantic_fact_is_transient),
            }
        if decision.episodic_event:
            return {"kind": "episodic", "content": decision.episodic_event.strip()}
        return None
