"""Trimming, at last - and the gate that keeps it honest.

The budget planner computed what to keep on every turn and the result was
discarded; CONTEXT_BUDGET_ENFORCE logged loudly that trimming was not
implemented. It is now: the plan's kept sets are applied to the turn's inputs
- context_data and history - before any rendering, so the report and the sent
prompt agree by construction rather than by later comparison.

Two properties carry everything. Trimming drops from the tail of each
section's relevance order, never the head, because the caller already sorted
by relevance and reversing that judgement under pressure would drop the best
material first. And the untrimmable parts win absolutely: a window too small
for the system prompt and the question is sent in full with a warning, never
"fixed" by sending a turn missing its own question.

The buried_evidence gate at the end is the reason this can ever be switched
on. Those labelled cases put the answering source late in the caller's order
- exactly where trimming cuts - so they fail the moment the production budget
or a floor is set low enough to lose a findable fact.
"""

import pytest

from backend.agents.graph import _apply_report, measure_turn
from backend.agents.reply.nodes import after_measure
from backend.config.settings import settings
from backend.core.context_budget import Allocation, BudgetReport


@pytest.fixture
def budget(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_ENABLED", True)
    return monkeypatch


def _context(sources: int = 12, size: int = 3_000):
    return {
        "search": [
            {"title": f"s{i}", "url": f"u{i}", "content": "w" * size}
            for i in range(sources)
        ],
        "recalled_turns": [
            {"said": "I like jazz", "when": "2026-06-11"},
            {"said": "I moved to Leeds", "when": "2026-07-01"},
        ],
        "semantic": [{"content": "lives in Raleigh"}],
        "episodic": [{"content": "asked about bridges"}],
        "images": [],
        "tool_results": [],
    }


def _history(turns: int = 6):
    return [{"query": f"question {i}", "response": f"answer {i}"} for i in range(turns)]


def _squeeze(monkeypatch, tokens: int):
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_TOKENS", tokens)
    monkeypatch.setattr(settings, "MAIN_LLM_MAX_TOKENS", 256)


def test_trimming_keeps_the_head_of_the_relevance_order(budget):
    _squeeze(budget, 8_000)
    context = _context()
    report = measure_turn(context, _history(), "q", "SYSTEM")
    assert report is not None
    assert report.dropped_total > 0, "the squeeze did not bind; test is vacuous"

    trimmed, _ = _apply_report(context, _history(), report)

    kept_titles = [item["title"] for item in trimmed["search"]]
    assert kept_titles == [
        f"s{i}" for i in range(len(kept_titles))
    ], "trimming must drop the tail, never reorder or skip"
    assert len(kept_titles) < 12


def test_history_is_trimmed_by_whole_oldest_turns(budget):
    _squeeze(budget, 1_200)
    # Heavy exchanges, or every one of them fits and the squeeze never binds.
    history = [
        {"query": f"question {i}", "response": f"answer {i} " + "w" * 800}
        for i in range(6)
    ]
    report = measure_turn(_context(2, 200), history, "q", "SYSTEM")
    assert report is not None
    kept_count = {i.name: len(i.kept) for i in report.allocations}["history"]
    assert kept_count < 6, "squeeze did not bind on history"

    _, kept_history = _apply_report(_context(2, 200), history, report)

    assert len(kept_history) == kept_count
    # The survivors are the newest exchanges, intact as pairs.
    assert kept_history == history[-kept_count:]


def test_a_deduplicated_recall_stays_dropped_under_enforcement(budget):
    _squeeze(budget, 50_000)
    said = "I like jazz"
    history = [{"query": said, "response": "noted"}]
    context = _context(1, 100)
    report = measure_turn(context, history, "q", "SYSTEM")
    assert report is not None

    trimmed, _ = _apply_report(context, history, report)

    said_kept = [turn["said"] for turn in trimmed["recalled_turns"]]
    assert "I moved to Leeds" in said_kept
    assert said not in said_kept, "a remark visible in history came back"


# Personal memory is part of the measured system prompt and cannot be silently trimmed.
def test_enforcement_preserves_personal_memory_inside_the_system_block(budget):
    context = {
        "episodic": [{"content": f"e{i}"} for i in range(3)],
        "semantic": [{"content": f"s{i}"} for i in range(3)],
    }
    report = measure_turn(context, [], "q", "SYSTEM")
    assert report is not None

    trimmed, _ = _apply_report(context, [], report)

    assert trimmed["episodic"] == context["episodic"]
    assert trimmed["semantic"] == context["semantic"]


# Tool notices share the same allowance instead of bypassing tool-result trimming.
def test_tool_notices_share_the_tool_budget(budget):
    context = {
        "tool_results": [{"tool": "clock", "value": "10:00"}],
        "tool_notices": [{"tool": "mail", "error": "denied"}],
    }
    report = measure_turn(context, [], "q", "SYSTEM")
    assert report is not None
    allocations = []
    for allocation in report.allocations:
        if allocation.name == "tools":
            allocations.append(
                type(allocation)(
                    name=allocation.name,
                    kept=allocation.kept[:1],
                    dropped=max(0, len(allocation.kept) - 1),
                    tokens=allocation.tokens,
                )
            )
        else:
            allocations.append(allocation)
    constrained = type(report)(
        budget_tokens=report.budget_tokens,
        used_tokens=report.used_tokens,
        allocations=tuple(allocations),
    )

    trimmed, _ = _apply_report(context, [], constrained)

    assert trimmed["tool_results"] == context["tool_results"]
    assert trimmed["tool_notices"] == []


# Safety framing cannot be trimmed, so a plan that drops it must not be enforced.
def test_enforcement_stops_when_turn_framing_does_not_fit(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_BUDGET_ENFORCE", True)
    report = BudgetReport(
        budget_tokens=100,
        used_tokens=100,
        allocations=(
            Allocation("system", kept=("system",)),
            Allocation("query", kept=("query",)),
            Allocation("turn_context", dropped=1),
        ),
    )

    assert after_measure({"budget_report": report, "trace_id": "test"}) == "assemble"


def test_nothing_is_trimmed_when_everything_fits(budget):
    context = _context(2, 200)
    report = measure_turn(context, _history(2), "q", "SYSTEM")
    assert report is not None
    assert report.dropped_total == 0

    trimmed, kept_history = _apply_report(context, _history(2), report)

    assert len(trimmed["search"]) == 2
    assert len(kept_history) == 2


# The production configuration this gate protects: at the shipped budget,
# every buried_evidence case keeps every source, so the fact that sits late in
# the caller's order - exactly where trimming cuts - is always still findable.
# The day a budget or floor change makes this drop, the change is wrong, not
# the case.
def test_the_buried_evidence_cases_survive_the_production_budget(budget):
    from backend.services.reply_quality_cases import REPLY_CASES

    cases = [c for c in REPLY_CASES if c.category == "buried_evidence"]
    assert cases, "the gate has nothing to guard"
    for case in cases:
        context = {"search": [dict(s) for s in case.search]}
        report = measure_turn(context, [], case.prompt, "S" * 4_000)
        assert report is not None
        trimmed, _ = _apply_report(context, [], report)

        answering = [
            s for s in trimmed["search"] if "background and history" not in s["title"]
        ]
        assert answering, (
            f"{case.prompt!r}: the answering source was trimmed away at the "
            "production budget - a findable fact became unfindable"
        )
        assert report.dropped_total == 0
