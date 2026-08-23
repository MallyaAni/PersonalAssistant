"""Familiarity is scoped to a place, which is the whole point.

The seen store answers "have I shown you this"; this answers "did you already
know it". For someone who has lived somewhere a while those diverge, and the
divergence reverses when they travel — so the test that matters most is that
knowing every trail in one town suppresses nothing in another.
"""

import os
import uuid

import pytest
from sqlalchemy import delete

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.database.session import AsyncSessionLocal
from backend.discovery.events import DiscoveredEvent
from backend.discovery.familiarity import (
    FamiliarItemRepository,
    FamiliarityFilter,
    familiar_digest,
    locality_scope,
)
from backend.discovery.novelty import ScoredCandidate
from backend.models.discovery_familiar import DiscoveryFamiliarItem

_HOME = "Arlington"
_AWAY = "Denver"


def _vec(*values: float) -> list[float]:
    vector = [0.0] * 768
    for index, value in enumerate(values):
        vector[index] = value
    return vector


def _candidate(title: str, embedding: list[float] | None = None) -> ScoredCandidate:
    return ScoredCandidate(
        DiscoveredEvent(
            source_id="web",
            external_id=f"https://example.org/{title}",
            title=title,
            starts_at=None,
            ends_at=None,
            place=None,
            url=f"https://example.org/{title}",
            summary=None,
        ),
        embedding,
    )


# One candidate from a named source, so two listings can share a title while
# remaining different happenings.
def _candidate_from(source_id: str, title: str) -> ScoredCandidate:
    return ScoredCandidate(
        DiscoveredEvent(
            source_id=source_id,
            external_id=f"https://{source_id}.example.org/{title}",
            title=title,
            starts_at=None,
            ends_at=None,
            place=None,
            url=f"https://{source_id}.example.org/{title}",
            summary=None,
        ),
        None,
    )


async def _cleanup(user_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(DiscoveryFamiliarItem).where(
                DiscoveryFamiliarItem.user_id == user_id
            )
        )
        await session.commit()


def test_the_same_title_normalizes_to_one_record():
    assert familiar_digest("Four Mile Run Trail") == familiar_digest(
        "  four   mile run trail  "
    )


def test_different_places_are_different_scopes():
    assert locality_scope(_HOME) != locality_scope(_AWAY)
    # A missing place is one scope rather than a crash.
    assert locality_scope(None) == locality_scope("")


@pytest.mark.asyncio
async def test_dismissing_something_suppresses_it():
    user_id = f"fam_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = FamiliarItemRepository(session)
            await repo.remember_known(user_id, _HOME, "Four Mile Run Trail", _vec(1.0))

            survivors = await FamiliarityFilter(repo).unfamiliar(
                user_id, _HOME, (_candidate("Four Mile Run Trail", _vec(1.0)),)
            )

            assert survivors == ()
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_dismissing_one_thing_suppresses_the_family():
    # Marking a trail directory as known is only useful if the next four like it
    # are also gone. Suppression is by proximity, not identity.
    user_id = f"fam_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = FamiliarItemRepository(session)
            await repo.remember_known(user_id, _HOME, "Four Mile Run Trail", _vec(1.0))

            survivors = await FamiliarityFilter(repo).unfamiliar(
                user_id,
                _HOME,
                (
                    _candidate("Four Mile Run Trail map", _vec(0.999, 0.02)),
                    _candidate("Pottery class downtown", _vec(0.0, 1.0)),
                ),
            )

            assert len(survivors) == 1
            assert survivors[0].event.title == "Pottery class downtown"
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_knowing_a_place_suppresses_nothing_somewhere_else():
    """The travel case, and the reason familiarity is scoped at all."""
    user_id = f"fam_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = FamiliarItemRepository(session)
            # Years of living in one town.
            for name in ("Four Mile Run Trail", "Potomac Heritage Trail"):
                await repo.remember_known(user_id, _HOME, name, _vec(1.0))

            at_home = await FamiliarityFilter(repo).unfamiliar(
                user_id, _HOME, (_candidate("Four Mile Run Trail", _vec(1.0)),)
            )
            # The same happening, judged from somewhere they have never been.
            away = await FamiliarityFilter(repo).unfamiliar(
                user_id, _AWAY, (_candidate("Four Mile Run Trail", _vec(1.0)),)
            )

            assert at_home == ()
            assert len(away) == 1
            assert await repo.count_known(user_id, _HOME) == 2
            assert await repo.count_known(user_id, _AWAY) == 0
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_a_candidate_without_an_embedding_is_still_matched_by_identity():
    # An embedding failure must not turn a dismissal into a no-op.
    user_id = f"fam_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = FamiliarItemRepository(session)
            await repo.remember_known(user_id, _HOME, "Four Mile Run Trail", None)

            survivors = await FamiliarityFilter(repo).unfamiliar(
                user_id, _HOME, (_candidate("four mile run trail", None),)
            )

            assert survivors == ()
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_dismissing_twice_is_one_record_and_can_be_undone():
    user_id = f"fam_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = FamiliarItemRepository(session)
            await repo.remember_known(user_id, _HOME, "Four Mile Run Trail", _vec(1.0))
            await repo.remember_known(user_id, _HOME, "four mile run trail", _vec(1.0))

            known = await repo.list_known(user_id, _HOME)
            assert len(known) == 1

            assert await repo.forget(user_id, str(known[0]["id"])) is True
            assert await repo.count_known(user_id, _HOME) == 0
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_another_users_record_cannot_be_forgotten():
    owner = f"fam_{uuid.uuid4().hex[:12]}"
    intruder = f"fam_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = FamiliarItemRepository(session)
            await repo.remember_known(owner, _HOME, "Four Mile Run Trail", _vec(1.0))
            known = await repo.list_known(owner, _HOME)

            assert await repo.forget(intruder, str(known[0]["id"])) is False
            assert await repo.count_known(owner, _HOME) == 1
    finally:
        await _cleanup(owner)


# A dismissal means the thing it names. Keying on the cleaned title let a real
# page title collapse to a common word and become the key: after dismissing one
# county's trails page, any later find whose cleaned title was also "Trails" was
# dropped — including other counties' listings the user had never been shown.
@pytest.mark.asyncio
async def test_a_dismissal_does_not_hide_a_different_thing_with_the_same_title():
    user_id = f"fam_{uuid.uuid4().hex[:8]}"
    try:
        # Two different counties' pages, both titled "Trails" - which is what
        # the CMS-name stripping actually produced on the live account.
        arlington = _candidate_from("arlington", "Trails")
        fairfax = _candidate_from("fairfax", "Trails")

        async with AsyncSessionLocal() as session:
            repository = FamiliarItemRepository(session)
            await repository.remember_known(
                user_id, _HOME, "Trails", None, item_digest=arlington.digest
            )
            surviving, hidden = await FamiliarityFilter(repository).filter_known(
                user_id, _HOME, (arlington, fairfax)
            )

        # The dismissed one goes; the other county's listing survives.
        assert hidden == 1
        assert [item.event.source_id for item in surviving] == ["fairfax"]
    finally:
        await _cleanup(user_id)


# Suppression is counted so a dismissal the user did not intend is visible. The
# panel lists what was dismissed, never what those dismissals removed, so
# without this a wrong hide can only be noticed as an unexplained thin digest.
@pytest.mark.asyncio
async def test_hidden_finds_are_counted():
    user_id = f"fam_{uuid.uuid4().hex[:8]}"
    try:
        known = _candidate("Weekly farmers market")
        fresh = _candidate("Night hike at Long Branch")
        async with AsyncSessionLocal() as session:
            repository = FamiliarItemRepository(session)
            await repository.remember_known(
                user_id,
                _HOME,
                known.event.title,
                None,
                item_digest=known.digest,
            )
            surviving, hidden = await FamiliarityFilter(repository).filter_known(
                user_id, _HOME, (known, fresh)
            )

        assert hidden == 1
        assert len(surviving) == 1
    finally:
        await _cleanup(user_id)


# A dismissal recorded before identity keying still works, so the change does
# not quietly resurrect everything anyone had already hidden.
@pytest.mark.asyncio
async def test_a_legacy_title_keyed_dismissal_still_suppresses():
    user_id = f"fam_{uuid.uuid4().hex[:8]}"
    try:
        item = _candidate("Weekly farmers market")
        async with AsyncSessionLocal() as session:
            repository = FamiliarItemRepository(session)
            # No identity supplied: the old title-hash path.
            await repository.remember_known(user_id, _HOME, item.event.title, None)
            surviving, hidden = await FamiliarityFilter(repository).filter_known(
                user_id, _HOME, (item,)
            )

        assert familiar_digest(item.event.title) is not None
        assert hidden == 1
        assert surviving == ()
    finally:
        await _cleanup(user_id)
