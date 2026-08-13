from typing import Any

import pytest

from backend.agents.supervisor import MainSupervisorAgent
from backend.core.llm import LLMClient
from backend.services.conversation_service import ConversationService
from backend.services.main_action_selector import DelegateAction, MainAction


class StubLlm(LLMClient):
    """Fail if a deterministic delegation accidentally calls the main model."""

    # Reject unexpected plain-text generation.
    def generate_text(self, prompt: str, max_tokens: int = 1024) -> str:
        raise AssertionError("Main model should not run for explicit delegation")

    # Reject unexpected buffered chat generation.
    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        raise AssertionError("Main model should not run for explicit delegation")

    # Reject unexpected streaming chat generation.
    def stream_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
    ):
        raise AssertionError("Main model should not run for explicit delegation")
        yield ""


class StubRepository:
    """Capture the delegated conversation turn without a database."""

    # Start with no earlier conversation turns.
    async def get_history(self, *args: Any) -> list[dict[str, Any]]:
        return []

    # Record the final chat turn for assertions.
    async def save_turn(
        self,
        conversation_id: str,
        turn: dict[str, Any],
    ) -> None:
        self.saved = (conversation_id, turn)


class StubTracer:
    """Provide stable trace evidence without external telemetry."""

    # Return one deterministic request trace.
    def start_trace(self, user_id: str) -> str:
        return "33333333-3333-4333-8333-333333333333"

    # Ignore unused trace steps in the delegation-only path.
    def log_step(self, *args: Any) -> None:
        return None


class StubMainActionSelector:
    """Return one fixed action without a native tool-calling round trip."""

    def __init__(self, action: MainAction) -> None:
        self.action = action

    async def select(
        self,
        user_id: str,
        query: str,
        history: list[dict[str, Any]],
        active_image_artifact_id: str | None,
        query_embedding: list[float] | None = None,
    ) -> MainAction:
        return self.action


class StubJobs:
    """Capture durable presentation work queued by the supervisor."""

    # Return one accepted background job.
    async def enqueue(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        prompt: str,
    ) -> dict[str, Any]:
        self.enqueued = (user_id, conversation_id, trace_id, prompt)
        return {
            "id": "44444444-4444-4444-8444-444444444444",
            "status": "queued",
        }


# Route explicit and ordinary prompts through the typed first-step graph.
@pytest.mark.asyncio
async def test_supervisor_routes_only_explicit_presentation_creation() -> None:
    supervisor = MainSupervisorAgent()

    delegated = await supervisor.decide(
        "Put together a six-slide deck explaining battery storage."
    )
    response = await supervisor.decide("What is two plus two?")

    assert delegated.action == "delegate_agent"
    assert delegated.capability_id == "presentation_agent"
    assert response.action == "respond"


# Queue a presentation without running the main response model in the request.
@pytest.mark.asyncio
async def test_conversation_delegates_presentation_to_durable_job() -> None:
    repository = StubRepository()
    jobs = StubJobs()
    service = ConversationService(
        memory=object(),  # type: ignore[arg-type]
        llm=StubLlm(),
        repository=repository,  # type: ignore[arg-type]
        tracer=StubTracer(),  # type: ignore[arg-type]
        main_action_selector=StubMainActionSelector(  # type: ignore[arg-type]
            DelegateAction(capability_id="presentation_agent")
        ),
        presentation_jobs=jobs,  # type: ignore[arg-type]
        presentation_model="qualified/presentation-model",
    )

    events = [
        event
        async for event in service.process_request(
            "ani.mallya",
            "Create a presentation about horses with exactly 2 slides.",
            "22222222-2222-4222-8222-222222222222",
            {},
        )
    ]

    assert [event["event"] for event in events] == [
        "start",
        "agent_started",
        "agent_finished",
        "delta",
        "done",
    ]
    assert events[1]["data"]["model"] == "qualified/presentation-model"
    assert events[2]["data"]["status"] == "queued"
    assert jobs.enqueued[3].endswith("exactly 2 slides.")
    assert repository.saved[1]["metadata"]["presentation_job_id"] == (
        "44444444-4444-4444-8444-444444444444"
    )
