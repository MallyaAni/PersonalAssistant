"""The owned HTTP boundary for discovery sources and calendar files.

Router-level coverage exists because the unit tests never touch serialization,
dependency assembly, or ownership checks — and those are where this subsystem
has broken before.
"""

import os
import uuid

from fastapi.testclient import TestClient

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.core.dependencies import get_embedding_provider
from backend.discovery.novelty import ScoredCandidate, SeenItemRepository
from backend.embeddings.base import EmbeddingProvider
from backend.main import app


def _vector(first: float = 1.0) -> list[float]:
    return [first, *([0.0] * 767)]


class _DeterministicEmbeddings(EmbeddingProvider):
    model = "discovery-test-embedding"

    def embed_text(self, text: str) -> list[float]:
        return _vector()

    def embed_query(self, query: str) -> list[float]:
        return _vector()


app.dependency_overrides[get_embedding_provider] = _DeterministicEmbeddings


def _user() -> str:
    return f"disc_{uuid.uuid4().hex[:12]}"


def _cleanup(client: TestClient, user_id: str) -> None:
    listing = client.get(f"/api/v1/discovery/{user_id}/sources")
    if listing.status_code == 200:
        for source in listing.json()["sources"]:
            client.delete(f"/api/v1/discovery/{user_id}/sources/{source['id']}")


def test_sources_round_trip_through_the_owned_api():
    user_id = _user()
    with TestClient(app) as client:
        try:
            created = client.put(
                f"/api/v1/discovery/{user_id}/sources",
                json={
                    "kind": "ics",
                    "url": "https://example.org/venue.ics",
                    "label": "Local venue",
                },
            )
            assert created.status_code == 200
            assert created.json()["kind"] == "ics"

            listing = client.get(f"/api/v1/discovery/{user_id}/sources")
            assert listing.status_code == 200
            assert len(listing.json()["sources"]) == 1

            # The same URL again edits rather than adding a second fetch.
            client.put(
                f"/api/v1/discovery/{user_id}/sources",
                json={"kind": "ics", "url": "https://example.org/venue.ics"},
            )
            assert (
                len(
                    client.get(f"/api/v1/discovery/{user_id}/sources").json()["sources"]
                )
                == 1
            )
        finally:
            _cleanup(client, user_id)


def test_a_non_web_feed_url_is_refused():
    user_id = _user()
    with TestClient(app) as client:
        response = client.put(
            f"/api/v1/discovery/{user_id}/sources",
            json={"kind": "ics", "url": "file:///etc/passwd"},
        )
        assert response.status_code == 422


def test_deleting_another_users_source_returns_404_without_removing_it():
    owner = _user()
    intruder = _user()
    with TestClient(app) as client:
        try:
            created = client.put(
                f"/api/v1/discovery/{owner}/sources",
                json={"kind": "rss", "url": "https://example.org/feed.xml"},
            ).json()

            denied = client.delete(
                f"/api/v1/discovery/{intruder}/sources/{created['id']}"
            )

            assert denied.status_code == 404
            assert (
                len(client.get(f"/api/v1/discovery/{owner}/sources").json()["sources"])
                == 1
            )
        finally:
            _cleanup(client, owner)


def test_a_stored_event_downloads_as_a_calendar_file():
    import asyncio
    from datetime import UTC, datetime, timedelta

    from backend.database.session import AsyncSessionLocal
    from backend.discovery.events import DiscoveredEvent

    user_id = _user()
    starts_at = datetime.now(UTC) + timedelta(days=9)
    event = DiscoveredEvent(
        source_id="src-api",
        external_id="evt-api",
        title="Jazz at the Green",
        starts_at=starts_at,
        ends_at=None,
        place="New Haven, CT",
        url="https://example.org/jazz",
        summary=None,
    )
    candidate = ScoredCandidate(event=event, embedding=_vector())

    async def _seed() -> str:
        async with AsyncSessionLocal() as session:
            repo = SeenItemRepository(session)
            await repo.record_seen(user_id, candidate, announced=True)
            await session.commit()
        return candidate.digest

    async def _forget() -> None:
        async with AsyncSessionLocal() as session:
            await SeenItemRepository(session).forget_all(user_id)

    digest = asyncio.run(_seed())
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/v1/discovery/{user_id}/calendar/{digest}.ics")

            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/calendar")
            assert "Jazz-at-the-Green.ics" in response.headers["content-disposition"]
            body = response.text
            assert body.startswith("BEGIN:VCALENDAR")
            assert "SUMMARY:Jazz at the Green" in body
            assert body.rstrip().endswith("END:VCALENDAR")

            # Another user asking for the same digest gets nothing.
            other = client.get(f"/api/v1/discovery/{_user()}/calendar/{digest}.ics")
            assert other.status_code == 404
    finally:
        asyncio.run(_forget())


def test_an_unknown_digest_is_not_found():
    user_id = _user()
    with TestClient(app) as client:
        response = client.get(f"/api/v1/discovery/{user_id}/calendar/{'0' * 64}.ics")
        assert response.status_code == 404


def test_the_calendar_link_is_absolute_so_a_phone_can_open_it():
    # A relative path only resolves on the origin the page was served from and
    # fails silently when the same link is opened from a phone, which is where
    # an "Add to calendar" tap happens.
    from backend.api.v1.discovery import _calendar_link

    assert (
        _calendar_link("https://deep-matter.com/api/v1/discovery", "ani.mallya", "abc123")
        == "https://deep-matter.com/api/v1/discovery/ani.mallya/calendar/abc123.ics"
    )
    # A trailing slash on the base must not double the separator.
    assert (
        _calendar_link("https://x.test/api/v1/discovery/", "u", "d")
        == "https://x.test/api/v1/discovery/u/calendar/d.ics"
    )
