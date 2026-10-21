"""A dropped brief says which gate dropped it, and a rewrite is told what to fix."""

import json
import threading
from pathlib import Path

from backend.agents.trading.desk.narrative import (
    CONTRADICTED,
    NO_RUNTIME,
    WRONG_STANCE,
    DeskNarrator,
    _check_facts,
    _check_verdict,
)
from backend.market import prose

_BRIEF = {
    "stance": "own",
    "verdict": "A on a bullish release and growing revenue.",
    "reasoning": "Fundamental bullish: revenue_yoy +1.551. Sentiment bullish.",
    "risks": "Participation is below its two-year median.",
    "watch": "A bearish sentiment stance would drop the grade.",
}


# A writer whose answers are scripted per call: briefs for the brief schema,
# checks for the check schema, so the test can see what each gate received.
class _Writer:
    def __init__(self, briefs, checks):
        self.briefs, self.checks, self.calls = list(briefs), list(checks), []

    def chat(self, messages, max_tokens, schema, temperature):
        self.calls.append((messages, schema))
        queue = self.briefs if schema["title"] == "DeskBrief" else self.checks
        payload = queue.pop(0) if len(queue) > 1 else queue[0]
        return {"content": payload if isinstance(payload, str) else json.dumps(payload)}


# Three rejected attempts end as a checker rejection that names the claims,
# and the rewrite prompts quote the claim the checker named.
def test_a_checker_rejection_names_the_claim_and_the_rewrite_quotes_it():
    writer = _Writer(
        [_BRIEF],
        [
            {
                "claims": [
                    {
                        "claim": "growing revenue",
                        "fact": "revenue_yoy +1.551",
                        "verdict": "contradicts",
                    },
                    {
                        "claim": "Sentiment bullish.",
                        "fact": "sentiment: bullish",
                        "verdict": "consistent",
                    },
                ]
            }
        ],
    )
    brief, why = DeskNarrator(writer).brief_outcome("evidence", "A")
    assert brief is None
    assert why["reason"] == CONTRADICTED
    assert why["claims"] == ["growing revenue"]
    assert why["rejected"]["verdict"] == _BRIEF["verdict"]
    rewrites = [
        m[1]["content"]
        for m, schema in writer.calls
        if schema["title"] == "DeskBrief" and m[1]["content"] != "evidence"
    ]
    assert len(rewrites) == 2
    assert all("- growing revenue" in text for text in rewrites)
    assert all("make no relative claim" in text for text in rewrites)


# The check schema asks for one graded row per claim, with the fact beside
# it, and the verdict is read from the rows in code.
def test_the_check_schema_carries_the_claim():
    writer = _Writer(
        [_BRIEF],
        [
            {
                "claims": [
                    {
                        "claim": "Sentiment bullish.",
                        "fact": "sentiment: bullish",
                        "verdict": "consistent",
                    }
                ]
            }
        ],
    )
    brief, why = DeskNarrator(writer).brief_outcome("evidence", "A")
    assert brief is not None
    assert why is None
    checks = [
        schema for _m, schema in writer.calls if schema["title"] == "DeskBriefCheck"
    ]
    assert checks
    row = checks[0]["properties"]["claims"]["items"]["properties"]
    assert set(row) == {"claim", "fact", "verdict"}
    # No rows is no judgement; an overall word the rows do not support is
    # never asked for.
    assert _check_verdict({"claims": []}) == ("uncertain", [])
    assert _check_verdict(
        {
            "claims": [
                {"claim": "a", "fact": "f", "verdict": "consistent"},
                {"claim": "b", "fact": "", "verdict": "uncertain"},
            ]
        }
    ) == ("uncertain", ["b"])
    assert _check_verdict(
        {
            "claims": [
                {"claim": "a", "fact": "f", "verdict": "uncertain"},
                {"claim": "b", "fact": "f", "verdict": "contradicts"},
            ]
        }
    ) == ("contradicts", ["a", "b"])


# A stance that disagrees with the grade is named as such, with the brief
# that carried it; a missing runtime is named too.
def test_the_other_gates_are_named():
    writer = _Writer(
        [_BRIEF],
        [
            {
                "claims": [
                    {
                        "claim": "Sentiment bullish.",
                        "fact": "sentiment: bullish",
                        "verdict": "consistent",
                    }
                ]
            }
        ],
    )
    brief, why = DeskNarrator(writer).brief_outcome("evidence", "C")
    assert brief is None
    assert why["reason"] == WRONG_STANCE
    assert why["detail"] == "own for grade C"
    assert why["rejected"]["stance"] == "own"
    assert DeskNarrator(None).brief_outcome("evidence", "A") == (
        None,
        {"reason": NO_RUNTIME},
    )


# The results row for a dropped brief carries the reason, the claims and the
# rejected brief, and the failure line the nightly prints says which gate.
def test_the_results_row_says_why(tmp_path: Path):
    results = tmp_path / "prose-results.jsonl"
    why = {"reason": CONTRADICTED, "claims": ["growing revenue"], "rejected": _BRIEF}
    with results.open("a", encoding="utf-8") as out:
        prose._attempt(out, threading.Lock(), "brief", "TSM", lambda: (None, why), dict)
        prose._attempt(
            out, threading.Lock(), "read", "TSM", lambda: ("fine.", None), str
        )
    rows = [json.loads(line) for line in results.read_text().splitlines()]
    assert rows[0]["error"] == f"no brief: {CONTRADICTED} - growing revenue"
    assert rows[0]["rejected"] == _BRIEF
    assert rows[1] == {"kind": "read", "ticker": "TSM", "value": "fine."}
    briefs, reads, failures = prose.collect(results)
    assert briefs == {}
    assert reads == {"TSM": "fine."}
    assert failures == [f"brief TSM: no brief: {CONTRADICTED} - growing revenue"]


# The rank given to the writer reaches the checker as a fact, so a brief that
# places a name "near the top of the book" is checked against it rather than
# called invented.
def test_the_checker_sees_the_rank_and_the_plain_words():
    text = (
        "Grade: A. Votes: +1.0.\n"
        "sentiment analyst: stance +1 (rank 0.88 among the book, 1.00 is best); "
        "tone_guidance +1.000.\n"
        "  sentiment analyst in plain words: upbeat on outlook\n"
        "value analyst: stance +0; price_book +0.946.\n"
    )
    facts = _check_facts(text)
    assert "sentiment: bullish, rank 0.88 among the book (1.00 is best)" in facts
    assert "value: neutral (price_book +0.946.)" in facts
    assert "sentiment, in plain words: upbeat on outlook" in facts
