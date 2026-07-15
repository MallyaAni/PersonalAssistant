import os

import pytest
from fastapi.testclient import TestClient

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.main import app
from backend.services.impl_placeholder import (
    MockConversationRepository,
    MockContextBuilder,
    MockInternetService,
    MockKnowledgeService,
    MockMemoryService,
    MockNotificationService,
    MockStreamer,
    MockToolService,
    MockTracer,
)
from backend.services.conversation_service import ConversationService


class CapturingConversationRepository(MockConversationRepository):
    def __init__(self):
        self.saved_turns = []

    async def save_turn(self, conversation_id, turn):
        self.saved_turns.append((conversation_id, turn))


def test_chat_openapi_has_no_dependency_query_parameters():
    with TestClient(app) as client:
        operation = client.get("/openapi.json").json()["paths"]["/api/v1/chat"]["post"]

    assert operation.get("parameters", []) == []


def test_chat_reaches_service_and_completes_stream(monkeypatch):
    captured = {}

    async def fake_process_request(self, user_id, query):
        captured.update(user_id=user_id, query=query)
        yield "validation ok"

    monkeypatch.setattr(ConversationService, "process_request", fake_process_request)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={
                "user_id": "validation_user",
                "query": "Reply with: validation ok",
                "metadata": {},
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text == "validation ok"
    assert captured == {
        "user_id": "validation_user",
        "query": "Reply with: validation ok",
    }


@pytest.mark.asyncio
async def test_conversation_service_streams_and_persists_required_turn_fields():
    repository = CapturingConversationRepository()
    service = ConversationService(
        memory=MockMemoryService(),
        knowledge=MockKnowledgeService(),
        internet=MockInternetService(),
        notifications=MockNotificationService(),
        tools=MockToolService(),
        repository=repository,
        context_builder=MockContextBuilder(),
        streamer=MockStreamer(),
        tracer=MockTracer(),
    )

    chunks = [
        chunk
        async for chunk in service.process_request(
            "validation_user",
            "Reply with: validation ok",
        )
    ]

    assert len(chunks) == 1
    assert "Response: Thinking..." in chunks[0]
    assert len(repository.saved_turns) == 1
    conversation_id, turn = repository.saved_turns[0]
    assert conversation_id
    assert turn == {
        "user_id": "validation_user",
        "query": "Reply with: validation ok",
        "response": "Thinking...",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"query": "hello", "metadata": {}},
        {"user_id": "validation_user", "metadata": {}},
    ],
)
def test_chat_rejects_missing_required_fields(payload):
    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json=payload)

    assert response.status_code == 400
    assert response.json() == {"detail": "Missing user_id or query in request body"}
