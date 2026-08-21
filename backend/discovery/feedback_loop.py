"""What the tapbacks mean for the next sweep.

Reactions have been collected and recorded since the feedback loop was
built, and then nothing read them: four real thumbs sat in the table while
every sweep ranked as though nobody had ever said anything. This module is
the read side. It joins each reaction back to the interest that surfaced
the find, and hands the sweep two things:

- **adjusted strengths** for deterministic ranking. Arithmetic, like the
  date guards: net thumbs per interest shade its stored strength up or
  down within the 1-3 band the ranker already understands. Stored
  strengths are never written - the shading is recomputed from the full
  reaction history every sweep, so it is idempotent, self-healing, and
  gone the moment a reaction is deleted.
- **reaction statements** for the model stages. The aim planner and the
  reranker read approved facts about the person; what they reacted to is
  exactly such a fact, and the model weighing "they waved off the winery
  evening" against a shortlist is the judgement no arithmetic reaches.

Both fail soft: no reactions, no rows, or an unreadable run all mean the
sweep behaves exactly as it did before this module existed.
"""

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.discovery_feedback import DiscoverySentFind
from backend.models.discovery_run import DiscoveryRun

# Enough history to shade every interest a profile may hold, small enough
# that one query stays cheap.
MAX_REACTIONS_READ = 60

# How many reaction statements reach the model stages. The newest carry the
# signal; a long tail of old thumbs would crowd out the approved facts the
# context exists to carry.
MAX_STATEMENTS = 6


@dataclass(frozen=True, slots=True)
class ReactedFind:
    """One thumb, joined back to what it was about."""

    title: str
    # "liked" or "disliked", as the collector records them.
    reaction: str
    # The interest that surfaced the find, or None when the find matched
    # nothing (a notable, or a near-tie the ranker declined to name).
    interest: str | None


# Every reacted find for this user, newest first, with the interest that
# surfaced it. The join runs through the run's digest record by title:
# the sent row and the digest both store the described title, and the
# digest is the only place the matched interest was written down.
async def reacted_finds(
    session: AsyncSession, user_id: str, limit: int = MAX_REACTIONS_READ
) -> tuple[ReactedFind, ...]:
    rows = (
        (
            await session.execute(
                select(DiscoverySentFind)
                .where(
                    DiscoverySentFind.user_id == user_id,
                    DiscoverySentFind.reaction.is_not(None),
                )
                .order_by(DiscoverySentFind.reacted_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return ()
    matched: dict[str, dict[str, str | None]] = {}
    run_ids = {str(row.run_id) for row in rows if row.run_id is not None}
    if run_ids:
        runs = (
            (
                await session.execute(
                    select(DiscoveryRun).where(DiscoveryRun.id.in_(run_ids))
                )
            )
            .scalars()
            .all()
        )
        for run in runs:
            try:
                digest = json.loads(run.digest_json or "{}")
            except ValueError:
                continue
            by_title = {
                str(item.get("title")): item.get("matched_interest")
                for item in digest.get("selected") or []
            }
            matched[str(run.id)] = by_title
    return tuple(
        ReactedFind(
            title=str(row.label or ""),
            reaction=str(row.reaction),
            interest=matched.get(str(row.run_id), {}).get(str(row.label or "")),
        )
        for row in rows
    )


# Stored strengths, shaded by the net thumbs each interest has earned.
# Clamped to the 1-3 band the ranker's normalization was built around, and
# keyed by the same labels; an interest nobody reacted about is untouched.
def adjusted_strengths(
    base: dict[str, int], reacted: tuple[ReactedFind, ...]
) -> dict[str, int]:
    if not reacted:
        return dict(base)
    net: dict[str, int] = {}
    for find in reacted:
        if find.interest is None or find.interest not in base:
            continue
        net[find.interest] = net.get(find.interest, 0) + (
            1 if find.reaction == "liked" else -1
        )
    shaded = dict(base)
    for label, swing in net.items():
        shaded[label] = max(1, min(3, base[label] + swing))
    return shaded


# The newest reactions as statements for the model stages, phrased as what
# happened rather than as instructions - the prompts around them already say
# how to weigh a fact.
def reaction_statements(
    reacted: tuple[ReactedFind, ...], limit: int = MAX_STATEMENTS
) -> tuple[str, ...]:
    statements = []
    for find in reacted[:limit]:
        verb = "thumbs-up" if find.reaction == "liked" else "thumbs-down"
        statements.append(
            f"They gave a {verb} to \"{find.title}\" from an earlier digest."
        )
    return tuple(statements)
