"""Benchmark provider-neutral AniOS inference roles and emit sanitized JSON."""

import argparse
import asyncio
import json
import os
import platform
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from backend.config.settings import settings
from backend.core.llm import create_inference_provider
from backend.embeddings.lm_studio import create_embedding_provider
from backend.services.inference_benchmark_service import (
    InferenceBenchmarkService,
    InferenceBenchmarkThresholds,
)
from backend.vision.lm_studio import create_vision_provider


# Define runtime overrides, thresholds, and optional report output.
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-name", default=settings.INFERENCE_PROVIDER_NAME)
    parser.add_argument("--main-adapter", default=_main_adapter())
    parser.add_argument("--main-base-url", default=_main_base_url())
    parser.add_argument("--main-model", default=_main_model())
    parser.add_argument("--presentation-adapter", default=_presentation_adapter())
    parser.add_argument("--presentation-base-url", default=_presentation_base_url())
    parser.add_argument("--presentation-model", default=_presentation_model())
    parser.add_argument("--vision-adapter", default=_vision_adapter())
    parser.add_argument("--vision-base-url", default=_vision_base_url())
    parser.add_argument("--vision-model", default=settings.VISION_MODEL)
    parser.add_argument("--embedding-adapter", default=_embedding_adapter())
    parser.add_argument("--embedding-base-url", default=_embedding_base_url())
    parser.add_argument("--embedding-model", default=settings.EMBEDDING_MODEL)
    parser.add_argument(
        "--embedding-dimension", type=int, default=settings.EMBEDDING_DIMENSION
    )
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    parser.add_argument("--max-main-ttft-seconds", type=float, default=30.0)
    parser.add_argument("--max-main-total-seconds", type=float, default=45.0)
    parser.add_argument(
        "--min-main-estimated-tokens-per-second", type=float, default=1.0
    )
    parser.add_argument("--max-tool-seconds", type=float, default=10.0)
    parser.add_argument("--max-presentation-seconds", type=float, default=45.0)
    parser.add_argument("--max-embedding-batch-seconds", type=float, default=10.0)
    parser.add_argument("--max-vision-seconds", type=float, default=30.0)
    parser.add_argument("--output", type=Path)
    return parser


# Resolve the main role adapter while preserving the legacy fallback.
def _main_adapter() -> str:
    return settings.MAIN_INFERENCE_ADAPTER or settings.INFERENCE_ADAPTER


# Resolve the main role endpoint while preserving the legacy fallback.
def _main_base_url() -> str:
    return settings.MAIN_LLM_BASE_URL or settings.LLM_BASE_URL


# Resolve the main role model while preserving the legacy fallback.
def _main_model() -> str:
    return settings.MAIN_LLM_MODEL or settings.LLM_MODEL


# Resolve the presentation role adapter while preserving the legacy fallback.
def _presentation_adapter() -> str:
    return settings.PRESENTATION_INFERENCE_ADAPTER or settings.INFERENCE_ADAPTER


# Resolve the presentation role endpoint while preserving the legacy fallback.
def _presentation_base_url() -> str:
    return settings.PRESENTATION_LLM_BASE_URL or settings.LLM_BASE_URL


# Resolve the presentation role model while preserving the legacy fallback.
def _presentation_model() -> str:
    return settings.PRESENTATION_LLM_MODEL or settings.LLM_MODEL


# Resolve the vision role adapter while preserving the legacy fallback.
def _vision_adapter() -> str:
    return settings.VISION_INFERENCE_ADAPTER or settings.INFERENCE_ADAPTER


# Resolve the vision role endpoint while preserving the legacy fallback.
def _vision_base_url() -> str:
    return settings.VISION_LLM_BASE_URL or settings.LLM_BASE_URL


# Resolve the embedding role adapter while preserving the legacy fallback.
def _embedding_adapter() -> str:
    return settings.EMBEDDING_INFERENCE_ADAPTER or settings.INFERENCE_ADAPTER


# Resolve the embedding role endpoint while preserving the legacy fallback.
def _embedding_base_url() -> str:
    return settings.EMBEDDING_BASE_URL or settings.LLM_BASE_URL


# Remove credentials and paths before recording a configured endpoint.
def _safe_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or "unknown"
    if ":" in host:
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme or 'http'}://{host}{port}"


# Capture non-identifying host and GPU facts needed to interpret local results.
def _hardware_identity() -> dict[str, Any]:
    gpus: list[dict[str, Any]] = []
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in completed.stdout.splitlines():
            fields = [field.strip() for field in line.split(",")]
            if len(fields) == 3:
                gpus.append(
                    {
                        "name": fields[0],
                        "memory_total_mib": int(fields[1]),
                        "driver_version": fields[2],
                    }
                )
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "logical_cpus": os.cpu_count(),
        "gpus": gpus,
    }


# Build the adapter/runtime/model identity recorded alongside measurements.
def _identity(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "provider_name": args.provider_name,
        "roles": {
            "main": {
                "adapter": args.main_adapter,
                "endpoint": _safe_endpoint(args.main_base_url),
                "model": args.main_model,
            },
            "presentation": {
                "adapter": args.presentation_adapter,
                "endpoint": _safe_endpoint(args.presentation_base_url),
                "model": args.presentation_model,
            },
            "embedding": {
                "adapter": args.embedding_adapter,
                "endpoint": _safe_endpoint(args.embedding_base_url),
                "model": args.embedding_model,
            },
            "vision": {
                "adapter": args.vision_adapter,
                "endpoint": _safe_endpoint(args.vision_base_url),
                "model": args.vision_model,
            },
        },
        "hardware": _hardware_identity(),
    }


# Validate all numeric limits before sending any provider request.
def _validate_args(args: argparse.Namespace) -> None:
    positive = {
        "--embedding-dimension": args.embedding_dimension,
        "--timeout-seconds": args.timeout_seconds,
        "--max-main-ttft-seconds": args.max_main_ttft_seconds,
        "--max-main-total-seconds": args.max_main_total_seconds,
        "--min-main-estimated-tokens-per-second": (
            args.min_main_estimated_tokens_per_second
        ),
        "--max-tool-seconds": args.max_tool_seconds,
        "--max-presentation-seconds": args.max_presentation_seconds,
        "--max-embedding-batch-seconds": args.max_embedding_batch_seconds,
        "--max-vision-seconds": args.max_vision_seconds,
    }
    invalid = [name for name, value in positive.items() if value <= 0]
    if invalid:
        raise SystemExit(f"{', '.join(invalid)} must be positive")


# Assemble neutral providers and execute one sequential benchmark run.
async def _run(args: argparse.Namespace) -> dict[str, Any]:
    thresholds = InferenceBenchmarkThresholds(
        max_main_ttft_seconds=args.max_main_ttft_seconds,
        max_main_total_seconds=args.max_main_total_seconds,
        min_main_estimated_tokens_per_second=(
            args.min_main_estimated_tokens_per_second
        ),
        max_tool_seconds=args.max_tool_seconds,
        max_presentation_seconds=args.max_presentation_seconds,
        max_embedding_batch_seconds=args.max_embedding_batch_seconds,
        max_vision_seconds=args.max_vision_seconds,
    )
    main = create_inference_provider(
        adapter=args.main_adapter,
        base_url=args.main_base_url,
        model=args.main_model,
        api_key=settings.LLM_API_KEY,
        timeout_seconds=args.timeout_seconds,
        reasoning_effort=settings.MAIN_LLM_REASONING_EFFORT,
    )
    presentation = create_inference_provider(
        adapter=args.presentation_adapter,
        base_url=args.presentation_base_url,
        model=args.presentation_model,
        api_key=settings.LLM_API_KEY,
        timeout_seconds=args.timeout_seconds,
        reasoning_effort=settings.PRESENTATION_LLM_REASONING_EFFORT,
    )
    embedding = create_embedding_provider(
        adapter=args.embedding_adapter,
        base_url=args.embedding_base_url,
        model=args.embedding_model,
        dimension=args.embedding_dimension,
        api_key=settings.LLM_API_KEY,
        timeout_seconds=args.timeout_seconds,
        max_concurrency=1,
    )
    vision = create_vision_provider(
        adapter=args.vision_adapter,
        base_url=args.vision_base_url,
        model=args.vision_model,
        api_key=settings.LLM_API_KEY,
        timeout_seconds=args.timeout_seconds,
        reasoning_effort=settings.VISION_LLM_REASONING_EFFORT,
        max_tokens=32,
    )
    return await InferenceBenchmarkService(
        main=main,
        presentation=presentation,
        embedding=embedding,
        vision=vision,
        embedding_dimension=args.embedding_dimension,
        thresholds=thresholds,
    ).run(_identity(args))


# Print and optionally persist the sanitized report with a threshold exit code.
def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _validate_args(args)
    report = asyncio.run(_run(args))
    encoded = json.dumps(report, indent=2, sort_keys=True)
    print(encoded)
    if args.output is not None:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    return 0 if report["summary"]["overall_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
