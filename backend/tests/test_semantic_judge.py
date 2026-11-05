"""The judge the sweep runs inside the runtime container.

The sweep used to reach the judge through backend.tests.functional.semantic,
which imports pytest. The runtime image has no pytest, so every statement
came back "judge unavailable" and the harness failed every journey while the
replies were fine. These pin the shared judge and the sweep's mapping: an
outage is None (a failed journey), a verdict is a bool.

They also pin the two choices that made the judge reliable on the deployed
runtime (2026-11-04): it asks the reply model, whose thinking is on, rather
than the reasoning-off routing model that answered false to plainly true
statements; and it carries the person's question, so a statement about the
place a forecast is for does not require the reply to repeat the place.
"""

from __future__ import annotations

import pathlib

import pytest

from backend.cli.sweep_journeys import Sweep
from backend.services import semantic_judge


class _StubLLM:
    def __init__(self, content: str | list[object]) -> None:
        self.content = content
        self.calls: list[tuple] = []

    def chat(self, messages, max_tokens=512, response_schema=None, temperature=None):
        self.calls.append((messages, max_tokens, response_schema, temperature))
        if isinstance(self.content, list):
            item = self.content.pop(0)
            if isinstance(item, Exception):
                raise item
            return {"content": item}
        return {"content": self.content}


def _stub(monkeypatch, content) -> _StubLLM:
    llm = _StubLLM(content)
    monkeypatch.setattr(semantic_judge, "get_reply_llm_client", lambda: llm)
    return llm


def test_a_true_verdict_is_returned_and_the_schema_is_enforced(monkeypatch) -> None:
    llm = _stub(monkeypatch, '{"holds": true}')
    assert semantic_judge.judge_answer("44.1.", "The reply gives 44.1.") is True
    messages, max_tokens, schema, temperature = llm.calls[0]
    assert schema is semantic_judge.VERDICT_SCHEMA
    assert temperature == 0.0
    assert max_tokens == semantic_judge.JUDGE_MAX_TOKENS
    assert "Statement about the reply" in messages[1]["content"]


def test_the_question_is_carried_so_the_reply_need_not_repeat_the_place(monkeypatch) -> None:
    llm = _stub(monkeypatch, '{"holds": true}')
    semantic_judge.judge_answer(
        "Saturday is sunny, Sunday is cloudy.",
        "The reply gives a forecast for Washington, DC that mentions Saturday or Sunday.",
        "what's the weather in DC this weekend?",
    )
    body = llm.calls[0][0][1]["content"]
    assert "Question: what's the weather in DC this weekend?" in body


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


# Thinking runs before the verdict. A measured call spent the whole 1,024-token
# budget on reasoning and returned a choice with no message; one retry at the
# larger budget turns that into a verdict instead of failing the journey.
def test_a_message_less_choice_is_retried_once(monkeypatch) -> None:
    llm = _stub(
        monkeypatch,
        [ValueError("Inference provider did not contain a message output"), '{"holds": true}'],
    )
    assert semantic_judge.judge_answer("a", "b") is True
    assert len(llm.calls) == 2


def test_other_provider_errors_are_not_retried(monkeypatch) -> None:
    llm = _stub(monkeypatch, [ValueError("the request was rejected")])
    with pytest.raises(ValueError, match="rejected"):
        semantic_judge.judge_answer("a", "b")
    assert len(llm.calls) == 1


def test_the_sweep_turns_an_outage_into_a_failed_journey(monkeypatch) -> None:
    def unreachable(answer: str, statement: str, question=None) -> bool:
        raise ConnectionError("judge is away")

    monkeypatch.setattr(semantic_judge, "judge_answer", unreachable)
    assert Sweep.judge("a", "b") is None


def test_the_sweep_passes_a_verdict_and_the_question_through(monkeypatch) -> None:
    seen: list[tuple[str, str, str | None]] = []

    def judge(answer: str, statement: str, question=None) -> bool:
        seen.append((answer, statement, question))
        return True

    monkeypatch.setattr(semantic_judge, "judge_answer", judge)
    assert Sweep.judge("a", "b", "what's the weather in DC?") is True
    assert seen == [("a", "b", "what's the weather in DC?")]


def test_the_runtime_judge_does_not_import_pytest() -> None:
    # The defect this module exists to prevent: the runtime image has no
    # pytest, so a test-side import fails there. The judge must stay runnable
    # from the backend container.
    source = pathlib.Path(semantic_judge.__file__).read_text()
    assert "import pytest" not in source
