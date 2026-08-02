import os
import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.config.settings import settings
from backend.core.auth_dependencies import get_login_rate_limiter
from backend.core.dependencies import get_embedding_provider
from backend.database.session import SessionLocal
from backend.embeddings.base import EmbeddingProvider
from backend.main import app
from backend.models.auth import RegistrationInvite, UserAccount, UserSession
from backend.models.memory import SemanticMemory, UserProfile
from backend.services.auth_service import digest_registration_invite
from backend.services.login_rate_limiter import LoginRateLimitDecision

_ORIGIN = "http://127.0.0.1:5173"
_PASSWORD = "Two profile acceptance password 123!"


# Build one deterministic vector that separates the two private test memories.
def _vector(first: float, second: float = 0.0) -> list[float]:
    return [first, second, *([0.0] * 766)]


class _DeterministicEmbeddingProvider(EmbeddingProvider):
    # Embed each profile's marker into a distinct deterministic direction.
    def embed_text(self, text: str) -> list[float]:
        return _vector(0.0, 1.0) if "blue-orchid" in text else _vector(1.0)

    # Match searches to the same profile-specific deterministic direction.
    def embed_query(self, query: str) -> list[float]:
        return _vector(0.0, 1.0) if "blue-orchid" in query else _vector(1.0)


class _OpenRateLimiter:
    # Admit deterministic registration and login attempts without shared Redis.
    async def before_attempt(self, username: str) -> LoginRateLimitDecision:
        return LoginRateLimitDecision(True)

    # Accept failure accounting for negative registration assertions.
    async def record_failure(self, username: str) -> None:
        return None

    # Accept successful clearing for positive registration assertions.
    async def clear_failures(self, username: str) -> None:
        return None


# Replace external embedding and Redis dependencies for one isolated test.
@pytest.fixture
def isolated_dependencies() -> Generator[None, None, None]:
    limiter = _OpenRateLimiter()

    # Return one deterministic rate limiter for the test application.
    def provide_limiter() -> _OpenRateLimiter:
        return limiter

    # Return one deterministic embedding provider for every memory operation.
    def provide_embeddings() -> _DeterministicEmbeddingProvider:
        return _DeterministicEmbeddingProvider()

    app.dependency_overrides[get_login_rate_limiter] = provide_limiter
    app.dependency_overrides[get_embedding_provider] = provide_embeddings
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_login_rate_limiter, None)
        app.dependency_overrides.pop(get_embedding_provider, None)


# Persist one raw-code digest and return the code that a friend would receive.
def _create_invite() -> str:
    raw_token = f"invite-{uuid.uuid4()}-{uuid.uuid4()}"
    with SessionLocal() as session:
        session.add(
            RegistrationInvite(
                token_digest=digest_registration_invite(raw_token),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        session.commit()
    return raw_token


# Remove only rows owned by the unique profiles and invitations from this test.
def _cleanup(user_ids: tuple[str, ...], invite_tokens: tuple[str, ...]) -> None:
    with SessionLocal() as session:
        session.execute(
            delete(SemanticMemory).where(SemanticMemory.user_id.in_(user_ids))
        )
        session.execute(delete(UserProfile).where(UserProfile.user_id.in_(user_ids)))
        session.execute(delete(UserSession).where(UserSession.user_id.in_(user_ids)))
        session.execute(
            delete(RegistrationInvite).where(
                RegistrationInvite.token_digest.in_(
                    [digest_registration_invite(token) for token in invite_tokens]
                )
            )
        )
        session.execute(delete(UserAccount).where(UserAccount.user_id.in_(user_ids)))
        session.commit()


# Prove registration, semantic recall, owner denial, invite use, and logout.
def test_registered_profiles_cannot_read_or_recall_each_others_semantic_context(
    isolated_dependencies: None,
) -> None:
    first_user = f"profile.{uuid.uuid4().hex[:12]}"
    second_user = f"profile.{uuid.uuid4().hex[:12]}"
    first_invite = _create_invite()
    second_invite = _create_invite()
    settings.AUTH_REQUIRED = True
    settings.AUTH_COOKIE_SECURE = False
    first_client = TestClient(app)
    second_client = TestClient(app)
    try:
        first_registration = first_client.post(
            "/api/v1/auth/register",
            headers={"Origin": _ORIGIN},
            json={
                "username": first_user,
                "password": _PASSWORD,
                "invite_code": first_invite,
            },
        )
        second_registration = second_client.post(
            "/api/v1/auth/register",
            headers={"Origin": _ORIGIN},
            json={
                "username": second_user,
                "password": _PASSWORD,
                "invite_code": second_invite,
            },
        )
        assert first_registration.status_code == 200
        assert second_registration.status_code == 200
        assert first_registration.json()["user_id"] == first_user
        assert second_registration.json()["user_id"] == second_user

        first_write = first_client.post(
            f"/api/v1/memory/{first_user}/semantic",
            headers={"Origin": _ORIGIN},
            json={"content": "My private marker is blue-orchid.", "metadata": {}},
        )
        second_write = second_client.post(
            f"/api/v1/memory/{second_user}/semantic",
            headers={"Origin": _ORIGIN},
            json={"content": "My private marker is amber-lantern.", "metadata": {}},
        )
        assert first_write.status_code == 201
        assert second_write.status_code == 201

        first_recall = first_client.get(
            f"/api/v1/memory/{first_user}/search",
            params={"query": "blue-orchid marker", "top_k": 5},
        )
        second_recall = second_client.get(
            f"/api/v1/memory/{second_user}/search",
            params={"query": "amber-lantern marker", "top_k": 5},
        )
        second_cannot_open_first = second_client.get(f"/api/v1/memory/{first_user}")
        first_cannot_search_second = first_client.get(
            f"/api/v1/memory/{second_user}/search",
            params={"query": "amber-lantern marker"},
        )

        assert first_recall.status_code == 200
        assert [item["content"] for item in first_recall.json()["memories"]] == [
            "My private marker is blue-orchid."
        ]
        assert second_recall.status_code == 200
        assert [item["content"] for item in second_recall.json()["memories"]] == [
            "My private marker is amber-lantern."
        ]
        assert second_cannot_open_first.status_code == 403
        assert first_cannot_search_second.status_code == 403

        with TestClient(app) as reuse_client:
            reused = reuse_client.post(
                "/api/v1/auth/register",
                headers={"Origin": _ORIGIN},
                json={
                    "username": f"reuse.{uuid.uuid4().hex[:12]}",
                    "password": _PASSWORD,
                    "invite_code": first_invite,
                },
            )
        assert reused.status_code == 400

        logged_out = first_client.post(
            "/api/v1/auth/logout",
            headers={"Origin": _ORIGIN},
        )
        after_logout = first_client.get("/api/v1/auth/session")
        assert logged_out.status_code == 204
        assert after_logout.status_code == 401

        with SessionLocal() as session:
            first_account = session.get(UserAccount, first_user)
            consumed_invite = session.scalar(
                select(RegistrationInvite).where(
                    RegistrationInvite.token_digest
                    == digest_registration_invite(first_invite)
                )
            )
            assert first_account is not None
            assert first_account.password_hash != _PASSWORD
            assert consumed_invite is not None
            assert consumed_invite.consumed_by_user_id == first_user
            assert consumed_invite.consumed_at is not None
    finally:
        first_client.close()
        second_client.close()
        settings.AUTH_REQUIRED = False
        settings.AUTH_COOKIE_SECURE = False
        _cleanup((first_user, second_user), (first_invite, second_invite))
