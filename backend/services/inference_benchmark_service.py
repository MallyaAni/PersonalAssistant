"""Provider-neutral latency and correctness benchmark for local inference roles."""

import asyncio
import hashlib
import io
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from PIL import Image, ImageDraw

from backend.core.interfaces import VisionProvider
from backend.core.llm import InferenceProvider
from backend.embeddings.base import EmbeddingProvider

_TOOL_NAME = "record_benchmark_marker"
_TOOL_MARKER = "anios-benchmark-ok"


@dataclass(frozen=True, slots=True)
class InferenceBenchmarkThresholds:
    """Explicit pass/fail limits for every measured inference role."""

    max_main_ttft_seconds: float = 30.0
    max_main_total_seconds: float = 45.0
    min_main_estimated_tokens_per_second: float = 1.0
    max_tool_seconds: float = 10.0
    max_presentation_seconds: float = 45.0
    max_embedding_batch_seconds: float = 10.0
    max_vision_seconds: float = 30.0


class InferenceBenchmarkService:
    """Exercise qualified inference contracts without knowing their runtime vendor."""

    # Store neutral providers and the explicit limits used to judge one run.
    def __init__(
        self,
        main: InferenceProvider,
        presentation: InferenceProvider,
        embedding: EmbeddingProvider,
        vision: VisionProvider,
        embedding_dimension: int,
        thresholds: InferenceBenchmarkThresholds,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._main = main
        self._presentation = presentation
        self._embedding = embedding
        self._vision = vision
        self._embedding_dimension = embedding_dimension
        self._thresholds = thresholds
        self._clock = clock

    # Run each role sequentially so a single GPU is not distorted by contention.
    async def run(self, identity: dict[str, Any]) -> dict[str, Any]:
        fixture, fixture_sha256 = _vision_fixture()
        results = {
            "main_stream": await asyncio.to_thread(self._measure_main_stream),
            "native_tool": await asyncio.to_thread(self._measure_native_tool),
            "presentation_buffered": await asyncio.to_thread(
                self._measure_presentation
            ),
            "embedding_batch": await asyncio.to_thread(self._measure_embeddings),
            "vision": await self._measure_vision(fixture, fixture_sha256),
        }
        passed = sum(bool(result["passed"]) for result in results.values())
        return {
            "suite": "anios-provider-neutral-inference-benchmark-v1",
            "identity": identity,
            "thresholds": asdict(self._thresholds),
            "results": results,
            "summary": {
                "passed": passed,
                "total": len(results),
                "overall_passed": passed == len(results),
            },
        }

    # Measure first output, completed streaming, and normalized output throughput.
    def _measure_main_stream(self) -> dict[str, Any]:
        started = self._clock()
        first_output: float | None = None
        chunks: list[str] = []
        try:
            stream = self._main.stream_chat(
                [
                    {
                        "role": "system",
                        "content": "Follow the requested output format exactly.",
                    },
                    {
                        "role": "user",
                        "content": (
                            "Return the integers 1 through 64, separated by one "
                            "space, with no other text."
                        ),
                    },
                ],
                max_tokens=128,
            )
            for chunk in stream:
                if first_output is None:
                    first_output = self._clock()
                chunks.append(chunk)
            finished = self._clock()
            output = "".join(chunks)
            estimated_tokens = _estimated_token_count(output)
            total_seconds = finished - started
            ttft_seconds = (first_output or finished) - started
            throughput = estimated_tokens / max(total_seconds, 0.000_001)
            passed = (
                bool(output.strip())
                and first_output is not None
                and ttft_seconds <= self._thresholds.max_main_ttft_seconds
                and total_seconds <= self._thresholds.max_main_total_seconds
                and throughput >= self._thresholds.min_main_estimated_tokens_per_second
            )
            return {
                "passed": passed,
                "ttft_seconds": round(ttft_seconds, 3),
                "total_seconds": round(total_seconds, 3),
                "chunk_count": len(chunks),
                "output_characters": len(output),
                "estimated_output_tokens": estimated_tokens,
                "estimated_tokens_per_second": round(throughput, 3),
                "terminal_stream_observed": True,
            }
        except Exception as exc:
            return _failure_result(started, self._clock(), exc)

    # Verify one native tool decision and its bounded structured arguments.
    def _measure_native_tool(self) -> dict[str, Any]:
        started = self._clock()
        try:
            message = self._main.chat_with_tools(
                [
                    {
                        "role": "system",
                        "content": "Use the supplied function exactly as requested.",
                    },
                    {
                        "role": "user",
                        "content": (
                            "Call record_benchmark_marker exactly once with marker "
                            "anios-benchmark-ok. Do not answer in text."
                        ),
                    },
                ],
                [_benchmark_tool()],
                max_tokens=64,
            )
            selected_name, arguments_valid = _validate_tool_message(message)
            elapsed = self._clock() - started
            passed = (
                selected_name == _TOOL_NAME
                and arguments_valid
                and elapsed <= self._thresholds.max_tool_seconds
            )
            return {
                "passed": passed,
                "latency_seconds": round(elapsed, 3),
                "selected_expected_tool": selected_name == _TOOL_NAME,
                "arguments_valid": arguments_valid,
            }
        except Exception as exc:
            return _failure_result(started, self._clock(), exc)

    # Measure buffered presentation-role inference and exact JSON correctness.
    def _measure_presentation(self) -> dict[str, Any]:
        started = self._clock()
        try:
            response = self._presentation.chat(
                [
                    {
                        "role": "system",
                        "content": "Return only compact JSON with no markdown.",
                    },
                    {
                        "role": "user",
                        "content": ('Return exactly {"status":"ready","count":2}.'),
                    },
                ],
                max_tokens=64,
            )
            content = response.get("content")
            parsed = json.loads(content) if isinstance(content, str) else None
            structured_valid = parsed == {"status": "ready", "count": 2}
            elapsed = self._clock() - started
            return {
                "passed": (
                    structured_valid
                    and elapsed <= self._thresholds.max_presentation_seconds
                ),
                "latency_seconds": round(elapsed, 3),
                "structured_output_valid": structured_valid,
                "observed_model": str(response.get("model") or "unreported"),
            }
        except Exception as exc:
            return _failure_result(started, self._clock(), exc)

    # Measure one fixed text batch and validate every finite vector dimension.
    def _measure_embeddings(self) -> dict[str, Any]:
        started = self._clock()
        try:
            vectors = self._embedding.embed_texts(
                [
                    "A benchmark document about local inference.",
                    "A second benchmark document about editable slides.",
                    "A third benchmark document about image understanding.",
                ]
            )
            elapsed = self._clock() - started
            dimensions = sorted({len(vector) for vector in vectors})
            finite = all(math.isfinite(value) for vector in vectors for value in vector)
            shape_valid = (
                len(vectors) == 3
                and dimensions == [self._embedding_dimension]
                and finite
            )
            return {
                "passed": (
                    shape_valid
                    and elapsed <= self._thresholds.max_embedding_batch_seconds
                ),
                "latency_seconds": round(elapsed, 3),
                "batch_size": len(vectors),
                "dimensions": dimensions,
                "finite_values": finite,
            }
        except Exception as exc:
            return _failure_result(started, self._clock(), exc)

    # Measure grounded vision inference against one deterministic owned fixture.
    async def _measure_vision(
        self,
        fixture: bytes,
        fixture_sha256: str,
    ) -> dict[str, Any]:
        started = self._clock()
        try:
            analysis = await self._vision.analyze(
                (
                    "Reply with exactly RED_SQUARE if the image contains a red "
                    "square centered on a white background; otherwise reply UNKNOWN."
                ),
                fixture,
                "image/png",
            )
            elapsed = self._clock() - started
            grounded = bool(
                re.fullmatch(r"RED_SQUARE[.!]?", analysis.content.strip(), re.I)
            )
            return {
                "passed": (grounded and elapsed <= self._thresholds.max_vision_seconds),
                "latency_seconds": round(elapsed, 3),
                "fixture_sha256": fixture_sha256,
                "grounded_output_valid": grounded,
                "observed_model": analysis.model,
            }
        except Exception as exc:
            return {
                **_failure_result(started, self._clock(), exc),
                "fixture_sha256": fixture_sha256,
            }


# Describe the single harmless function used to test native tool selection.
def _benchmark_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": _TOOL_NAME,
            "description": "Record a fixed non-sensitive benchmark marker.",
            "parameters": {
                "type": "object",
                "properties": {"marker": {"type": "string"}},
                "required": ["marker"],
                "additionalProperties": False,
            },
        },
    }


# Validate exactly one expected tool call without retaining its raw arguments.
def _validate_tool_message(message: dict[str, Any]) -> tuple[str | None, bool]:
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or len(calls) != 1:
        return None, False
    call = calls[0]
    function = call.get("function") if isinstance(call, dict) else None
    if not isinstance(function, dict):
        return None, False
    name = function.get("name")
    arguments = function.get("arguments")
    try:
        parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
    except json.JSONDecodeError:
        return str(name) if name else None, False
    valid = parsed == {"marker": _TOOL_MARKER}
    return str(name) if name else None, valid


# Estimate output tokens consistently without depending on a vendor tokenizer.
def _estimated_token_count(content: str) -> int:
    return len(re.findall(r"\w+|[^\w\s]", content, re.UNICODE))


# Create the same application-owned red-square PNG for every vision run.
def _vision_fixture() -> tuple[bytes, str]:
    image = Image.new("RGB", (128, 128), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((32, 32, 95, 95), fill=(220, 20, 60))
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False)
    content = output.getvalue()
    return content, hashlib.sha256(content).hexdigest()


# Return bounded failure metadata without retaining prompts or provider output.
def _failure_result(started: float, finished: float, exc: Exception) -> dict[str, Any]:
    return {
        "passed": False,
        "latency_seconds": round(finished - started, 3),
        "error_type": type(exc).__name__,
    }
