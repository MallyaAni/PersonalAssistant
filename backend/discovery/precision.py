"""The precision half of the cascade: read each pair properly, once.

Embedding similarity is a recall instrument. It compares a candidate against an
interest without ever reading the two together, which is what makes it cheap
enough to run over every candidate and why its scores cluster so tightly that
`relevance.py` needs `MIN_ATTRIBUTION_MARGIN` (0.035) to decide whether the best
interest is really a match or merely the top of a heap where everything scores
within a hair of everything else.

So the loop now asks the question twice, with the right instrument each time:

1. **recall** — `relevance.py` scores every novel candidate against the aimed
   interest vectors and admits a shortlist. Unchanged, and still what decides
   *eligibility*: `MIN_SCORE` and the lead-time rules keep their meaning;
2. **precision** — this, a local cross-encoder reading (interest, candidate) as
   one sequence, which sets the order within that shortlist and re-decides which
   interest a find is reported as matching;
3. **constraints** — `reranking.py`, where the model applies what the user has
   approved being known by, which no scorer of topical similarity can represent.

Two properties are kept deliberately:

- **it reorders, it does not admit.** Nothing enters the digest here that
  deterministic ranking rejected. A stage that could admit would be a second,
  differently-calibrated definition of what qualifies;
- **absence is not failure.** With no weights, a disabled provider, or any error,
  the shortlist keeps the order and attribution embeddings gave it. That is the
  behaviour the sweep had before this stage existed.

Attribution is the concrete win, and it was measured rather than hoped for. Over
the eight candidates whose cosine scores `relevance.py` tabulates — the ones
that forced its 0.035 margin — cosine attributed 5 of 8 correctly and named the
wrong interest three times. The cross-encoder attributed every one of them
correctly, in all four query framings tried. So a digest can say *why* a find
was chosen far more often, and be right when it does.

The margin below is measured on this stage's own score distribution rather than
carried over, for exactly the reason `conversation_service.py` records about
image-recall distance: a threshold that means one thing in one space means
something else entirely in another.
"""

import asyncio
from dataclasses import replace

from backend.core.interfaces import RerankProvider
from backend.discovery.relevance import RankedCandidate, candidate_text
from backend.discovery.types import SweepAim

# How far the best interest must beat the second best before the digest names it
# as the reason a find was chosen.
#
# Not comparable to `MIN_ATTRIBUTION_MARGIN` in `relevance.py`. That one is
# 0.035 on cosine similarities clustered near 0.6; this is log-odds from a
# cross-encoder, which ranges roughly -11 to +3. The same number in the two
# places would mean two entirely different things, which is exactly the mistake
# `conversation_service.py`'s `max_distance=0.96` note warns about.
#
# Measured over the same candidates whose cosine scores are tabulated in
# `relevance.py`, with the aimed profile as the query — the text the sweep
# actually sends:
#
#   Water Lantern Festival        margin 0.29   should name nothing
#   Planet Word Afterhours        margin 0.06   should name nothing
#   Guided Sunrise Hike           margin 1.49   Hiking
#   Country Dance night           margin 2.34   Line Dancing
#   Virginia Wine Festival        margin 2.57   Wine Tasting
#   Saturday Morning Social Run   margin 7.39   Run Clubs
#   Live Jazz Trio, Blues Alley   margin 12.61  Concerts
#
# Wrong attributions stop at 0.29 and right ones start at 1.49, so the bound
# sits between with room on both sides. Note the absolute score separates
# nothing here either — a correct Hiking match scores -9.84 while a find that
# should name nothing scores -11.11 — which is the same conclusion cosine
# reached in a different space, and why this is a margin rather than a floor.
MIN_ATTRIBUTION_MARGIN = 1.0

# Longest document one pair carries. The model truncates anyway; this keeps the
# text that matters — what it is and where — ahead of the truncation point.
MAX_DOCUMENT_CHARS = 400


class PrecisionRanker:
    """Reorder a shortlist by reading each interest and candidate together."""

    # The provider is optional so a sweep runs unchanged without weights.
    def __init__(
        self,
        reranker: RerankProvider | None,
        min_attribution_margin: float = MIN_ATTRIBUTION_MARGIN,
    ) -> None:
        self.reranker = reranker
        self.min_attribution_margin = min_attribution_margin

    # Report whether this stage can do anything, so a caller can skip the work.
    def is_enabled(self) -> bool:
        return self.reranker is not None and self.reranker.is_enabled()

    # Rescore and reorder one shortlist, keeping every candidate it was given.
    #
    # The aim supplies the query side of each pair: the profile sentence memory
    # produced where there was one, and the bare interest label otherwise. That
    # is the same text ranking embedded, so the two stages are asking about the
    # same person rather than about two different descriptions of them.
    async def order(
        self,
        shortlist: tuple[RankedCandidate, ...],
        aim: SweepAim,
    ) -> tuple[RankedCandidate, ...]:
        if not shortlist or not self.is_enabled() or not aim.aims:
            return shortlist
        queries = [(item.label, item.profile) for item in aim.aims]
        documents = [_document(item) for item in shortlist]
        pairs = [
            (profile, document) for document in documents for _, profile in queries
        ]
        try:
            flat = await asyncio.to_thread(self.reranker.score, pairs)  # type: ignore[union-attr]
        except Exception:
            # Unreadable weights, a shape mismatch, a missing input — none of
            # them are worth failing a sweep for. The embedding order stands.
            return shortlist
        if len(flat) != len(pairs):
            return shortlist

        width = len(queries)
        rescored: list[RankedCandidate] = []
        for index, item in enumerate(shortlist):
            row = flat[index * width : (index + 1) * width]
            score, matched = self._best(row, queries)
            rescored.append(replace(item, score=score, matched_interest=matched))
        # Sort only. Which finds are eligible was decided before this ran, and
        # this stage deliberately cannot revisit it.
        rescored.sort(key=lambda item: -item.score)
        return tuple(rescored)

    # The best interest for one candidate, and whether it beat the runner-up by
    # enough to be named.
    #
    # Interest strength deliberately plays no part here, for two reasons. It was
    # already applied during recall, where it scaled the cosine score that
    # decided whether this candidate reached the shortlist at all, so applying
    # it again would count it twice. And `relevance.py` applies it by
    # multiplication, which is meaningful on a cosine score that cannot go below
    # zero and actively wrong on a log-odds one that usually does: multiplying
    # -9.8 by a strength of 3/2 makes it -14.7, so caring *more* about an
    # interest would push its matches down.
    #
    # `best` starts at negative infinity for the same reason. Nearly every logit
    # here is negative, so a zero starting point would leave a whole shortlist
    # unranked and unattributed.
    def _best(
        self,
        row: list[float],
        queries: list[tuple[str, str]],
    ) -> tuple[float, str | None]:
        best = float("-inf")
        runner_up = float("-inf")
        matched: str | None = None
        for (label, _), value in zip(queries, row, strict=True):
            if value > best:
                best, runner_up = value, best
                matched = label
            elif value > runner_up:
                runner_up = value
        if best - runner_up < self.min_attribution_margin:
            # A near-tie is a nearest neighbour, not a match. Naming one is
            # worse than naming none: it is a stated reason that is wrong.
            return best, None
        return best, matched


# The document side of a pair: what the find is, where, and its own first words.
# The same text ranking embedded, so neither stage is judging a different thing.
def _document(item: RankedCandidate) -> str:
    event = item.event
    return candidate_text(event.title, event.place, event.summary)[:MAX_DOCUMENT_CHARS]
