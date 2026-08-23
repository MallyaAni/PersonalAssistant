import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from typing import Any

import httpx
from fastapi.testclient import TestClient

from backend.core.dependencies import get_image_artifact_service
from backend.main import app


class UnreachableImageService:
    """Stand in for a generation service whose provider process is down."""

    async def generate(self, **_: Any) -> Any:
        raise httpx.ConnectError("All connection attempts failed")


def test_unreachable_image_provider_returns_a_named_reason() -> None:
    # A down ComfyUI is a distinct, actionable condition, not a generic failure.
    app.dependency_overrides[get_image_artifact_service] = UnreachableImageService
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/images/generate",
                json={
                    "user_id": "ani.mallya",
                    "conversation_id": "55555555-5555-4555-8555-555555555555",
                    "prompt": "a cat",
                },
            )
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["reason"] == "image_provider_unreachable"
        assert "ComfyUI" in detail["message"]
    finally:
        app.dependency_overrides.pop(get_image_artifact_service, None)
