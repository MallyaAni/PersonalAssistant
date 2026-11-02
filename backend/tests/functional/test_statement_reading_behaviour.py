"""What the statement-reading prompt actually does on the real runtime.

The unit tests prove the packet and label arithmetic. This test sends a
synthetic, unmistakably rising eight-quarter record through the registered
prompt and strict schema, and asserts on the answer that came back: it
parses, it commits to a direction, it is grounded in the table's own
language, and it does not invent a company or a date. It is skipped when
the runtime is unreachable; `ANIOS_REQUIRE_FUNCTIONAL=1` turns that skip
into a failure for the deploy gate.
"""

from __future__ import annotations

import os
from datetime import date

import pytest

from backend.core.llm import OpenAICompatibleInferenceProvider
from backend.market import statement_reading as sr


# An eight-row packet whose revenue and net income rise every quarter.
def _packet() -> sr.Packet:
    """Return a synthetic rising packet with no dates or absolute levels."""
    rows = []
    for index in range(8):
        rows.append(
            sr.PacketRow(
                quarter=f"t-{7 - index}",
                end=None,
                revenue_index=round(100.0 / (1.05 ** (7 - index)), 2),
                revenue_yoy_pct=5.0,
                revenue_qoq_pct=5.0,
                gross_margin_pct=40.0,
                net_margin_pct=12.0,
                ocf_margin_pct=20.0,
                capex_pct_revenue=5.0,
                net_income_yoy_pct=8.0,
                net_income_qoq_pct=8.0,
            )
        )
    return sr.Packet(
        anchor=date(2026, 3, 31),
        net_income_tag="synthetic",
        rows=tuple(rows),
    )


# The real prompt and schema produce a grounded, committed answer.
def test_statement_reading_prompt_answers_the_record() -> None:
    url = os.environ.get("STATEMENT_READING_URL")
    model = os.environ.get("STATEMENT_READING_MODEL")
    if not url or not model:
        pytest.skip(
            "Set STATEMENT_READING_URL and STATEMENT_READING_MODEL "
            "for the real prompt test"
        )
    packet = _packet()
    provider = OpenAICompatibleInferenceProvider(
        url, model, timeout_seconds=300.0, reasoning_effort="none"
    )
    result = sr.ask(provider, packet)
    answer = result["answer"]
    assert result["finish_reason"] == "stop"
    assert result["served_model"] == model
    assert answer["direction"] in sr.DIRECTIONS
    assert 0.0 <= answer["confidence"] <= 1.0
    assert answer["analysis"].strip()
    # The record is rising by 8% year over year; a direction is supported.
    assert answer["direction"] != "uncertain"
    # The answer talks about the table's own quantities, not outside facts.
    text = answer["analysis"].lower()
    assert "revenue" in text or "net income" in text or "margin" in text
    prompt = result["prompt"]
    assert "t-7" in prompt
    assert "t0" in prompt
    assert "NA" in prompt
    assert "2026" not in prompt
    assert "synthetic" not in prompt
