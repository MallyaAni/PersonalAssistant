"""Tests for the provider-neutral inference benchmark."""

from collections.abc import Iterator
from typing import Any

import pytest

from backend.artifacts.types import VisionAnalysis
from backend.cli import benchmark_inference
from backend.core.interfaces import VisionProvider
from backend.core.llm import InferenceProvider
from backend.embeddings.base import EmbeddingProvider
from backend.services.inference_benchmark_service import (
    InferenceBenchmarkService,
    InferenceBenchmarkThresholds,
)


class FakeInferenceProvider(InferenceProvider):
    """Return deterministic text, stream, and native-tool benchmark outputs."""

    # Return a small deterministic completion for the unused text shortcut.
    def generate_text(self, prompt: str, max_tokens: int = 1024) -> str:
        return "ready"

    # Return the exact structured presentation benchmark response.
    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        return {
            "content": '{"status":"ready","count":2}',
            "model": "fake-presentation",
        }

    # Yield multiple chunks so streaming metrics exercise chunk aggregation.
    def stream_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
    ) -> Iterator[str]:
        yield "1 2 3 "
        yield "4 5 6"

    # Return one exact native call without executing any capability.
    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 256,
    ) -> dict[str, Any]:
        return {
            "tool_calls": [
                {
                    "function": {
                        "name": "record_benchmark_marker",
                        "arguments": '{"marker":"anios-benchmark-ok"}',
                    }
                }
            ]
        }


class BrokenStreamInferenceProvider(FakeInferenceProvider):
    """Simulate a provider stream that fails after emitting one chunk."""

    # Emit partial output and then fail before terminal stream completion.
    def stream_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
    ) -> Iterator[str]:
        yield "partial"
        raise ValueError("stream ended before terminal marker")


class FakeEmbeddingProvider(EmbeddingProvider):
    """Return deterministic finite vectors for batch validation."""

    # Embed one document into the fixed test dimension.
    def embed_text(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    # Embed one query into the fixed test dimension.
    def embed_query(self, query: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    # Preserve the requested batch size with fixed finite vectors.
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeVisionProvider(VisionProvider):
    """Recognize the benchmark fixture without external inference."""

    # Return the exact grounded marker expected for the owned fixture.
    async def analyze(
        self,
        prompt: str,
        content: bytes,
        mime_type: str,
    ) -> VisionAnalysis:
        return VisionAnalysis(
            content="RED_SQUARE",
            model="fake-vision",
            metadata={},
        )

    # Delegate threaded analysis to the same deterministic fixture response.
    async def analyze_thread(
        self,
        content: bytes,
        mime_type: str,
        history: list[dict[str, str]],
        prompt: str,
    ) -> VisionAnalysis:
        return await self.analyze(prompt, content, mime_type)


# Build the service with deterministic neutral provider test doubles.
def _service(
    main: InferenceProvider | None = None,
) -> InferenceBenchmarkService:
    return InferenceBenchmarkService(
        main=main or FakeInferenceProvider(),
        presentation=FakeInferenceProvider(),
        embedding=FakeEmbeddingProvider(),
        vision=FakeVisionProvider(),
        embedding_dimension=3,
        thresholds=InferenceBenchmarkThresholds(),
    )


# Verify every role passes and the report excludes raw benchmark content.
@pytest.mark.asyncio
async def test_benchmark_reports_sanitized_metrics_for_every_role() -> None:
    report = await _service().run(
        {
            "provider_name": "fake-runtime",
            "roles": {},
            "hardware": {},
        }
    )

    assert report["summary"] == {
        "passed": 5,
        "total": 5,
        "overall_passed": True,
    }
    assert report["results"]["main_stream"]["terminal_stream_observed"] is True
    assert report["results"]["native_tool"]["arguments_valid"] is True
    assert report["results"]["presentation_buffered"]["structured_output_valid"] is True
    assert report["results"]["embedding_batch"]["dimensions"] == [3]
    assert len(report["results"]["vision"]["fixture_sha256"]) == 64
    encoded = str(report)
    assert "A benchmark document" not in encoded
    assert "anios-benchmark-ok" not in encoded
    assert '"status":"ready"' not in encoded


# Verify a partial stream is failed instead of being mistaken for completion.
@pytest.mark.asyncio
async def test_benchmark_fails_stream_without_terminal_completion() -> None:
    report = await _service(BrokenStreamInferenceProvider()).run(
        {"provider_name": "fake-runtime"}
    )

    result = report["results"]["main_stream"]
    assert result["passed"] is False
    assert result["error_type"] == "ValueError"
    assert "terminal_stream_observed" not in result
    assert report["summary"]["overall_passed"] is False


# Verify CLI threshold failures produce a nonzero automation-friendly exit code.
def test_cli_returns_nonzero_when_benchmark_thresholds_fail(monkeypatch: Any) -> None:
    # Return one already-sanitized failed report without calling a real runtime.
    async def fake_run(args: Any) -> dict[str, Any]:
        return {"summary": {"overall_passed": False}}

    monkeypatch.setattr(benchmark_inference, "_run", fake_run)

    assert benchmark_inference.main([]) == 1


# Verify configured URLs cannot leak credentials or provider-specific paths.
def test_safe_endpoint_removes_credentials_paths_and_queries() -> None:
    value = benchmark_inference._safe_endpoint(
        "https://user:secret@example.test:8443/private?token=secret"
    )

    assert value == "https://example.test:8443"
