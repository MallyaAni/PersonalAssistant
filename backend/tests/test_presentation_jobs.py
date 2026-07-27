import os
from typing import Any

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

import pytest
from fastapi.testclient import TestClient

from backend.core.dependencies import get_presentation_job_service
from backend.main import app
from backend.services.presentation_job_service import PresentationJobService


class StubJobRepository:
    """Capture durable job requests without opening PostgreSQL."""

    # Initialize captured enqueue inputs and one configurable job.
    def __init__(self) -> None:
        self.enqueued: tuple[Any, ...] | None = None
        self.job: dict[str, Any] | None = None
        self.cancelled: tuple[str, str] | None = None

    # Return one queued handle after capturing private creation inputs.
    async def enqueue(self, *args: Any) -> dict[str, Any]:
        self.enqueued = args
        return {
            "id": "11111111-1111-4111-8111-111111111111",
            "presentation_id": "22222222-2222-4222-8222-222222222222",
            "revision_id": "33333333-3333-4333-8333-333333333333",
            "user_id": "ani.mallya",
            "status": "queued",
            "expected_slide_count": args[-1],
            "attempt_count": 0,
            "cancel_requested": False,
            "error_code": None,
            "draft_specification": None,
        }

    # Return the configured owned job.
    async def get_owned(
        self,
        user_id: str,
        job_id: str,
    ) -> dict[str, Any] | None:
        return self.job

    # Capture one cooperative cancellation request.
    async def request_cancel(self, user_id: str, job_id: str) -> bool:
        self.cancelled = (user_id, job_id)
        return True


class StubPresentationRepository:
    """Return one ready presentation for terminal job hydration."""

    # Return deterministic ready deck metadata for the requested owner.
    async def get_owned(
        self,
        user_id: str,
        presentation_id: str,
    ) -> dict[str, Any]:
        return {
            "id": presentation_id,
            "user_id": user_id,
            "title": "Ready deck",
        }


class StubApiJobService:
    """Serve queued API jobs without invoking a model."""

    # Queue a deterministic job handle for the API contract.
    async def enqueue(self, *_: Any) -> dict[str, Any]:
        return {
            "id": "11111111-1111-4111-8111-111111111111",
            "presentation_id": "22222222-2222-4222-8222-222222222222",
            "revision_id": "33333333-3333-4333-8333-333333333333",
            "user_id": "ani.mallya",
            "status": "queued",
            "expected_slide_count": 6,
            "attempt_count": 0,
            "cancel_requested": False,
            "error_code": None,
            "draft_specification": None,
        }

    # Return no job because this test exercises only the queue boundary.
    async def get(self, *_: Any) -> None:
        return None

    # Accept one deterministic cancellation request.
    async def cancel(self, *_: Any) -> bool:
        return True


# Verify enqueue returns immediately with a durable handle and parsed slide count.
@pytest.mark.asyncio
async def test_job_service_queues_without_running_the_presentation_agent() -> None:
    jobs = StubJobRepository()
    service = PresentationJobService(
        jobs,  # type: ignore[arg-type]
        StubPresentationRepository(),  # type: ignore[arg-type]
        "lm_studio",
        "google/gemma-4-12b",
    )

    queued = await service.enqueue(
        "ani.mallya",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "Create a presentation on horses, 6 slides",
    )

    assert queued["status"] == "queued"
    assert queued["expected_slide_count"] == 6
    assert jobs.enqueued is not None
    assert jobs.enqueued[3] == "Create a presentation on horses, 6 slides"


# Verify a terminal job reconnect includes its promoted presentation.
@pytest.mark.asyncio
async def test_job_service_hydrates_the_ready_presentation() -> None:
    jobs = StubJobRepository()
    jobs.job = {
        "id": "11111111-1111-4111-8111-111111111111",
        "presentation_id": "22222222-2222-4222-8222-222222222222",
        "status": "ready",
    }
    service = PresentationJobService(
        jobs,  # type: ignore[arg-type]
        StubPresentationRepository(),  # type: ignore[arg-type]
        "lm_studio",
        "google/gemma-4-12b",
    )

    ready = await service.get(
        "ani.mallya",
        "11111111-1111-4111-8111-111111111111",
    )

    assert ready is not None
    assert ready["presentation"]["title"] == "Ready deck"


# Verify POST returns 202 and a job handle rather than waiting for deck generation.
def test_presentation_api_returns_an_accepted_job() -> None:
    app.dependency_overrides[get_presentation_job_service] = StubApiJobService
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/presentations",
                json={
                    "user_id": "ani.mallya",
                    "conversation_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                    "prompt": "Create a presentation on horses, 6 slides",
                },
            )
        assert response.status_code == 202
        assert response.json()["status"] == "queued"
        assert response.json()["expected_slide_count"] == 6
    finally:
        app.dependency_overrides.pop(get_presentation_job_service, None)
