"""The comparison harness has to be right before its verdicts mean anything.

A judge that is fed the same two answers twice, with the positions exchanged,
only cancels order bias if the second pass is mapped back correctly. Get that
mapping wrong and the harness reports the opposite of what happened, fluently
and with reasons attached - which is worse than no measurement, because it
would be believed. That is what most of this file is about.

Nothing here calls a model or the judge. The scoring logic is what can be wrong
silently; whether Claude runs is obvious the moment it does not.
"""

import argparse
from typing import Any

import pytest

import backend.cli.evaluate_reply_quality as harness
from backend.evals.judge import JudgeError, parse_verdicts
from backend.services.reply_quality_cases import REPLY_CASES


def _args(**overrides: Any) -> argparse.Namespace:
    base = {
        "a_base_url": "http://a.test",
        "a_model": "model-a",
        "a_adapter": "",
        "a_reasoning": "none",
        "b_base_url": "http://b.test",
        "b_model": "model-b",
        "b_adapter": "",
        "b_reasoning": "none",
        "max_tokens": 64,
        "batch": 50,
        "judge_model": "opus",
        "judge_timeout": 60,
        "json": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


# Answers that name the model that produced them, so a swap that is not undone
# shows up as the wrong model winning rather than as a subtle scoring drift.
def _answers(model: str) -> dict[str, str]:
    return {case.prompt: f"answer from {model}" for case in REPLY_CASES}


# A judge that always prefers whichever answer it is shown first. This is the
# bias the swap exists to cancel, so the harness must call every case a tie.
def test_a_judge_that_always_prefers_the_first_answer_decides_nothing(monkeypatch):
    monkeypatch.setattr(
        harness,
        "_judge",
        lambda block, count, model, timeout: [
            {"case": number, "winner": "A", "why": "shown first"}
            for number in range(1, count + 1)
        ],
    )

    resolved = harness._resolve(
        harness._compare(_args(), _answers("model-a"), _answers("model-b"))
    )

    assert len(resolved) == len(REPLY_CASES)
    assert {verdict.winner for verdict in resolved.values()} == {"tie"}


# The mapping that matters. A judge that genuinely prefers one model picks the
# letter that model occupies, which is "A" in the first pass and "B" in the
# second. Both must resolve to the same candidate.
def test_a_consistent_preference_survives_the_swap(monkeypatch):
    def judge(block: str, count: int, model: str, timeout: int) -> list[dict]:
        verdicts = []
        for number in range(1, count + 1):
            # Find which letter model-b was rendered under for this case.
            case_text = block.split("=== CASE ")[number].split("--- ANSWER A ---")[1]
            first, second = case_text.split("--- ANSWER B ---")
            assert "model-b" in first or "model-b" in second
            winner = "A" if "model-b" in first else "B"
            verdicts.append({"case": number, "winner": winner, "why": "prefers b"})
        return verdicts

    monkeypatch.setattr(harness, "_judge", judge)

    resolved = harness._resolve(
        harness._compare(_args(), _answers("model-a"), _answers("model-b"))
    )

    assert {verdict.winner for verdict in resolved.values()} == {"b"}


# Two orderings that disagree are not half a win each: the judge could not hold
# on to a difference, so there is none to report.
def test_orderings_that_disagree_are_recorded_as_a_tie():
    verdicts = [
        harness.Verdict(1, "synthesis", "a", "first pass"),
        harness.Verdict(1, "synthesis", "b", "second pass"),
    ]

    resolved = harness._resolve(verdicts)

    assert resolved[1].winner == "tie"
    assert resolved[1].why == "orderings disagreed"


def test_orderings_that_agree_keep_the_winner_and_the_reason():
    verdicts = [
        harness.Verdict(2, "no_invention", "a", "declined to guess"),
        harness.Verdict(2, "no_invention", "a", "declined to guess"),
    ]

    resolved = harness._resolve(verdicts)

    assert resolved[2].winner == "a"
    assert "declined" in resolved[2].why


# The judge is told to emit bare JSON and does, but one fenced reply should not
# throw away a whole run.
@pytest.mark.parametrize(
    "reply",
    [
        '[{"case": 1, "winner": "A", "why": "x"}]',
        '```json\n[{"case": 1, "winner": "A", "why": "x"}]\n```',
        'Here you go:\n[{"case": 1, "winner": "A", "why": "x"}]\nHope that helps.',
    ],
)
def test_verdicts_are_recovered_from_the_shapes_a_judge_replies_in(reply: str):
    assert parse_verdicts(reply) == [{"case": 1, "winner": "A", "why": "x"}]


def test_a_judge_reply_with_no_verdicts_fails_loudly():
    with pytest.raises(JudgeError):
        parse_verdicts("I cannot judge these answers.")


# A verdict naming a case outside the batch would otherwise be attributed to
# whichever case happened to sit at that index.
def test_a_verdict_for_a_case_that_was_not_asked_about_is_dropped(monkeypatch):
    monkeypatch.setattr(
        harness,
        "_judge",
        lambda block, count, model, timeout: [
            {"case": 999, "winner": "A", "why": "hallucinated case number"}
        ],
    )

    resolved = harness._resolve(
        harness._compare(_args(), _answers("model-a"), _answers("model-b"))
    )

    assert resolved == {}


# Both candidates must answer from the same context, or the comparison measures
# the harness. The prompt is a function of the case alone, and this pins it:
# nothing about which model is answering may reach the context it is given.
def test_context_depends_on_the_case_and_never_on_the_model(monkeypatch):
    seen: dict[str, list[str]] = {"fast-model": [], "slow-model": []}
    monkeypatch.setattr(harness, "_client", lambda url, model, adapter, effort: model)

    def record(client: Any, case: Any, max_tokens: int) -> str:
        seen[client].append(harness._build_system_prompt(harness._context_of(case)))
        return "answer"

    monkeypatch.setattr(harness, "_answer", record)
    for model in seen:
        harness.collect(_args(), "http://x.test", model, "", "none")

    assert seen["fast-model"] == seen["slow-model"] != []


# Answers are paired by prompt, not by position, so adding a case to the set
# cannot silently pair one model's answer with a different question.
def test_answers_are_paired_by_prompt_not_by_position(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(
        harness,
        "_judge",
        lambda block, count, model, timeout: captured.append(block) or [],
    )
    # Side B is missing the first case entirely, which would shift every
    # subsequent pairing by one if positions were trusted.
    b_answers = {
        case.prompt: f"b said about {case.prompt[:20]}" for case in REPLY_CASES[1:]
    }
    a_answers = {
        case.prompt: f"a said about {case.prompt[:20]}" for case in REPLY_CASES
    }

    harness._compare(_args(), a_answers, b_answers)

    block = captured[0]
    for case in REPLY_CASES[1:]:
        section = block.split(f"User asked: {case.prompt}")[1].split("=== CASE")[0]
        assert f"a said about {case.prompt[:20]}" in section
        assert f"b said about {case.prompt[:20]}" in section


# The guard against this set drifting back into the overfitting it replaces.
# A case that names the phrase it wants is scoring a word, and a case about
# this project's own subject matter rewards a model for having memorised it.
def test_no_case_demands_a_specific_phrase():
    for case in REPLY_CASES:
        assert case.standard.strip(), f"{case.prompt} has no standard"
        assert case.category.strip()
        assert '"' not in case.standard, (
            f"{case.prompt}: a quoted phrase in a standard is a string match"
        )


def test_every_category_is_covered_more_than_once():
    from collections import Counter

    counts = Counter(case.category for case in REPLY_CASES)
    thin = [name for name, total in counts.items() if total < 2]
    assert not thin, f"one case cannot show a regression in: {thin}"


# The buried-evidence cases only measure anything if the fact is genuinely late
# in the context, which is what makes them useful for context management too.
def test_buried_cases_put_the_answer_late_among_many_sources():
    buried = [case for case in REPLY_CASES if case.category == "buried_evidence"]
    assert buried
    for case in buried:
        assert len(case.search) >= 8, f"{case.prompt} is not a long context"
        answering = [
            index
            for index, item in enumerate(case.search)
            if "background and history" not in item["title"]
        ]
        assert answering, f"{case.prompt} has no answering source"
        assert min(answering) >= len(case.search) // 2, (
            f"{case.prompt} puts the answer early, so position is not tested"
        )
