"""The statement reader's contract (A2), without a model.

What has to hold: the prompt loads from its file and names the relative
quarter labels it reads; the schema requires every field (an optional
field is one the model skips) and bounds the probability and the
direction; a schema-shaped answer becomes a StatementCall whose stance is
the probability less one half; a direction on the wrong side of the
probability is kept and flagged, never silently corrected; an answer that
does not parse, a direction outside the enum or a probability outside
[0, 1] degrades to None; a missing runtime degrades to None; the writer is
called greedily with the schema and the block as the user turn.
"""

import json

import pytest

from backend.agents.trading import statement_reader as sr


class Writer:
    """A fake writer that returns a fixed JSON content and records the call."""

    def __init__(self, content):
        self.content = content
        self.calls = []

    def chat(self, messages, max_tokens, schema, temperature):
        self.calls.append((messages, max_tokens, schema, temperature))
        return {"content": self.content}


def test_the_prompt_loads_and_explains_the_relative_labels():
    assert "Q1" in sr._SYSTEM
    assert "Q8" in sr._SYSTEM
    assert "Q9" in sr._SYSTEM
    assert "Q5" in sr._SYSTEM
    assert sr.PROMPT_VERSION == "statements/1"


def test_the_schema_requires_every_field_and_bounds_them():
    schema = sr.schema()
    assert set(schema["required"]) == {"direction", "probability", "rationale"}
    assert schema["additionalProperties"] is False
    assert schema["properties"]["direction"]["enum"] == [sr.UP, sr.DOWN]
    assert schema["properties"]["probability"]["minimum"] == 0
    assert schema["properties"]["probability"]["maximum"] == 1
    assert schema["properties"]["rationale"]["maxLength"] == sr.MAX_RATIONALE


def test_a_schema_shaped_answer_becomes_a_call_with_its_stance():
    writer = Writer(
        json.dumps(
            {
                "direction": "up",
                "probability": 0.7,
                "rationale": "Revenue rises each quarter. Margins hold. Risk is capex.",
            }
        )
    )
    call = sr.StatementReader(writer).call_sync("Line  Q1\nRevenue 1.0")
    assert call is not None
    assert call.direction == "up"
    assert call.probability == pytest.approx(0.7)
    assert call.stance == pytest.approx(0.2)
    assert call.consistent
    messages, max_tokens, schema, temperature = writer.calls[0]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == sr._SYSTEM
    assert messages[1] == {"role": "user", "content": "Line  Q1\nRevenue 1.0"}
    assert temperature == 0.0
    assert schema == sr.schema()
    assert max_tokens == 500


def test_a_direction_on_the_wrong_side_is_kept_and_flagged():
    writer = Writer(
        json.dumps({"direction": "down", "probability": 0.8, "rationale": "x" * 30})
    )
    call = sr.StatementReader(writer).call_sync("block")
    assert call is not None
    assert call.direction == "down"
    assert call.probability == pytest.approx(0.8)
    assert not call.consistent


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        json.dumps(
            {"direction": "sideways", "probability": 0.5, "rationale": "x" * 30}
        ),
        json.dumps({"direction": "up", "probability": 1.5, "rationale": "x" * 30}),
        json.dumps({"direction": "up", "rationale": "x" * 30}),
    ],
)
def test_an_answer_outside_the_contract_degrades_to_none(content):
    assert sr.StatementReader(Writer(content)).call_sync("block") is None


def test_a_missing_runtime_or_an_empty_block_degrades_to_none():
    assert sr.StatementReader(None).call_sync("block") is None
    writer = Writer("{}")
    assert sr.StatementReader(writer).call_sync("   ") is None
    assert writer.calls == []


def test_the_rationale_is_bounded():
    writer = Writer(
        json.dumps({"direction": "up", "probability": 0.6, "rationale": "y" * 2000})
    )
    call = sr.StatementReader(writer).call_sync("block")
    assert call is not None
    assert len(call.rationale) == sr.MAX_RATIONALE
