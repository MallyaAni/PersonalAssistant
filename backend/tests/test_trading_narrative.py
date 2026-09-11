"""The desk brief: evidence text, the schema round trip, the stance check."""

import json
from datetime import date, timedelta

import numpy as np

from backend.agents.trading.desk import grading, regime
from backend.agents.trading.desk.desk import DeskReport
from backend.agents.trading.desk.narrative import (
    AVOID,
    OWN,
    WAIT,
    DeskNarrator,
    _coverage_gaps,
    brief_text,
    stance_for,
)
from backend.agents.trading.desk.opinions import Opinion
from backend.market.panel import Panel
from backend.market.universe import AI_COMPUTE


# A writer that returns a fixed JSON payload per call (the last one is
# reused), or garbage.
class _Writer:
    def __init__(self, payload, *more):
        self.payloads = [payload, *more]
        self.calls = []

    def chat(self, messages, max_tokens, schema, temperature):
        self.calls.append((messages, max_tokens, schema, temperature))
        payload = self.payloads[min(len(self.calls) - 1, len(self.payloads) - 1)]
        content = (
            payload if isinstance(payload, str) else json.dumps(payload)
        )
        return {"content": content}


def _report() -> DeskReport:
    t, n = 5, 2
    close = np.full((t, n + 1), 100.0)
    dates = np.array(
        [date(2026, 9, 1) + timedelta(days=i) for i in range(t)], dtype="datetime64[D]"
    )
    panel = Panel(
        dates=dates,
        tickers=("SNDK", "IREN", "SPY"),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={"SNDK": (AI_COMPUTE,), "IREN": (AI_COMPUTE,)},
        benchmark="SPY",
    )
    grades = np.zeros((t, n + 1), dtype=int)
    grades[:, 0] = grading.ORDINAL["A+"]
    stances = {
        "fundamental": np.array([[1, -1, 0]] * t),
        "technical": np.array([[1, -1, 0]] * t),
        "sentiment": np.array([[1, 0, 0]] * t),
    }
    graded = grading.Graded(grades, np.array([[3.0, -2.0, 0.0]] * t), stances)
    opinions = {
        "fundamental": Opinion(
            "fundamental",
            np.full((t, n + 1), 0.5),
            {"revenue_yoy": np.array([[1.551, -0.311, np.nan]] * t)},
        ),
        "sentiment": Opinion(
            "sentiment",
            np.full((t, n + 1), 0.5),
            {"tone_guidance": np.array([[1.0, np.nan, np.nan]] * t)},
        ),
    }
    state = regime.RegimeState(
        -0.06,
        0.19,
        0.0,
        -0.52,
        -3.6,
        4.8,
        "software",
        -0.217,
        -0.223,
        0.5,
        1.0,
        ("participation below its two-year median",),
    )
    view = regime.RegimeView(
        [state] * t, Opinion("rotation", np.full((t, n + 1), np.nan))
    )
    return DeskReport(
        panel,
        {"SNDK": "ai", "IREN": "ai"},
        opinions,
        view,
        graded,
        grades.astype(float),
        [],
    )


# The evidence text carries the grade, every analyst's stance and numbers,
# the regime and its flags, written once each.
def test_brief_text_carries_the_evidence():
    text = brief_text(_report(), "SNDK")
    assert "Grade: A+" in text
    assert "fundamental analyst: stance +1 (rank 0.50 among the book" in text
    assert "revenue_yoy +1.551" in text
    assert "sentiment analyst: stance +1 (rank 0.50 among the book" in text
    assert "tone_guidance +1.000" in text
    assert "participation below its two-year median" in text
    assert "Not in today's book" in text
    iren = brief_text(_report(), "IREN")
    assert "Grade: C" in iren
    assert "sentiment analyst: stance +0 (rank 0.50 among the book" in iren
    assert "no data for this name" in iren


# The coverage gate must see a ranked analyst (whose rank sits between the
# stance and the semicolon) exactly as it sees an unranked one, so a read
# that skips it still fails. Before the fix the ranked variant broke the
# line pattern and the analyst was never checked.
def test_the_coverage_gate_sees_a_ranked_analyst():
    unranked = "technical analyst: stance +1; momentum +0.123, trend +0.456."
    ranked = (
        "technical analyst: stance +1 (rank 0.95 among the book, 1.00 is best); "
        "momentum +0.123, trend +0.456."
    )
    read = "The fundamental case is strong on revenue and growth."
    assert any("technical analyst" in g for g in _coverage_gaps(unranked, read))
    assert any("technical analyst" in g for g in _coverage_gaps(ranked, read))


# The stance the grade implies.
def test_stance_for_grade():
    assert stance_for("A+") == OWN
    assert stance_for("A") == OWN
    assert stance_for("B") == WAIT
    assert stance_for("C") == AVOID


# A well-formed answer becomes a DeskBrief; a stance that contradicts the
# grade, garbage, or a missing runtime become None.
def test_narrator_round_trip_and_refusals():
    payload = {
        "stance": "own",
        "verdict": "A+ on a bullish release and growing revenue.",
        "reasoning": "Fundamental bullish: revenue_yoy +1.551. Sentiment bullish.",
        "risks": "Participation is below its two-year median.",
        "watch": "A bearish sentiment stance would drop the grade.",
    }
    writer = _Writer(payload, {"consistency": "consistent"})
    brief = DeskNarrator(writer).brief_sync("evidence", "A+")
    assert brief is not None
    assert brief.stance == OWN
    assert brief.verdict.startswith("A+")
    messages, _max_tokens, schema, temperature = writer.calls[0]
    assert messages[1]["content"] == "evidence"
    assert schema["properties"]["stance"]["enum"] == ["own", "wait", "avoid"]
    assert temperature == 0.0
    assert DeskNarrator(writer).brief_sync("evidence", "C") is None
    assert DeskNarrator(_Writer("not json")).brief_sync("evidence", "A+") is None
    assert DeskNarrator(None).brief_sync("evidence", "A+") is None


# A brief that contradicts the evidence is dropped, not persisted; the page
# shows the deterministic readings instead. A check that fails to answer
# never discards a good brief.
def test_a_brief_that_contradicts_the_evidence_is_dropped():
    payload = {
        "stance": "own",
        "verdict": "A+ on a bullish release and growing revenue.",
        "reasoning": "Fundamental bullish: revenue_yoy +1.551. Sentiment bullish.",
        "risks": "Participation is below its two-year median.",
        "watch": "A bearish sentiment stance would drop the grade.",
    }
    assert (
        DeskNarrator(_Writer(payload, {"consistency": "contradicts"})).brief_sync(
            "evidence", "A+"
        )
        is None
    )
    assert (
        DeskNarrator(_Writer(payload, "not json")).brief_sync("evidence", "A+")
        is not None
    )


# A long field is cut at a sentence end, never mid-word.
def test_cut_at_sentence():
    from backend.agents.trading.desk.narrative import _cut

    text = "First sentence is here. Second sentence follows. Third one is long."
    assert _cut(text, 100) == text
    assert _cut(text, 50) == "First sentence is here. Second sentence follows."


# A short field that ends without sentence punctuation is a truncation, not
# a finished brief: it is cut back to the last complete sentence rather
# than shown broken. A single fragment with no sentence end is kept whole.
def test_a_short_unfinished_field_is_cut_to_a_complete_sentence():
    from backend.agents.trading.desk.narrative import _cut

    unfinished = "Revenue is up strongly. The margin story is still"
    assert _cut(unfinished, 200) == "Revenue is up strongly."
    fragment = "The margin story is still"
    assert _cut(fragment, 200) == fragment
    assert _cut("Revenue is up strongly.", 200) == "Revenue is up strongly."
