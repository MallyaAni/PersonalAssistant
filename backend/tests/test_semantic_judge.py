"""The judge the sweep runs inside the runtime container.

The sweep used to reach the judge through backend.tests.functional.semantic,
which imports pytest. The runtime image has no pytest, so every statement
came back "judge unavailable" and the harness failed every journey while the
replies were fine. These pin the shared judge and the sweep's mapping: an
outage is None (a failed journey), a verdict is a bool.
"""

from __future__ import annotations

import pathlib

import pytest

from backend.cli.sweep_journeys import Sweep
from backend.services import semantic_judge


class _StubLLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple] = []

    def chat(self, messages, max_tokens=512, response_schema=None, temperature=None):
        self.calls.append((messages, max_tokens, response_schema, temperature))
        return {"content": self.content}


def _stub(monkeypatch, content: str) -> _StubLLM:
    llm = _StubLLM(content)
    monkeypatch.setattr(semantic_judge, "get_routing_llm_client", lambda: llm)
    return llm


def test_a_true_verdict_is_returned_and_the_schema_is_enforced(monkeypatch) -> None:
    llm = _stub(monkeypatch, '{"holds": true}')
    assert semantic_judge.judge_answer("44.1.", "The reply gives 44.1.") is True
    messages, max_tokens, schema, temperature = llm.calls[0]
    assert schema is semantic_judge.VERDICT_SCHEMA
    assert temperature == 0.0
    assert "Statement about the text" in messages[1]["content"]


def test_a_false_verdict_is_returned(monkeypatch) -> None:
    _stub(monkeypatch, '{"holds": false}')
    assert semantic_judge.judge_answer("I cannot check.", "The reply gives a price.") is False


def test_non_json_is_an_error_not_a_verdict(monkeypatch) -> None:
    _stub(monkeypatch, "the model wrote prose")
    with pytest.raises(ValueError, match="non-JSON"):
        semantic_judge.judge_answer("a", "b")


def test_a_missing_verdict_is_an_error(monkeypatch) -> None:
    _stub(monkeypatch, '{"verdict": true}')
    with pytest.raises(ValueError, match="no verdict"):
        semantic_judge.judge_answer("a", "b")


def test_the_sweep_turns_an_outage_into_a_failed_journey(monkeypatch) -> None:
    def unreachable(answer: str, statement: str) -> bool:
        raise ConnectionError("judge is away")

    monkeypatch.setattr(semantic_judge, "judge_answer", unreachable)
    assert Sweep.judge("a", "b") is None


def test_the_sweep_passes_a_verdict_through(monkeypatch) -> None:
    monkeypatch.setattr(semantic_judge, "judge_answer", lambda answer, statement: True)
    assert Sweep.judge("a", "b") is True


def test_the_runtime_judge_does_not_import_pytest() -> None:
    # The defect this module exists to prevent: the runtime image has no
    # pytest, so a test-side import fails there. The judge must stay runnable
    # from the backend container.
    source = pathlib.Path(semantic_judge.__file__).read_text()
    assert "import pytest" not in source
