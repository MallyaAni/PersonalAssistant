import os
import uuid

import pytest
from sqlalchemy import delete

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.database.session import AsyncSessionLocal
from backend.discovery.errors import DiscoveryProfileLimitError
from backend.discovery.repository import DiscoveryProfileRepository
from backend.discovery.service import DiscoveryProfileService, render_profile_context
from backend.discovery.types import (
    MAX_INTERESTS_PER_USER,
    DiscoveryProfile,
    Interest,
    Locality,
    label_digest,
    normalize_label,
)
from backend.models.discovery import DiscoveryInterest, DiscoveryLocality


def _interest(label: str, strength: int = 2) -> Interest:
    return Interest(
        id=str(uuid.uuid4()), label=label, strength=strength, provenance="user_explicit"
    )


def _locality(label: str, is_primary: bool = False) -> Locality:
    return Locality(
        id=str(uuid.uuid4()),
        label=label,
        region="NJ",
        radius_km=25,
        timezone="America/New_York",
        is_primary=is_primary,
    )


# Case and spacing differences describe the same interest, so they must resolve
# to one identity; accents distinguish real place names and are preserved.
def test_normalization_folds_case_and_spacing_but_keeps_accents():
    assert normalize_label("  Live   MUSIC ") == "live music"
    assert label_digest("Live Music") == label_digest("live  music")
    assert normalize_label("Café") == "café"
    assert label_digest("Café") != label_digest("Cafe")


# The digest must never be the plaintext, because the readable copy is sealed
# and the digest is the only value stored in the clear.
def test_digest_does_not_expose_the_label():
    digest = label_digest("underground jazz")
    assert "underground" not in digest
    assert len(digest) == 64


def test_primary_locality_prefers_the_marked_place_then_falls_back():
    marked = DiscoveryProfile(
        interests=(),
        localities=(_locality("Hoboken"), _locality("Jersey City", is_primary=True)),
    )
    assert marked.primary_locality is not None
    assert marked.primary_locality.label == "Jersey City"

    unmarked = DiscoveryProfile(interests=(), localities=(_locality("Hoboken"),))
    assert unmarked.primary_locality is not None
    assert unmarked.primary_locality.label == "Hoboken"

    assert DiscoveryProfile(interests=(), localities=()).primary_locality is None


# Only approved labels reach a prompt. Identifiers and provenance are internal
# bookkeeping and must not be handed to the model.
def test_rendered_context_carries_labels_without_internal_bookkeeping():
    profile = DiscoveryProfile(
        interests=(_interest("live music", 3),),
        localities=(_locality("Jersey City", is_primary=True),),
    )

    rendered = render_profile_context(profile)

    assert rendered["interests"] == [{"label": "live music", "strength": 3}]
    assert rendered["lives_near"] == {
        "place": "Jersey City",
        "region": "NJ",
        "radius_km": 25,
    }
    assert "id" not in str(rendered)
    assert "provenance" not in str(rendered)


def test_rendered_context_is_empty_without_a_profile():
    assert render_profile_context(DiscoveryProfile(interests=(), localities=())) == {}


# An interest that was never approved by the user cannot be written under a
# provenance that claims it was.
@pytest.mark.asyncio
async def test_unsupported_provenance_is_rejected():
    async with AsyncSessionLocal() as session:
        service = DiscoveryProfileService(DiscoveryProfileRepository(session))
        with pytest.raises(ValueError, match="Unsupported interest provenance"):
            await service.add_interest(
                "provenance_user", "live music", provenance="model_inferred"
            )


@pytest.mark.asyncio
async def test_profile_is_user_scoped_and_deduplicates_by_normalized_label():
    user_id = f"discovery_{uuid.uuid4().hex[:12]}"
    other_id = f"discovery_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            service = DiscoveryProfileService(DiscoveryProfileRepository(session))
            await service.add_interest(user_id, "Live Music", strength=2)
            # The same label in different case updates the row rather than
            # creating a second one the user would have to delete twice.
            await service.add_interest(user_id, "live  music", strength=3)
            await service.add_interest(other_id, "pottery")

            profile = await service.get_profile(user_id)
            assert [item.label for item in profile.interests] == ["live  music"]
            assert profile.interests[0].strength == 3

            other = await service.get_profile(other_id)
            assert [item.label for item in other.interests] == ["pottery"]
    finally:
        await _cleanup(user_id, other_id)


@pytest.mark.asyncio
async def test_first_locality_becomes_primary_and_promotion_demotes_the_rest():
    user_id = f"discovery_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            service = DiscoveryProfileService(DiscoveryProfileRepository(session))
            first = await service.add_locality(user_id, "Jersey City", region="NJ")
            assert first.is_primary is True

            await service.add_locality(user_id, "Hoboken", region="NJ")
            await service.add_locality(user_id, "Hoboken", region="NJ", is_primary=True)

            profile = await service.get_profile(user_id)
            primaries = [item.label for item in profile.localities if item.is_primary]
            assert primaries == ["Hoboken"]
    finally:
        await _cleanup(user_id)


# Editing a place must not silently demote it. A live request that omitted the
# flag cleared the only primary locality, leaving discovery runs with no default.
@pytest.mark.asyncio
async def test_updating_a_primary_locality_keeps_it_primary():
    user_id = f"discovery_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            service = DiscoveryProfileService(DiscoveryProfileRepository(session))
            await service.add_locality(user_id, "Jersey City", region="NJ")

            updated = await service.add_locality(
                user_id, "Jersey City", region="NJ", radius_km=40
            )

            assert updated.is_primary is True
            assert updated.radius_km == 40
            profile = await service.get_profile(user_id)
            assert profile.primary_locality is not None
            assert profile.primary_locality.label == "Jersey City"
    finally:
        await _cleanup(user_id)


# One user's identifier must never delete another user's row.
@pytest.mark.asyncio
async def test_delete_is_scoped_to_the_owning_user():
    owner_id = f"discovery_{uuid.uuid4().hex[:12]}"
    attacker_id = f"discovery_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            service = DiscoveryProfileService(DiscoveryProfileRepository(session))
            interest = await service.add_interest(owner_id, "ceramics")

            removed = await service.remove_interest(attacker_id, uuid.UUID(interest.id))
            assert removed is False
            assert len((await service.get_profile(owner_id)).interests) == 1

            assert await service.remove_interest(owner_id, uuid.UUID(interest.id))
            assert (await service.get_profile(owner_id)).interests == ()
    finally:
        await _cleanup(owner_id, attacker_id)


# Every interest is eligible to enter a prompt, so the list stays bounded. The
# limit must not block editing an interest that already exists.
@pytest.mark.asyncio
async def test_interest_capacity_is_bounded_but_still_allows_edits():
    user_id = f"discovery_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            service = DiscoveryProfileService(DiscoveryProfileRepository(session))
            for index in range(MAX_INTERESTS_PER_USER):
                await service.add_interest(user_id, f"interest {index}")

            with pytest.raises(DiscoveryProfileLimitError):
                await service.add_interest(user_id, "one too many")

            edited = await service.add_interest(user_id, "interest 0", strength=3)
            assert edited.strength == 3
    finally:
        await _cleanup(user_id)


async def _cleanup(*user_ids: str) -> None:
    async with AsyncSessionLocal() as session:
        for table in (DiscoveryInterest, DiscoveryLocality):
            await session.execute(
                delete(table).where(table.user_id.in_(list(user_ids)))
            )
        await session.commit()


# Exercise the router itself. The service tests operate on dataclasses directly,
# which is exactly why a serialization fault in the HTTP layer reached a live
# request before it reached a test.
def test_api_round_trips_a_profile_and_scopes_deletes():
    from fastapi.testclient import TestClient

    from backend.main import app

    user_id = f"discovery_{uuid.uuid4().hex[:12]}"
    other_id = f"discovery_{uuid.uuid4().hex[:12]}"
    try:
        with TestClient(app) as client:
            created = client.put(
                f"/api/v1/discovery/{user_id}/interests",
                json={"label": "live music", "strength": 3},
            )
            assert created.status_code == 200
            assert created.json()["label"] == "live music"
            assert created.json()["strength"] == 3

            placed = client.put(
                f"/api/v1/discovery/{user_id}/localities",
                json={"label": "Jersey City", "region": "NJ", "radius_km": 30},
            )
            assert placed.status_code == 200
            assert placed.json()["is_primary"] is True

            profile = client.get(f"/api/v1/discovery/{user_id}")
            assert profile.status_code == 200
            body = profile.json()
            assert [item["label"] for item in body["interests"]] == ["live music"]
            assert [item["label"] for item in body["localities"]] == ["Jersey City"]

            # An unknown field is rejected rather than silently ignored.
            assert (
                client.put(
                    f"/api/v1/discovery/{user_id}/interests",
                    json={"label": "pottery", "unexpected": 1},
                ).status_code
                == 422
            )

            interest_id = created.json()["id"]
            assert (
                client.delete(
                    f"/api/v1/discovery/{other_id}/interests/{interest_id}"
                ).status_code
                == 404
            )
            assert (
                client.delete(
                    f"/api/v1/discovery/{user_id}/interests/{interest_id}"
                ).status_code
                == 204
            )
    finally:
        import asyncio

        asyncio.run(_cleanup(user_id, other_id))
