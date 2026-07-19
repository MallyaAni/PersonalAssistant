import argparse
import asyncio
import json
import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

from backend.agents.diagram import DiagramAgent
from backend.architecture.candidates import (
    DIAGRAM_NAMES,
    ArchitectureCandidateService,
    validate_candidate_output_path,
)
from backend.artifacts.diagram import LLMDiagramProvider
from backend.core.llm import LMStudioLLM


@dataclass(frozen=True, slots=True)
class LocalDiagramModelConfig:
    """Only the local model settings needed by the maintenance command."""

    base_url: str
    model: str
    api_key: str | None
    timeout_seconds: float
    reasoning_effort: str


# Define explicit repository evidence and review-output command options.
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a review-only AniOS architecture diagram candidate.",
    )
    parser.add_argument("--diagram", choices=DIAGRAM_NAMES, required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument(
        "--context",
        action="append",
        required=True,
        help="Repository-relative implementation file to provide as evidence.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="New review path ending in .candidate.mmd; canonical files are refused.",
    )
    parser.add_argument(
        "--require-label",
        action="append",
        default=[],
        help="Implementation-backed label that must appear in the candidate.",
    )
    return parser


# Refuse remote model endpoints for repository-aware generation.
def _require_local_model_endpoint(base_url: str) -> None:
    host = (urlparse(base_url).hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(
            "Architecture candidates require a loopback LM Studio endpoint"
        )


# Read only LLM settings without importing unrelated application configuration.
def _load_model_config(repository_root: Path) -> LocalDiagramModelConfig:
    file_values = dotenv_values(repository_root / ".env")

    # Prefer one process value while retaining the documented optional .env source.
    def value(name: str, default: str) -> str:
        process_value = os.environ.get(name)
        file_value = file_values.get(name)
        return process_value or (str(file_value) if file_value is not None else default)

    api_key = value("LLM_API_KEY", "").strip() or None
    return LocalDiagramModelConfig(
        base_url=value("LLM_BASE_URL", "http://127.0.0.1:1234"),
        model=value("LLM_MODEL", "google/gemma-4-12b"),
        api_key=api_key,
        timeout_seconds=float(value("LLM_TIMEOUT_SECONDS", "120")),
        reasoning_effort=value("LLM_REASONING_EFFORT", "none"),
    )


# Render one candidate SVG through the pinned local Mermaid toolchain.
def _render_candidate(repository_root: Path, source_path: Path) -> Path:
    output_path = source_path.with_suffix(".svg")
    script_path = repository_root / "frontend" / "scripts" / "architecture-diagram.mjs"
    subprocess.run(
        ["node", str(script_path), "validate", str(source_path), str(output_path)],
        cwd=repository_root / "frontend",
        check=True,
    )
    return output_path


# Generate, save, and render one candidate without replacing canonical source.
async def _run(args: argparse.Namespace, repository_root: Path) -> dict[str, object]:
    model_config = _load_model_config(repository_root)
    _require_local_model_endpoint(model_config.base_url)
    output_path = validate_candidate_output_path(
        repository_root,
        args.diagram,
        args.output,
    )
    llm = LMStudioLLM(
        base_url=model_config.base_url,
        model=model_config.model,
        api_key=model_config.api_key,
        timeout_seconds=model_config.timeout_seconds,
        reasoning_effort=model_config.reasoning_effort,
    )
    candidate = await ArchitectureCandidateService(
        repository_root,
        DiagramAgent(LLMDiagramProvider(llm, model_config.model)),
    ).generate(
        args.diagram,
        args.request,
        args.context,
        args.require_label,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(candidate.specification.source + "\n", encoding="utf-8")
    rendered_path = _render_candidate(repository_root, output_path)
    return {
        "status": "candidate_ready_for_review",
        "diagram": candidate.diagram_name,
        "model": model_config.model,
        "source": str(output_path),
        "rendered": str(rendered_path),
        "context_paths": candidate.context_paths,
        "required_labels": args.require_label,
        "canonical_updated": False,
    }


# Run the review-only candidate workflow and return a shell-friendly exit code.
def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repository_root = Path(__file__).resolve().parents[2]
    result = asyncio.run(_run(args, repository_root))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
