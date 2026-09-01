"""Order a shortlist by what is known about the person, not by cosine alone.

Embedding similarity picks a good shortlist and then cannot separate it. Measured
over real candidates, a genuine concert scored 0.612 against "Concerts" and a
lantern festival scored 0.616 against "Line Dancing" — the wrong match scored
higher than the right one. That clustering is what forced `MIN_ATTRIBUTION_MARGIN`
in `relevance.py`, and it is a property of the space rather than a tuning
problem: everything sits near everything.

Two things a vector cannot represent are exactly what decides these:

- **a reason.** "Beginner welcome" and "for advanced climbers" embed almost
  identically and mean opposite things to someone who has never climbed;
- **an exclusion.** No embedding of "Run Clubs" is far from a women-only running
  event. Nothing in the geometry says *not for you*.

So the deterministic ranker still decides what is eligible, and this reorders
what survived. The division matters: a model that could admit candidates would
be deciding what qualifies during an unattended sweep, which is what
`relevance.py` refuses. A model that can only reorder an already-qualified
shortlist can be wrong about the order and never wrong about the standard.

The order also carries a notability tiebreak (prompts/scout/rerank.md, added
2026-09-01): among finds the approved facts do not distinguish, a one-off
festival or headline performance leads a routine weekly social, because a
recurring social is already on the calendar. Reorder-only, never an exclusion,
so it cannot empty a digest the way a selection-side filter once did. Measured:
`evaluate_discovery_ranking` green (filtering recall 0.8571, geography
happening-retention 1.0) and a rehearsal sweep shows variety; the tiebreak
itself is pinned by two functional cases in test_prompt_behaviour.py.

Exclusion is the one exception, and it is deliberately narrow. A find may be
dropped only when the listing itself states a restriction and an approved fact
explicitly contradicts it. Never inferred — not from a name, not from an
interest, not from anything the user did. Some "Women's Run" events are open to
all, which is why this can only act on what the page says, and why a digest that
lost everything falls back to the deterministic order rather than shipping empty.

**Do not strengthen that wording without measuring it.** It was measured here,
greedily, against the live runtime, on a shortlist containing a stated
women-only race, a stadium show, and an over-21 wine festival, for a person
whose facts said they are a man, dislike stadium shows, and do not drink:

- as written, the model excluded nothing and ranked the women-only race last;
- given a worked example and "when the text is explicit, exclude it", it
  excluded all three — turning two *preferences* into eligibility bars — and on
  a control context with no fact about gender at all it still excluded the
  women-only race. That is the inference this must never make, produced by
  wording that reads as more careful.

So the conservative wording stays, and audience restriction is not solved here.
The fix is a deterministic restricted-audience field read out of the page in
`summarize.py`, said in the digest so the user can judge, and filtered only by
code against an explicit fact. A 4B model is not the right thing to trust with
who may attend.

Candidate text is untrusted third-party prose, quoted as data and never followed
as instructions, exactly as it is in `summarize.py`.
"""

import asyncio
import json
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from backend.core.interfaces import TextWriter
from backend.core.prompts import load
from backend.discovery.personal_context import PersonalContext
from backend.discovery.relevance import (
    MAX_SELECTED,
    MAX_UNDATED,
    RankedCandidate,
    cap_by_lead_time,
)

# How many shortlisted finds one call may consider. Beyond this the tail keeps
# its deterministic order, which is what it had before this existed.
MAX_CONSIDERED = 16

# How much of a find's own words the model sees. Enough to carry a stated
# restriction or an audience, short enough that sixteen of them fit.
MAX_CANDIDATE_CHARS = 240


class _Ordering(BaseModel):
    """The grammar-constrained ordering returned by the local model."""

    model_config = ConfigDict(extra="forbid")

    # Best first. May be partial: anything unlisted keeps its deterministic
    # position behind the ones that were listed.
    order: list[int] = Field(default_factory=list, max_length=MAX_CONSIDERED)
    # Finds whose own text states a restriction an approved fact contradicts.
    excluded: list[int] = Field(default_factory=list, max_length=MAX_CONSIDERED)


# The same schema with both fields required.
#
# Left optional, the model simply never emitted `excluded` — three greedy runs
# against the live runtime returned `{"order": [...]}` and nothing else, so the
# exclusion question was not being answered so much as skipped. Required, it
# answers it: the same three runs returned the same order with `"excluded": []`.
# The default stays on the model so a runtime that omits the field anyway still
# parses, rather than losing a good ordering to a missing empty list.
def _schema() -> dict[str, object]:
    schema = dict(_Ordering.model_json_schema())
    schema["required"] = ["order", "excluded"]
    return schema


_SYSTEM = load("scout/rerank")


class MemoryReranker:
    """Reorder a qualified shortlist against approved personal memory."""

    # The writer is the same narrow inference contract the describer uses; None
    # means the sweep runs entirely deterministically.
    def __init__(
        self,
        writer: TextWriter | None,
        max_considered: int = MAX_CONSIDERED,
        max_tokens: int = 256,
    ) -> None:
        self.writer = writer
        self.max_considered = max_considered
        self.max_tokens = max_tokens

    # Order and truncate one shortlist. Dated finds and undated mentions are
    # kept apart and capped separately, exactly as `RelevanceRanker.rank` does:
    # an undated find cannot become a calendar entry, so it must never displace
    # one however well it reads.
    async def order(
        self,
        shortlist: tuple[RankedCandidate, ...],
        context: PersonalContext,
        now: datetime | None = None,
        limit: int = MAX_SELECTED,
        undated_limit: int = MAX_UNDATED,
    ) -> tuple[RankedCandidate, ...]:
        moment = now or datetime.now(UTC)
        if not shortlist:
            return ()
        ranks, excluded = await self._decide(shortlist, context)
        kept = [index for index in range(len(shortlist)) if index not in excluded]
        if not kept:
            # Everything was excluded, which is far likelier to be a model
            # failure than a person for whom nothing at all is eligible.
            kept = list(range(len(shortlist)))
        ordered = [
            shortlist[index]
            for index in sorted(kept, key=lambda index: ranks.get(index, index))
        ]
        return cap_by_lead_time(ordered, moment, limit, undated_limit)

    # Ask for an order, or accept the one we already have. Returns a rank per
    # shortlist position and the set of positions to drop.
    async def _decide(
        self, shortlist: tuple[RankedCandidate, ...], context: PersonalContext
    ) -> tuple[dict[int, int], set[int]]:
        deterministic = {index: index for index in range(len(shortlist))}
        if self.writer is None or context.is_empty or len(shortlist) < 2:
            return deterministic, set()
        considered = shortlist[: self.max_considered]
        prompt = (
            "Facts this person has approved about themselves:\n"
            f"{context.render()}\n\n"
            "Shortlisted finds:\n" + _render_candidates(considered)
        )
        try:
            result = await asyncio.to_thread(
                self.writer.chat,
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                self.max_tokens,
                _schema(),
                # Greedy, so the same shortlist orders the same way every run.
                0.0,
            )
            decision = _Ordering.model_validate(json.loads(result["content"]))
        except Exception:
            return deterministic, set()

        excluded = {
            number - 1 for number in decision.excluded if 1 <= number <= len(considered)
        }
        ranks: dict[int, int] = {}
        placed: set[int] = set()
        position = 0
        for number in decision.order:
            index = number - 1
            if not 0 <= index < len(considered) or index in placed:
                continue
            placed.add(index)
            ranks[index] = position
            position += 1
        # Anything the model did not mention keeps its deterministic order,
        # behind everything it did. A partial answer is still an improvement on
        # no answer, and this is what makes a truncated generation safe.
        for index in range(len(shortlist)):
            if index not in placed:
                ranks[index] = position + index
        return ranks, excluded


# Number the shortlist for the prompt. The number is the only handle the model
# gets: it cannot name a URL, and nothing it writes is used as text.
def _render_candidates(shortlist: tuple[RankedCandidate, ...]) -> str:
    lines: list[str] = []
    for number, item in enumerate(shortlist, start=1):
        event = item.event
        parts = [event.title]
        if event.place:
            parts.append(event.place)
        if event.summary:
            parts.append(event.summary)
        text = " — ".join(parts)[:MAX_CANDIDATE_CHARS]
        lines.append(f"{number}. {text}")
    return "\n".join(lines)
