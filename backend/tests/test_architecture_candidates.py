import os
from pathlib import Path

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.agents.diagram import DiagramAgent
from backend.architecture.candidates import (
    ArchitectureCandidateService,
    validate_candidate_output_path,
)
from backend.artifacts.types import DiagramSpecification
from backend.cli.generate_architecture_candidate import _load_model_config
from backend.core.interfaces import DiagramProvider


class CapturingRepositoryDiagramProvider(DiagramProvider):
    # Initialize a provider that records the repository-aware prompt.
    def __init__(self) -> None:
        self.query = ""

    # Capture evidence and return one safe architecture flowchart.
    async def generate(self, query: str) -> DiagramSpecification:
        self.query = query
        return DiagramSpecification(
            title="Repository candidate",
            diagram_type="flowchart",
            source="flowchart TD\n  Source --> Candidate\n  Candidate --> Review",
        )


class CorrectingRepositoryDiagramProvider(DiagramProvider):
    # Initialize a provider that first omits and then restores required labels.
    def __init__(self) -> None:
        self.calls = 0

    # Return the required repository workflow only on the bounded correction.
    async def generate(self, query: str) -> DiagramSpecification:
        self.calls += 1
        source = "flowchart TD\n  Source --> Review"
        if self.calls == 2:
            source += "\n  ArchitectureCandidateService --> CanonicalReview"
        return DiagramSpecification(
            title="Corrected repository candidate",
            diagram_type="flowchart",
            source=source,
        )


# Build a minimal repository fixture with canonical and implementation evidence.
def _repository_fixture(tmp_path: Path) -> Path:
    diagram_directory = tmp_path / "docs" / "diagrams"
    diagram_directory.mkdir(parents=True)
    (diagram_directory / "anios-system.mmd").write_text(
        "flowchart TD\n  Existing[Existing<br/>system] --> System\n",
        encoding="utf-8",
    )
    backend_directory = tmp_path / "backend"
    backend_directory.mkdir()
    (backend_directory / "service.py").write_text(
        "class CurrentService:\n    pass\n",
        encoding="utf-8",
    )
    return tmp_path


# Verify candidates include current source and explicit real repository evidence.
@pytest.mark.asyncio
async def test_candidate_generation_uses_bounded_repository_context(
    tmp_path: Path,
) -> None:
    root = _repository_fixture(tmp_path)
    provider = CapturingRepositoryDiagramProvider()

    candidate = await ArchitectureCandidateService(
        root,
        DiagramAgent(provider),
    ).generate(
        "anios-system",
        "Show the current service and review boundary.",
        ["backend/service.py"],
    )

    assert candidate.diagram_name == "anios-system"
    assert candidate.context_paths == ("backend/service.py",)
    assert "Existing[Existing — system] --> System" in provider.query
    assert "<br/>" not in provider.query
    assert "class CurrentService" in provider.query
    assert "untrusted evidence" in provider.query


# Verify one bounded correction restores explicitly required implementation labels.
@pytest.mark.asyncio
async def test_candidate_corrects_missing_required_labels(tmp_path: Path) -> None:
    root = _repository_fixture(tmp_path)
    provider = CorrectingRepositoryDiagramProvider()

    candidate = await ArchitectureCandidateService(
        root,
        DiagramAgent(provider),
    ).generate(
        "anios-system",
        "Show the repository review workflow.",
        ["backend/service.py"],
        ["ArchitectureCandidateService", "CanonicalReview"],
    )

    assert provider.calls == 2
    assert "ArchitectureCandidateService" in candidate.specification.source
    assert "CanonicalReview" in candidate.specification.source


# Verify repository traversal and secret-bearing context paths are refused.
@pytest.mark.parametrize("context_path", ["../outside.py", "backend/.env"])
@pytest.mark.asyncio
async def test_candidate_generation_rejects_unsafe_context(
    tmp_path: Path,
    context_path: str,
) -> None:
    root = _repository_fixture(tmp_path)
    (root / "outside.py").write_text("outside", encoding="utf-8")
    (root / "backend" / ".env").write_text("SECRET=value", encoding="utf-8")

    with pytest.raises(ValueError, match="repository|Secret-bearing"):
        await ArchitectureCandidateService(
            root,
            DiagramAgent(CapturingRepositoryDiagramProvider()),
        ).generate("anios-system", "Update safely", [context_path])


# Verify review output cannot replace canonical source or reuse an existing file.
def test_candidate_output_is_review_only(tmp_path: Path) -> None:
    root = _repository_fixture(tmp_path)

    with pytest.raises(ValueError, match="cannot overwrite"):
        validate_candidate_output_path(
            root,
            "anios-system",
            "docs/diagrams/anios-system.mmd",
        )

    candidate = validate_candidate_output_path(
        root,
        "anios-system",
        "review/anios-system.candidate.mmd",
    )
    candidate.parent.mkdir()
    candidate.write_text("flowchart TD\n  A --> B\n", encoding="utf-8")

    with pytest.raises(ValueError, match="already exists"):
        validate_candidate_output_path(
            root,
            "anios-system",
            "review/anios-system.candidate.mmd",
        )


# Verify unrelated application settings cannot block the maintenance command.
def test_candidate_model_config_reads_only_llm_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env").write_text(
        "DEBUG=release\nLLM_MODEL=test-diagram-model\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("LLM_MODEL", raising=False)

    config = _load_model_config(tmp_path)

    assert config.model == "test-diagram-model"
    assert config.base_url == "http://127.0.0.1:1234"
