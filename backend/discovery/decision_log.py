"""What the ranker considered, not only what it sent.

A reaction is a label on an item. On its own it is close to useless for
improving ranking, because it says nothing about *why* that item was in front of
the person: which interest matched it, how strongly it scored, how many better
or worse things it beat, or where in the message it appeared. Worse, the record
of what was rejected disappears entirely, and a rejected item is the only thing
that can ever tell you the ranker was wrong to reject it.

So this records the decision, not the outcome. Written at the moment of
selection, in the shape the off-policy evaluation literature settled on — the
same fields Open Bandit Pipeline expects of logged bandit feedback — so the data
can be handed to a standard estimator later instead of being re-derived from
whatever survived:

| there            | here                                        |
| ---------------- | ------------------------------------------- |
| `context`        | the interests and place this run ran against |
| `action`         | `digest`, the item's stable identity         |
| `reward`         | joined later from the reaction on the bubble |
| `pscore`         | `propensity`, the chance the policy chose it |
| `position`       | the slot in the digest                       |
| `action_context` | `score` and `interest`, why it ranked there  |

One thing this deliberately does not hide: `policy` records that selection is
deterministic top-k, and a deterministic policy assigns propensity 1.0 to what
it chose and 0.0 to everything else. Under the usual estimators, an action with
zero probability of being logged contributes nothing, so **no amount of this
data alone makes an alternative ranker measurable.** That takes exploration —
sometimes sending something the policy did not rank first, and recording the
real chance it had. Logging the propensity now, honestly, is what makes the
change from deterministic to stochastic visible in the data rather than silent.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# The policy that chose. Recorded rather than assumed, because the estimator a
# future analyst may use is only valid for some of the possible answers.
DETERMINISTIC_TOP_K = "deterministic_top_k"

# Enough of the title to recognise a row when reading the log by hand. The
# identity that matters is `digest`; this is for human eyes only.
TITLE_CHARS = 80

VERSION = 1


@dataclass(frozen=True, slots=True)
class Considered:
    """One candidate the ranker weighed, chosen or not."""

    digest: str
    title: str
    score: float
    interest: str | None
    shortlist_rank: int
    selected: bool
    # Where it appeared in the message, for the position bias that any ranking
    # model has to account for. None when it was not sent.
    position: int | None
    # The chance this policy had of choosing it. Degenerate under a
    # deterministic policy, which is the point of recording it.
    propensity: float


# Record one selection decision in full, chosen and rejected alike.
#
# `shortlist` is everything the deterministic ranker admitted, in its order;
# `selected` is what survived to the message, in send order. Both are needed:
# the second is the action taken, the first is the set it was taken from, and an
# action without its alternatives cannot be evaluated against anything.
def build_decision(
    shortlist: tuple[Any, ...],
    selected: tuple[Any, ...],
    interests: tuple[str, ...],
    locality: str | None,
    decided_at: datetime,
    policy: str = DETERMINISTIC_TOP_K,
) -> dict[str, Any]:
    positions = {
        item.candidate.digest: index for index, item in enumerate(selected)
    }
    considered: list[Considered] = []
    for rank, item in enumerate(shortlist):
        digest = item.candidate.digest
        position = positions.get(digest)
        considered.append(
            Considered(
                digest=digest,
                title=str(item.candidate.event.title or "")[:TITLE_CHARS],
                score=round(float(item.score), 6),
                interest=item.matched_interest,
                shortlist_rank=rank,
                selected=position is not None,
                position=position,
                propensity=1.0 if position is not None else 0.0,
            )
        )

    # An item can reach the message without reaching the shortlist — the notable
    # section picks on unlikeness rather than on interest. It is still an action
    # the person saw and may react to, so it is logged as one.
    known = {row.digest for row in considered}
    for digest, position in positions.items():
        if digest in known:
            continue
        item = selected[position]
        considered.append(
            Considered(
                digest=digest,
                title=str(item.candidate.event.title or "")[:TITLE_CHARS],
                score=round(float(item.score), 6),
                interest=item.matched_interest,
                shortlist_rank=-1,
                selected=True,
                position=position,
                propensity=1.0,
            )
        )

    return {
        "version": VERSION,
        "policy": policy,
        "decided_at": decided_at.isoformat(),
        "context": {"interests": list(interests), "locality": locality},
        "considered": [
            {
                "digest": row.digest,
                "title": row.title,
                "score": row.score,
                "interest": row.interest,
                "shortlist_rank": row.shortlist_rank,
                "selected": row.selected,
                "position": row.position,
                "propensity": row.propensity,
            }
            for row in considered
        ],
    }


# Serialize a decision for the sealed column it is stored in.
def to_json(decision: dict[str, Any]) -> str:
    return json.dumps(decision, separators=(",", ":"), sort_keys=True)
