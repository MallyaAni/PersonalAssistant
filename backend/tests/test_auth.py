import os

from fastapi.testclient import TestClient

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.main import app


def test_required_authentication_binds_chat_and_memory_to_token_subject():
    settings.AUTH_REQUIRED = True
    own_token = issue_user_token("auth_user")
    other_token = issue_user_token("other_user")
    expired_token = issue_user_token("auth_user", ttl_seconds=-1)

    try:
        with TestClient(app) as client:
            missing = client.get("/api/v1/memory/auth_user")
            invalid = client.get(
                "/api/v1/memory/auth_user",
                headers={"Authorization": f"Bearer {own_token}x"},
            )
            expired = client.get(
                "/api/v1/memory/auth_user",
                headers={"Authorization": f"Bearer {expired_token}"},
            )
            cross_user = client.get(
                "/api/v1/memory/auth_user",
                headers={"Authorization": f"Bearer {other_token}"},
            )
            own_memory = client.get(
                "/api/v1/memory/auth_user",
                headers={"Authorization": f"Bearer {own_token}"},
            )
            cross_user_chat = client.post(
                "/api/v1/chat",
                headers={"Authorization": f"Bearer {other_token}"},
                json={"user_id": "auth_user", "query": "blocked"},
            )

        assert missing.status_code == 401
        assert invalid.status_code == 401
        assert expired.status_code == 401
        assert cross_user.status_code == 403
        assert own_memory.status_code == 200
        assert cross_user_chat.status_code == 403
    finally:
        settings.AUTH_REQUIRED = False
