import asyncio
import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.agents.diagram import DiagramAgent
from backend.artifacts.diagram import (
    LLMDiagramProvider,
    is_diagram_request,
    validate_diagram_specification,
)
from backend.artifacts.types import DiagramSpecification
from backend.core.dependencies import (
    get_artifact_repository,
    get_conversation_repository,
)
from backend.core.interfaces import ArtifactRepository, DiagramProvider
from backend.core.llm import LLMClient
from backend.main import app
from backend.services.conversation_service import ConversationService
from backend.services.diagram_artifact_service import DiagramArtifactService
from backend.tests.doubles import (
    StubConversationRepository,
    StubMemoryService,
    StubTracer,
)


class CapturingArtifactRepository(ArtifactRepository):
    # Initialize an in-memory artifact lifecycle for deterministic tests.
    def __init__(self) -> None:
        self.artifact_id = str(uuid.uuid4())
        self.status = "missing"
        self.records: list[dict[str, Any]] = []

    # Store one pending record with stable test provenance.
    async def create_pending(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        provider: str,
        model: str | None,
    ) -> dict[str, Any]:
        record = {
            "id": self.artifact_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "trace_id": trace_id,
            "kind": "diagram",
            "status": "pending",
            "provider": provider,
            "model": model,
        }
        self.status = "pending"
        self.records = [record]
        return record

    # Replace the pending record with validated ready source.
    async def mark_ready(
        self,
        artifact_id: str,
        user_id: str,
        specification: DiagramSpecification,
    ) -> dict[str, Any]:
        self.status = "ready"
        record = {
            **self.records[0],
            "status": "ready",
            "title": specification.title,
            "source_format": "mermaid",
            "source": specification.source,
            "mime_type": "image/svg+xml",
            "error_code": None,
            "metadata": {"diagram_type": specification.diagram_type},
        }
        self.records = [record]
        return record

    # Replace the pending record with a sanitized failure state.
    async def mark_failed(
        self,
        artifact_id: str,
        user_id: str,
        error_code: str,
    ) -> dict[str, Any]:
        self.status = "failed"
        record = {
            **self.records[0],
            "status": "failed",
            "error_code": error_code,
        }
        self.records = [record]
        return record

    # Return records only for the matching user conversation.
    async def list_for_conversation(
        self,
        user_id: str,
        conversation_id: str,
    ) -> list[dict[str, Any]]:
        return [
            record
            for record in self.records
            if record["user_id"] == user_id
            and record["conversation_id"] == conversation_id
        ]

    # Return recent records only for the matching user.
    async def list_for_user(
        self,
        user_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return [
            record for record in reversed(self.records) if record["user_id"] == user_id
        ][:limit]

    # Delete a record only for its owning user.
    async def delete(self, user_id: str, artifact_id: str) -> bool:
        before = len(self.records)
        self.records = [
            record
            for record in self.records
            if not (record["user_id"] == user_id and record["id"] == artifact_id)
        ]
        return len(self.records) < before

    # Return one matching artifact for shared diagram and binary deletion routes.
    async def get_owned(
        self,
        user_id: str,
        artifact_id: str,
    ) -> dict[str, Any] | None:
        for record in self.records:
            if record["user_id"] == user_id and record["id"] == artifact_id:
                return {**record, "_storage_key": record.get("_storage_key")}
        return None


class StaticDiagramProvider(DiagramProvider):
    # Return a fixed valid flowchart for deterministic orchestration tests.
    async def generate(self, query: str) -> DiagramSpecification:
        return DiagramSpecification(
            title="Validation flow",
            diagram_type="flowchart",
            source="flowchart TD\n  Start --> Validate\n  Validate --> Complete",
        )


class FailingDiagramProvider(DiagramProvider):
    # Raise a provider failure without returning unsafe partial source.
    async def generate(self, query: str) -> DiagramSpecification:
        raise RuntimeError("private provider detail")


class BlockingDiagramProvider(DiagramProvider):
    # Wait indefinitely so the test can cancel generation after pending persistence.
    async def generate(self, query: str) -> DiagramSpecification:
        await asyncio.Event().wait()
        raise AssertionError("cancelled provider unexpectedly resumed")


class CapturingConversationRepository(StubConversationRepository):
    # Initialize persisted turns for deterministic service assertions.
    def __init__(self) -> None:
        self.saved_turns: list[tuple[str, dict[str, Any]]] = []
        self.history: list[dict[str, Any]] = []

    # Return owned persisted turns for route-level restoration tests.
    async def get_history(
        self,
        conversation_id: str,
        user_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return [
            turn
            for turn in self.history
            if turn["conversation_id"] == conversation_id and turn["user_id"] == user_id
        ][:limit]

    # Capture one saved turn without a database dependency.
    async def save_turn(
        self,
        conversation_id: str,
        turn: dict[str, Any],
    ) -> None:
        self.saved_turns.append((conversation_id, turn))


class NoopLLM(LLMClient):
    # Return unused fixed text for the abstract generation contract.
    def generate_text(self, prompt: str, max_tokens: int = 1024) -> str:
        return "unused"

    # Return unused fixed text for the abstract chat contract.
    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        return {"content": "unused"}

    # Yield unused fixed text for the abstract streaming contract.
    def stream_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
    ) -> Iterator[str]:
        yield "unused"


class JsonDiagramLLM(NoopLLM):
    # Return a JSON diagram payload for the real provider parser.
    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        return {
            "content": (
                '{"title":"JSON flow","diagram_type":"flowchart",'
                '"source":"flowchart TD\\n  A --> B"}'
            )
        }


class RetryingJsonDiagramLLM(JsonDiagramLLM):
    # Initialize a provider double that emits one invalid JSON escape first.
    def __init__(self) -> None:
        self.calls = 0

    # Return invalid JSON once and a safe diagram on the bounded retry.
    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return {
                "content": (
                    '{"title":"Broken","diagram_type":"flowchart TD",'
                    '"source":"Start \\q Finish"}'
                )
            }
        return super().chat(messages, max_tokens)


# Verify deterministic routing requires an explicit diagram-generation request.
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Create a flowchart showing intake and review", True),
        ("Visualize this process as a diagram", True),
        ("Explain what an architecture diagram is", False),
        ("Tell me about flowcharts", False),
        ("Generate an image of a mountain", False),
    ],
)
def test_diagram_request_classification(query: str, expected: bool) -> None:
    assert is_diagram_request(query) is expected


# Verify the validator accepts bounded passive Mermaid source.
def test_diagram_validator_accepts_safe_source() -> None:
    specification = validate_diagram_specification(
        {
            "title": "Safe flow",
            "source": "flowchart TD\n  Start --> Finish",
        }
    )

    assert specification.diagram_type == "flowchart"
    assert specification.source.endswith("Start --> Finish")


# Verify a safe declared type repairs local-model output that omits the Mermaid header.
def test_diagram_validator_prepends_missing_declared_type() -> None:
    specification = validate_diagram_specification(
        {
            "title": "Provider flow",
            "diagram_type": "flowchart TD",
            "source": "Start[Start] --> Finish[Finish]",
        }
    )

    assert specification.diagram_type == "flowchart"
    assert specification.source == ("flowchart TD\nStart[Start] --> Finish[Finish]")


# Verify an unrecognized model declaration cannot authorize arbitrary source.
def test_diagram_validator_rejects_unknown_declared_type() -> None:
    with pytest.raises(ValueError, match="type is not supported"):
        validate_diagram_specification(
            {
                "title": "Unknown",
                "diagram_type": "custom diagram",
                "source": "Start --> Finish",
            }
        )


# Verify active Mermaid directives and remote links are rejected.
@pytest.mark.parametrize(
    "source",
    [
        "flowchart TD\n  A --> B\n  click A https://example.com",
        "flowchart TD\n  %%{init: {'securityLevel': 'loose'}}%%\n  A --> B",
        "flowchart TD\n  A[<script>alert(1)</script>] --> B",
    ],
)
def test_diagram_validator_rejects_active_content(source: str) -> None:
    with pytest.raises(ValueError, match="unsupported active content"):
        validate_diagram_specification({"title": "Unsafe", "source": source})


# Verify the local LLM adapter parses JSON into a validated specification.
@pytest.mark.asyncio
async def test_llm_diagram_provider_parses_valid_json() -> None:
    provider = LLMDiagramProvider(JsonDiagramLLM(), "test-model")

    specification = await provider.generate("Create a flowchart of A to B")

    assert specification == DiagramSpecification(
        title="JSON flow",
        diagram_type="flowchart",
        source="flowchart TD\n  A --> B",
    )


# Verify one malformed local-model response receives one bounded correction retry.
@pytest.mark.asyncio
async def test_llm_diagram_provider_retries_invalid_json_once() -> None:
    llm = RetryingJsonDiagramLLM()
    provider = LLMDiagramProvider(llm, "test-model")

    specification = await provider.generate("Create a flowchart of A to B")

    assert specification.title == "JSON flow"
    assert llm.calls == 2


# Verify the focused diagram graph returns the provider's validated specification.
@pytest.mark.asyncio
async def test_diagram_agent_runs_provider_through_graph() -> None:
    specification = await DiagramAgent(StaticDiagramProvider()).generate(
        "Create a flowchart of start to complete"
    )

    assert specification.title == "Validation flow"
    assert specification.source.endswith("Validate --> Complete")


# Verify an explicit diagram request streams and persists a ready artifact.
@pytest.mark.asyncio
async def test_conversation_service_streams_ready_diagram_artifact() -> None:
    artifacts = CapturingArtifactRepository()
    conversations = CapturingConversationRepository()
    service = ConversationService(
        memory=StubMemoryService(),
        llm=NoopLLM(),
        repository=conversations,
        tracer=StubTracer(),
        diagram_artifacts=DiagramArtifactService(
            DiagramAgent(StaticDiagramProvider()),
            artifacts,
            "test_provider",
            "test_model",
        ),
    )

    events = [
        event
        async for event in service.process_request(
            "diagram_user",
            "Create a flowchart showing start to complete",
            "77777777-7777-4777-8777-777777777777",
        )
    ]

    assert [event["event"] for event in events] == [
        "start",
        "artifact_started",
        "delta",
        "artifact_ready",
        "done",
    ]
    assert events[-2]["data"]["source_format"] == "mermaid"
    assert artifacts.status == "ready"
    assert conversations.saved_turns[0][1]["metadata"] == {
        "artifact_ids": [artifacts.artifact_id],
        "artifact_status": "ready",
    }


# Verify provider failure is persisted, visible, sanitized, and terminal.
@pytest.mark.asyncio
async def test_conversation_service_streams_failed_diagram_artifact() -> None:
    artifacts = CapturingArtifactRepository()
    conversations = CapturingConversationRepository()
    service = ConversationService(
        memory=StubMemoryService(),
        llm=NoopLLM(),
        repository=conversations,
        tracer=StubTracer(),
        diagram_artifacts=DiagramArtifactService(
            DiagramAgent(FailingDiagramProvider()),
            artifacts,
            "test_provider",
            "test_model",
        ),
    )

    events = [
        event
        async for event in service.process_request(
            "diagram_user",
            "Create a flowchart showing failure",
            "88888888-8888-4888-8888-888888888888",
        )
    ]

    assert [event["event"] for event in events] == [
        "start",
        "artifact_started",
        "delta",
        "artifact_error",
        "done",
    ]
    assert events[-2]["data"]["message"] == "Unable to create the diagram."
    assert "private provider detail" not in str(events)
    assert artifacts.status == "failed"
    assert conversations.saved_turns[0][1]["metadata"]["artifact_status"] == ("failed")


# Verify cancelling provider work leaves a terminal sanitized artifact record.
@pytest.mark.asyncio
async def test_cancelled_diagram_generation_marks_pending_artifact_failed() -> None:
    artifacts = CapturingArtifactRepository()
    service = ConversationService(
        memory=StubMemoryService(),
        llm=NoopLLM(),
        repository=CapturingConversationRepository(),
        tracer=StubTracer(),
        diagram_artifacts=DiagramArtifactService(
            DiagramAgent(BlockingDiagramProvider()),
            artifacts,
            provider_name="blocking-test",
            model_name=None,
        ),
    )
    stream = service.process_request(
        "cancel_user",
        "Create a flowchart for cancellation",
        "99999999-9999-4999-8999-999999999999",
    )
    assert (await anext(stream))["event"] == "start"
    assert (await anext(stream))["event"] == "artifact_started"
    pending_generation = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    pending_generation.cancel()

    with pytest.raises(asyncio.CancelledError):
        await pending_generation

    assert artifacts.status == "failed"
    assert artifacts.records[0]["error_code"] == "cancelled"


# Verify artifact list and deletion routes preserve user ownership.
def test_artifact_management_routes_are_user_scoped() -> None:
    repository = CapturingArtifactRepository()
    conversation_id = "99999999-9999-4999-8999-999999999999"
    trace_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    repository.records = [
        {
            "id": repository.artifact_id,
            "user_id": "artifact_user",
            "conversation_id": conversation_id,
            "trace_id": trace_id,
            "kind": "diagram",
            "status": "pending",
            "provider": "test_provider",
            "model": "test_model",
        }
    ]

    # Supply the in-memory repository to artifact route dependencies.
    async def repository_override() -> CapturingArtifactRepository:
        return repository

    app.dependency_overrides[get_artifact_repository] = repository_override
    try:
        with TestClient(app) as client:
            user_list = client.get("/api/v1/artifacts/artifact_user")
            isolated_list = client.get("/api/v1/artifacts/other_user")
            listed = client.get(
                f"/api/v1/artifacts/artifact_user/conversations/{conversation_id}"
            )
            cross_user_delete = client.delete(
                f"/api/v1/artifacts/other_user/{repository.artifact_id}"
            )
            deleted = client.delete(
                f"/api/v1/artifacts/artifact_user/{repository.artifact_id}"
            )

        assert user_list.status_code == 200
        assert user_list.json()[0]["id"] == repository.artifact_id
        assert isolated_list.json() == []
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == repository.artifact_id
        assert cross_user_delete.status_code == 404
        assert deleted.status_code == 200
    finally:
        app.dependency_overrides.clear()


# Verify conversation restoration returns only the owned transcript and artifacts.
def test_conversation_snapshot_route_restores_owned_diagram() -> None:
    artifacts = CapturingArtifactRepository()
    conversations = CapturingConversationRepository()
    conversation_id = "99999999-9999-4999-8999-999999999999"
    trace_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    artifact_id = artifacts.artifact_id
    conversations.history = [
        {
            "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "conversation_id": conversation_id,
            "user_id": "artifact_user",
            "query": "Create a flowchart",
            "response": "Created an editable diagram: Restored flow.",
            "metadata": {
                "artifact_ids": [artifact_id],
                "artifact_status": "ready",
            },
        }
    ]
    artifacts.records = [
        {
            "id": artifact_id,
            "user_id": "artifact_user",
            "conversation_id": conversation_id,
            "trace_id": trace_id,
            "kind": "diagram",
            "status": "ready",
            "title": "Restored flow",
            "source_format": "mermaid",
            "source": "flowchart TD\n  Restore --> Complete",
            "mime_type": "image/svg+xml",
            "provider": "test_provider",
            "model": "test_model",
            "error_code": None,
            "metadata": {"diagram_type": "flowchart"},
        }
    ]

    # Supply in-memory repositories to the conversation snapshot endpoint.
    async def conversation_override() -> CapturingConversationRepository:
        return conversations

    # Supply in-memory artifacts to the same snapshot request.
    async def artifact_override() -> CapturingArtifactRepository:
        return artifacts

    app.dependency_overrides[get_conversation_repository] = conversation_override
    app.dependency_overrides[get_artifact_repository] = artifact_override
    try:
        with TestClient(app) as client:
            restored = client.get(
                f"/api/v1/conversations/artifact_user/{conversation_id}"
            )
            isolated = client.get(f"/api/v1/conversations/other_user/{conversation_id}")

        assert restored.status_code == 200
        assert restored.json()["turns"][0]["query"] == "Create a flowchart"
        assert restored.json()["artifacts"][0]["source"].endswith(
            "Restore --> Complete"
        )
        assert isolated.status_code == 200
        assert isolated.json() == {
            "conversation_id": conversation_id,
            "turns": [],
            "artifacts": [],
        }
    finally:
        app.dependency_overrides.clear()
