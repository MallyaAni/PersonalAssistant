import os
import uuid
from datetime import UTC, datetime, timedelta

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


# Build a compact interest record for profile behavior tests.
def _interest(label: str, strength: int = 2) -> Interest:
    return Interest(
        id=str(uuid.uuid4()), label=label, strength=strength, provenance="user_explicit"
    )


# Build a compact locality record with independent home and travel flags.
def _locality(
    label: str,
    is_primary: bool = False,
    is_travel_active: bool = False,
    travel_expires_at: datetime | None = None,
) -> Locality:
    return Locality(
        id=str(uuid.uuid4()),
        label=label,
        region="NJ",
        radius_km=25,
        timezone="America/New_York",
        is_primary=is_primary,
        is_travel_active=is_travel_active,
        travel_expires_at=travel_expires_at,
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


# Prefer the approved home, falling back only for a legacy profile without one.
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


# Travel changes the operational place while preserving the approved home.
def test_active_locality_prefers_travel_without_changing_primary():
    profile = DiscoveryProfile(
        interests=(),
        localities=(
            _locality("Arlington", is_primary=True),
            _locality("Denver", is_travel_active=True),
        ),
    )

    assert profile.primary_locality is not None
    assert profile.primary_locality.label == "Arlington"
    assert profile.active_locality is not None
    assert profile.active_locality.label == "Denver"


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


# An empty profile contributes no prompt context.
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


# Remove profile rows created by service-level tests.
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


# Exercise reversible travel through the public API and preserve the home fact.
def test_api_travel_mode_preserves_home_and_scopes_the_destination():
    from fastapi.testclient import TestClient

    from backend.discovery.projection import LOCALITY_KEY
    from backend.main import app

    user_id = f"travel_{uuid.uuid4().hex[:12]}"
    other_id = f"travel_{uuid.uuid4().hex[:12]}"
    try:
        with TestClient(app) as client:
            home = client.put(
                f"/api/v1/discovery/{user_id}/localities",
                json={"label": "Arlington", "region": "Virginia"},
            )
            destination = client.put(
                f"/api/v1/discovery/{user_id}/localities",
                json={"label": "Denver", "region": "Colorado"},
            )
            assert home.status_code == 200
            assert destination.status_code == 200
            assert home.json()["is_primary"] is True
            assert destination.json()["is_primary"] is False

            started = client.put(
                f"/api/v1/discovery/{user_id}/travel",
                json={"locality_id": destination.json()["id"]},
            )
            profile = client.get(f"/api/v1/discovery/{user_id}").json()
            facts = client.get(f"/api/v1/memory/{user_id}").json()["facts"]

            assert started.status_code == 200
            assert started.json()["active_locality"]["label"] == "Denver"
            assert (
                next(
                    item
                    for item in profile["localities"]
                    if item["label"] == "Arlington"
                )["is_primary"]
                is True
            )
            assert (
                next(
                    item for item in profile["localities"] if item["label"] == "Denver"
                )["is_travel_active"]
                is True
            )
            assert [(fact["fact_key"], fact["value"]) for fact in facts] == [
                (LOCALITY_KEY, "Arlington, Virginia")
            ]

            assert (
                client.put(
                    f"/api/v1/discovery/{other_id}/travel",
                    json={"locality_id": destination.json()["id"]},
                ).status_code
                == 404
            )
            assert (
                client.put(
                    f"/api/v1/discovery/{user_id}/travel",
                    json={"locality_id": home.json()["id"]},
                ).status_code
                == 409
            )

            stopped = client.delete(f"/api/v1/discovery/{user_id}/travel")
            after = client.get(f"/api/v1/discovery/{user_id}").json()
            assert stopped.status_code == 204
            assert not any(item["is_travel_active"] for item in after["localities"])
    finally:
        with TestClient(app) as client:
            client.delete(f"/api/v1/memory/{user_id}")
            client.delete(f"/api/v1/memory/{other_id}")


# A trip that nobody remembered to end must not redirect Scout forever. The
# failure was silent: a weekly digest about a city the user left in spring still
# arrives looking like a working digest, and every find in it is useless.
def test_a_lapsed_trip_falls_back_to_home_on_its_own():
    moment = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
    profile = DiscoveryProfile(
        interests=(),
        localities=(
            _locality("Arlington", is_primary=True),
            _locality(
                "Denver",
                is_travel_active=True,
                travel_expires_at=moment - timedelta(days=1),
            ),
        ),
    )

    lapsed = profile.locality_at(moment)
    assert lapsed is not None
    assert lapsed.label == "Arlington"
    # Still away the day before it expires.
    current = profile.locality_at(moment - timedelta(days=2))
    assert current is not None
    assert current.label == "Denver"


# A destination recorded before expiry existed stays open-ended, so the
# migration changes nothing for a trip that is already running.
def test_a_trip_without_an_expiry_stays_active():
    profile = DiscoveryProfile(
        interests=(),
        localities=(
            _locality("Arlington", is_primary=True),
            _locality("Denver", is_travel_active=True),
        ),
    )

    assert profile.is_away is True
    current = profile.active_locality
    assert current is not None
    assert current.label == "Denver"


# Reporting a location must never rewrite where someone lives. It used to write
# the primary locality, and with it the approved memory fact, so one press from
# a hotel said the user had moved - and pressing it again on the way home said
# they had moved twice.
@pytest.mark.asyncio
async def test_reporting_a_location_moves_scout_but_never_home():
    user_id = f"place_{uuid.uuid4().hex[:8]}"
    try:
        async with AsyncSessionLocal() as session:
            service = DiscoveryProfileService(DiscoveryProfileRepository(session))
            await service.add_locality(
                user_id, "Arlington", "Virginia", is_primary=True
            )

            away, is_away = await service.set_current_place(
                user_id, "Denver", "Colorado", trip_days=14
            )

            assert is_away is True
            assert away.label == "Denver"
            profile = await service.get_profile(user_id)
            home = profile.primary_locality
            assert home is not None
            assert home.label == "Arlington"
            assert away.travel_expires_at is not None
            current = profile.active_locality
            assert current is not None
            assert current.label == "Denver"
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(DiscoveryLocality).where(DiscoveryLocality.user_id == user_id)
            )
            await session.commit()


# Arriving home ends the trip rather than recording home as a destination.
@pytest.mark.asyncio
async def test_reporting_home_ends_the_trip():
    user_id = f"place_{uuid.uuid4().hex[:8]}"
    try:
        async with AsyncSessionLocal() as session:
            service = DiscoveryProfileService(DiscoveryProfileRepository(session))
            await service.add_locality(
                user_id, "Arlington", "Virginia", is_primary=True
            )
            await service.set_current_place(user_id, "Denver", "Colorado")

            back, is_away = await service.set_current_place(
                user_id, "Arlington", "Virginia"
            )

            assert is_away is False
            assert back.label == "Arlington"
            profile = await service.get_profile(user_id)
            assert profile.is_away is False
            assert not any(item.is_travel_active for item in profile.localities)
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(DiscoveryLocality).where(DiscoveryLocality.user_id == user_id)
            )
            await session.commit()


# With nothing recorded yet, the first place someone reports is where they live.
# Treating it as a trip would leave the profile permanently away from a home it
# never had.
@pytest.mark.asyncio
async def test_the_first_reported_place_becomes_home():
    user_id = f"place_{uuid.uuid4().hex[:8]}"
    try:
        async with AsyncSessionLocal() as session:
            service = DiscoveryProfileService(DiscoveryProfileRepository(session))

            locality, is_away = await service.set_current_place(
                user_id, "Arlington", "Virginia"
            )

            assert is_away is False
            assert locality.is_primary is True
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(DiscoveryLocality).where(DiscoveryLocality.user_id == user_id)
            )
            await session.commit()
