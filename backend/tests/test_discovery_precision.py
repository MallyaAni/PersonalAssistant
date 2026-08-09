"""The precision stage: a cross-encoder reordering what embeddings admitted.

These cover the properties that make the stage safe rather than merely better —
it never admits, it never drops, and its absence is exactly the old behaviour —
plus the two things that are easy to get wrong about its score: the values are
log-odds and are usually negative, and interest strength must not be applied
twice.
"""

import os

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.discovery.aiming import InterestAim, SweepAim
from backend.discovery.events import DiscoveredEvent
from backend.discovery.novelty import ScoredCandidate
from backend.discovery.precision import PrecisionRanker
from backend.discovery.relevance import RankedCandidate


class _StubEncoder:
    """A cross-encoder whose answer each test decides."""

    def __init__(self, table: dict[tuple[str, str], float] | None = None, **kw) -> None:
        self.table = table or {}
        self.enabled = kw.get("enabled", True)
        self.fail = kw.get("fail", False)
        self.wrong_length = kw.get("wrong_length", False)
        self.pairs: list[tuple[str, str]] = []

    def is_enabled(self) -> bool:
        return self.enabled

    def score(self, pairs: list[tuple[str, str]]) -> list[float]:
        self.pairs = list(pairs)
        if self.fail:
            raise RuntimeError("onnx session unavailable")
        if self.wrong_length:
            return [0.0]
        return [self.table.get((query, document), -11.0) for query, document in pairs]


def _event(external_id: str, title: str) -> DiscoveredEvent:
    return DiscoveredEvent(
        source_id="web-search",
        external_id=external_id,
        title=title,
        starts_at=None,
        ends_at=None,
        place=None,
        url=f"https://example.org/{external_id}",
        summary=None,
    )


def _ranked(*titles: str) -> tuple[RankedCandidate, ...]:
    return tuple(
        RankedCandidate(
            candidate=ScoredCandidate(event=_event(f"e{index}", title), embedding=None),
            score=0.5,
            matched_interest="Cosine Guess",
        )
        for index, title in enumerate(titles)
    )


def _aim(*labels: str) -> SweepAim:
    return SweepAim(
        tuple(
            InterestAim(label=label, subject=label, profile=f"{label} profile")
            for label in labels
        )
    )


@pytest.mark.asyncio
async def test_negative_log_odds_still_rank():
    # The whole shortlist scores below zero, which is the ordinary case: these
    # are log-odds, not similarities. A scorer that started from zero would
    # leave every one of them unranked and unattributed.
    shortlist = _ranked("Jazz trio", "Tax seminar")
    aim = _aim("Concerts")
    encoder = _StubEncoder(
        {
            ("Concerts profile", "Jazz trio"): -4.1,
            ("Concerts profile", "Tax seminar"): -11.2,
        }
    )

    ordered = await PrecisionRanker(encoder).order(shortlist, aim)

    assert [item.event.title for item in ordered] == ["Jazz trio", "Tax seminar"]
    assert ordered[0].score == -4.1
    assert ordered[0].matched_interest == "Concerts"


@pytest.mark.asyncio
async def test_a_clear_winner_is_named_and_a_near_tie_is_not():
    shortlist = _ranked("Jazz trio", "Lantern festival")
    aim = _aim("Concerts", "Line Dancing")
    encoder = _StubEncoder(
        {
            # Beats the runner-up comfortably.
            ("Concerts profile", "Jazz trio"): -4.0,
            ("Line Dancing profile", "Jazz trio"): -10.0,
            # Two interests within a hair of each other: a nearest neighbour,
            # not a match, exactly as cosine's own margin rule decided.
            ("Concerts profile", "Lantern festival"): -11.0,
            ("Line Dancing profile", "Lantern festival"): -11.2,
        }
    )

    ordered = await PrecisionRanker(encoder).order(shortlist, aim)

    named = {item.event.title: item.matched_interest for item in ordered}
    assert named["Jazz trio"] == "Concerts"
    assert named["Lantern festival"] is None


@pytest.mark.asyncio
async def test_strength_is_not_applied_twice():
    # Recall already weighted by strength when it decided what reached the
    # shortlist. Re-applying it here would count it twice, and multiplying a
    # negative log-odds by a strength ratio would invert its meaning.
    shortlist = _ranked("Jazz trio")
    aim = _aim("Concerts")
    encoder = _StubEncoder({("Concerts profile", "Jazz trio"): -6.0})

    ordered = await PrecisionRanker(encoder).order(shortlist, aim)

    assert ordered[0].score == -6.0


@pytest.mark.asyncio
async def test_the_aimed_profile_is_the_query_and_the_find_is_the_document():
    shortlist = _ranked("Jazz trio")
    aim = _aim("Concerts")
    encoder = _StubEncoder()

    await PrecisionRanker(encoder).order(shortlist, aim)

    # The same text ranking embedded, so the two stages ask about one person
    # rather than two descriptions of them.
    assert encoder.pairs == [("Concerts profile", "Jazz trio")]


@pytest.mark.asyncio
async def test_it_reorders_but_never_admits_or_drops():
    shortlist = _ranked("A", "B", "C")
    aim = _aim("Concerts")
    encoder = _StubEncoder(
        {
            ("Concerts profile", "A"): -11.0,
            ("Concerts profile", "B"): -2.0,
            ("Concerts profile", "C"): -7.0,
        }
    )

    ordered = await PrecisionRanker(encoder).order(shortlist, aim)

    # Whether a find qualifies was decided before this ran, and this stage
    # deliberately cannot revisit it in either direction.
    assert [item.event.title for item in ordered] == ["B", "C", "A"]
    assert len(ordered) == len(shortlist)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "encoder",
    [
        None,
        _StubEncoder(enabled=False),
        _StubEncoder(fail=True),
        _StubEncoder(wrong_length=True),
    ],
)
async def test_absence_leaves_the_embedding_order_exactly_as_it_was(encoder):
    shortlist = _ranked("A", "B")
    aim = _aim("Concerts")

    ordered = await PrecisionRanker(encoder).order(shortlist, aim)

    assert ordered == shortlist
    assert [item.matched_interest for item in ordered] == [
        "Cosine Guess",
        "Cosine Guess",
    ]


@pytest.mark.asyncio
async def test_a_sweep_with_no_interests_is_left_alone():
    shortlist = _ranked("A")

    ordered = await PrecisionRanker(_StubEncoder()).order(shortlist, SweepAim())

    assert ordered == shortlist
