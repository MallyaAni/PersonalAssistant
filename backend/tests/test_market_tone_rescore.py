"""The masked re-score runner (arm B) and the leak-question runner.

What has to hold: a masked release is scored by the reader and lands in
the name's partial file as a ToneRecord carrying the reader's model and
prompt version; a re-run scores only what is missing; a reader failure is
counted and does not stop the run; the leak runner sends the sample's
prompt, keeps the answers by accession and resumes.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.agents.trading.release_tone import PROMPT_VERSION, ReleaseTone
from backend.cli import market_tone_rescore as rs
from backend.market import language


# A reader that scores from the text's length, failing on "BOOM".
class _Reader:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def score_sync(self, text: str) -> ReleaseTone | None:
        self.calls.append(text)
        if "BOOM" in text:
            raise RuntimeError("runtime away")
        return ReleaseTone(1.0, 0.0, -1.0, 0.0, 1.0, "s", False, "2024-06-30", 100.0, None, None, 55.5)


# Two names' masked rows.
def _masked(tmp_path: Path) -> Path:
    masked = tmp_path / "masked"
    masked.mkdir()
    rows = {
        "AAA": [
            {"accession": "a1", "ticker": "AAA", "reaction_date": "2024-08-01", "text": "[COMPANY] grew"},
            {"accession": "a2", "ticker": "AAA", "reaction_date": "2024-11-01", "text": "BOOM"},
        ],
        "BBB": [{"accession": "b1", "ticker": "BBB", "reaction_date": "2024-08-02", "text": "[COMPANY] fell"}],
    }
    for ticker, lines in rows.items():
        (masked / f"{ticker}.jsonl").write_text("\n".join(json.dumps(r) for r in lines) + "\n")
    return masked


# Scores land as ToneRecords under the reader's model; a failure is
# counted; a second run scores nothing new and keeps the records.
def test_score_masked_writes_partials_and_resumes(tmp_path):
    masked = _masked(tmp_path)
    out = tmp_path / "tone"
    reader = _Reader()
    scored, failed = rs.score_masked(masked, out, [reader], "test-model", log=lambda s: None)
    assert (scored, failed) == (2, 1)
    got = language.read_partial(out / "AAA.jsonl")
    assert list(got) == ["a1"]
    rec = got["a1"]
    assert rec.model == "test-model" and rec.prompt_version == PROMPT_VERSION
    assert rec.guidance == 1.0 and rec.pricing == -1.0 and rec.gross_margin_pct == 55.5
    assert str(rec.reaction_date) == "2024-08-01" and str(rec.quarter_end) == "2024-06-30"
    assert language.read_partial(out / "BBB.jsonl")["b1"].demand == 0.0
    again = _Reader()
    scored, failed = rs.score_masked(masked, out, [again], "test-model", log=lambda s: None)
    assert (scored, failed) == (0, 1) and again.calls == ["BOOM"]
    # The masked-tone loader of the evaluate step reads these partials.
    assert len(language.read_partial(out / "AAA.jsonl")) == 1


# `--limit` scores at most that many releases (a smoke run).
def test_score_masked_limit(tmp_path):
    masked = _masked(tmp_path)
    reader = _Reader()
    scored, failed = rs.score_masked(masked, tmp_path / "t", [reader], "m", log=lambda s: None, limit=1)
    assert (scored, failed) == (1, 0) and len(reader.calls) == 1


# A writer that answers the leak question with JSON.
class _Writer:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def chat(self, messages, max_tokens, schema, temperature):
        self.prompts.append(messages[0]["content"])
        assert schema == rs.LEAK_SCHEMA and temperature == 0.0
        return {"content": json.dumps({"company": "unknown", "quarter": "Q2", "year": "2024"})}


# The leak runner sends each prompt once, writes answers by accession and
# resumes past what it wrote.
def test_ask_leak_writes_and_resumes(tmp_path):
    sample = tmp_path / "leak_sample.jsonl"
    rows = [
        {"accession": "a1", "ticker": "AAA", "reaction_date": "2024-08-01", "prompt": "Which company? ...", "truth": {}},
        {"accession": "b1", "ticker": "BBB", "reaction_date": "2024-08-02", "prompt": "Which company? ...", "truth": {}},
    ]
    sample.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    answers = tmp_path / "leak_answers.jsonl"
    answers.write_text(json.dumps({"accession": "a1", "answer": "x"}) + "\n")
    writer = _Writer()
    assert rs.ask_leak(sample, answers, [writer], log=lambda s: None) == 1
    assert writer.prompts == ["Which company? ..."]
    lines = [json.loads(l) for l in answers.read_text().splitlines()]
    assert [l["accession"] for l in lines] == ["a1", "b1"]
    assert json.loads(lines[1]["answer"])["year"] == "2024"
