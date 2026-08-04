"""Unusual finds are the one ranking path not anchored to a stated interest.

That anchoring is what keeps a digest from becoming noise, so this axis has to
earn its place: a small quota, a high bar, and never mixed into the matched
list.
"""

import os

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

import pytest

from backend.discovery.events import DiscoveredEvent
from backend.discovery.notable import NotableSelector
from backend.discovery.novelty import ScoredCandidate
from backend.discovery.relevance import RankedCandidate


def _candidate(title: str, external_id: str | None = None) -> ScoredCandidate:
    return ScoredCandidate(
        DiscoveredEvent(
            source_id="web",
            external_id=external_id or f"https://example.org/{title}",
            title=title,
            starts_at=None,
            ends_at=None,
            place=None,
            url=f"https://example.org/{title}",
            summary=None,
        ),
        [0.1] * 768,
    )


class _StubSeen:
    """Answer the nearest-neighbour question with fixed distances."""

    def __init__(self, distances: dict[str, float | None]) -> None:
        self.distances = distances

    async def nearest_seen_distance(self, user_id, embedding):
        return self.distances.get(user_id, 0.0)


class _PerTitleSeen:
    def __init__(self, by_title: dict[str, float | None]) -> None:
        self.by_title = by_title
        self.asked: list[str] = []

    async def nearest_seen_distance(self, user_id, embedding):
        # The selector asks once per candidate, in order.
        title = self.asked.pop(0)
        return self.by_title.get(title)


# Something unlike anything the account has seen is surfaced; a variation on
# the usual stream is not. A forty-first trail listing is novel and
# unremarkable; a balloon festival is novel and worth interrupting for.
@pytest.mark.asyncio
async def test_only_the_genuinely_unlike_is_surfaced():
    usual = _candidate("Another trail listing")
    unusual = _candidate("Hot air balloon festival")
    seen = _PerTitleSeen(
        {"Another trail listing": 0.11, "Hot air balloon festival": 0.62}
    )
    seen.asked = ["Another trail listing", "Hot air balloon festival"]

    picked = await NotableSelector(seen).select("u", (usual, unusual))

    assert [item.event.title for item in picked] == ["Hot air balloon festival"]


# The quota is hard. An unanchored axis is the most likely way to turn a useful
# digest into one nobody reads, so it cannot grow with the sweep.
@pytest.mark.asyncio
async def test_the_quota_is_capped():
    candidates = tuple(_candidate(f"Unusual {index}") for index in range(6))
    seen = _StubSeen({"u": 0.9})

    picked = await NotableSelector(seen, limit=2).select("u", candidates)

    assert len(picked) == 2


# Something already being shown for matching an interest is not repeated here.
# Showing it twice under a second heading is what "padded" looks like.
@pytest.mark.asyncio
async def test_an_already_selected_find_is_not_repeated():
    matched = _candidate("Trail race")
    already = (
        RankedCandidate(candidate=matched, score=0.8, matched_interest="hiking"),
    )
    seen = _StubSeen({"u": 0.9})

    picked = await NotableSelector(seen).select("u", (matched,), already)

    assert picked == ()


# A fresh account has nothing to be unlike. Staying quiet is correct: otherwise
# a first digest is entirely "unusual" items, which teaches the wrong thing
# about what the section means.
@pytest.mark.asyncio
async def test_an_account_with_no_history_surfaces_nothing():
    seen = _StubSeen({"u": None})

    picked = await NotableSelector(seen).select("u", (_candidate("Anything"),))

    assert picked == ()


# The case that showed the first design was wrong. Measured against a real
# ten-item history, a guided night hike scored 0.362 unlike and a hot air
# balloon festival 0.328 — so a bar on unlikeness alone admitted the hiking
# event and rejected the balloon festival, exactly backwards. What separates
# them is not distance from history; it is whether the matcher wanted it.
@pytest.mark.asyncio
async def test_an_interest_match_is_never_surfaced_as_a_surprise():
    night_hike = _candidate("Guided night hike on the Potomac Heritage Trail")
    balloons = _candidate("Hot air balloon festival over Shenandoah")
    seen = _PerTitleSeen(
        {
            "Guided night hike on the Potomac Heritage Trail": 0.362,
            "Hot air balloon festival over Shenandoah": 0.328,
        }
    )
    seen.asked = [
        "Guided night hike on the Potomac Heritage Trail",
        "Hot air balloon festival over Shenandoah",
    ]
    # The matcher scores the hike well against "hiking" and the festival poorly.
    interest_scores = {night_hike.digest: 0.55, balloons.digest: 0.04}

    picked = await NotableSelector(seen).select(
        "u", (night_hike, balloons), interest_scores=interest_scores
    )

    assert [item.event.title for item in picked] == [
        "Hot air balloon festival over Shenandoah"
    ]
