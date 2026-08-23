import os
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.config.settings import settings
from backend.core.auth_dependencies import get_login_rate_limiter
from backend.database.session import SessionLocal
from backend.main import app
from backend.models.auth import UserAccount, UserSession
from backend.services.auth_service import hash_password
from backend.services.login_rate_limiter import LoginRateLimitDecision

_ORIGIN = "http://127.0.0.1:5173"
_PASSWORD = "A valid acceptance password 123!"


class _TestLoginRateLimiter:
    # Start each API test with an open deterministic login boundary.
    def __init__(self) -> None:
        self.decision = LoginRateLimitDecision(True)
        self.failures = 0
        self.clears = 0

    # Return the test-selected admission result without contacting Redis.
    async def before_attempt(self, username: str) -> LoginRateLimitDecision:
        return self.decision

    # Record that invalid credentials reached the failure accounting boundary.
    async def record_failure(self, username: str) -> None:
        self.failures += 1

    # Record that a valid login cleared its prior failure window.
    async def clear_failures(self, username: str) -> None:
        self.clears += 1


# Replace shared Redis with one isolated limiter for every API test.
@pytest.fixture(autouse=True)
def login_rate_limiter() -> Generator[_TestLoginRateLimiter, None, None]:
    limiter = _TestLoginRateLimiter()

    # Return the same isolated limiter throughout one TestClient lifecycle.
    def provide_limiter() -> _TestLoginRateLimiter:
        return limiter

    app.dependency_overrides[get_login_rate_limiter] = provide_limiter
    try:
        yield limiter
    finally:
        app.dependency_overrides.pop(get_login_rate_limiter, None)


# Insert one isolated invite account without creating or changing owned user data.
def _create_test_account(user_id: str, username: str | None = None) -> None:
    with SessionLocal() as session:
        session.add(
            UserAccount(
                user_id=user_id,
                username=username or user_id,
                password_hash=hash_password(_PASSWORD),
                is_active=True,
            )
        )
        session.commit()


# Remove only account and session rows created by this isolated test.
def _remove_test_account(user_id: str) -> None:
    with SessionLocal() as session:
        session.execute(delete(UserSession).where(UserSession.user_id == user_id))
        session.execute(delete(UserAccount).where(UserAccount.user_id == user_id))
        session.commit()


# Verify login, ownership binding, origin checks, and logout through the public API.
def test_password_login_binds_cookie_session_to_one_user_and_revokes_logout() -> None:
    user_id = f"auth_{uuid.uuid4().hex[:12]}"
    username = f"login_{uuid.uuid4().hex[:12]}"
    _create_test_account(user_id, username)
    settings.AUTH_REQUIRED = True
    settings.AUTH_COOKIE_SECURE = False
    try:
        with TestClient(app) as client:
            missing_origin = client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": _PASSWORD},
            )
            invalid = client.post(
                "/api/v1/auth/login",
                headers={"Origin": _ORIGIN},
                json={"username": username, "password": "incorrect-password"},
            )
            logged_in = client.post(
                "/api/v1/auth/login",
                headers={"Origin": _ORIGIN},
                json={"username": username.upper(), "password": _PASSWORD},
            )
            session_response = client.get("/api/v1/auth/session")
            own_memory = client.get(f"/api/v1/memory/{user_id}")
            other_memory = client.get("/api/v1/memory/ani.mallya")
            unsafe_without_origin = client.put(
                f"/api/v1/memory/{user_id}/profile",
                json={"name": "Blocked", "preferences": {}},
            )
            logged_out = client.post(
                "/api/v1/auth/logout",
                headers={"Origin": _ORIGIN},
            )
            after_logout = client.get("/api/v1/auth/session")

        assert missing_origin.status_code == 403
        assert invalid.status_code == 401
        assert "set-cookie" not in invalid.headers
        assert logged_in.status_code == 200
        cookie = logged_in.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=lax" in cookie
        assert logged_in.json()["user_id"] == user_id
        assert session_response.status_code == 200
        assert session_response.json()["user_id"] == user_id
        assert own_memory.status_code == 200
        assert other_memory.status_code == 403
        assert unsafe_without_origin.status_code == 403
        assert logged_out.status_code == 204
        assert after_logout.status_code == 401

        with SessionLocal() as session:
            stored_sessions = session.scalars(
                select(UserSession).where(UserSession.user_id == user_id)
            ).all()
            assert len(stored_sessions) == 1
            assert stored_sessions[0].revoked_at is not None
    finally:
        settings.AUTH_REQUIRED = False
        settings.AUTH_COOKIE_SECURE = False
        _remove_test_account(user_id)


# Verify a disabled invite cannot authenticate with its still-correct password.
def test_disabled_account_cannot_login() -> None:
    user_id = f"auth_{uuid.uuid4().hex[:12]}"
    _create_test_account(user_id)
    settings.AUTH_REQUIRED = True
    try:
        with SessionLocal() as session:
            account = session.get(UserAccount, user_id)
            assert account is not None
            account.is_active = False
            session.commit()
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/login",
                headers={"Origin": _ORIGIN},
                json={"username": user_id, "password": _PASSWORD},
            )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid username or password"
    finally:
        settings.AUTH_REQUIRED = False
        _remove_test_account(user_id)


# Verify throttled credentials stop before authentication and expose retry time.
def test_login_rate_limit_returns_retry_after(
    login_rate_limiter: _TestLoginRateLimiter,
) -> None:
    limiter = login_rate_limiter
    limiter.decision = LoginRateLimitDecision(False, 47)
    settings.AUTH_REQUIRED = True
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/login",
                headers={"Origin": _ORIGIN},
                json={"username": "rate_limited", "password": _PASSWORD},
            )
        assert response.status_code == 429
        assert response.headers["retry-after"] == "47"
        assert response.json()["detail"] == "Too many login attempts. Try again later."
    finally:
        settings.AUTH_REQUIRED = False
