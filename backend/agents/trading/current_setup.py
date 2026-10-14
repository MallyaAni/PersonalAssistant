"""Bounded model interpretation of dated chart facts, with no trading authority."""

import json
from pathlib import Path

from backend.core.prompts import _strip_notes

VERSION = "current-chart-setup/1"
SYSTEM = _strip_notes(
    "trading/current_setup", Path(__file__).with_suffix(".md").read_text()
)
ENTRIES = ("ready", "wait", "avoid", "unavailable")
RELATIONS = ("hold_above", "reclaim_above", "none")


# Constrain model rows to known symbols, judgments and supplied references.
def schema(facts):
    refs = sorted({key for row in facts for key in row["levels"]} | {"none"})
    properties = {
        "ticker": {"type": "string"},
        "entry": {"type": "string", "enum": list(ENTRIES)},
        "exit": {"type": "string", "enum": ["review", "hold"]},
        "entry_priority": {"type": "string", "enum": ["high", "medium", "low"]},
        "exit_priority": {"type": "string", "enum": ["high", "medium", "low"]},
        "reason": {
            "type": "string",
            "minLength": 20,
            "maxLength": 240,
            "pattern": "^[^0-9]*$",
        },
        "confirmation": {"type": "string", "enum": list(RELATIONS)},
        "confirmation_ref": {"type": "string", "enum": refs},
        "invalidation_ref": {"type": "string", "enum": refs},
    }
    rows = {}
    for fact in facts:
        fields = {**properties, "ticker": {"type": "string", "const": fact["ticker"]}}
        refs = list(fact["levels"]) + ["none"]
        fields["confirmation_ref"] = fields["invalidation_ref"] = {
            "type": "string",
            "enum": refs,
        }
        fields["entry"] = {
            "type": "string",
            "enum": ["ready", "wait", "avoid"]
            if fact.get("candles")
            else list(ENTRIES),
        }
        if not fact["entry_permitted"] or not fact.get("candles"):
            fields["entry"] = {
                "type": "string",
                "enum": ["wait", "avoid"]
                if fact.get("candles")
                else ["wait", "avoid", "unavailable"],
            }
        rows[fact["ticker"]] = {
            "type": "object",
            "additionalProperties": False,
            "required": list(fields),
            "properties": fields,
        }
    return {
        "title": "CurrentChartSetups",
        "type": "object",
        "additionalProperties": False,
        "required": ["rows"],
        "properties": {
            "rows": {
                "type": "object",
                "additionalProperties": False,
                "required": list(rows),
                "properties": rows,
            }
        },
    }


# Reject incomplete batches before validating each stock's grounded judgment.
def validate(rows, facts):
    by_name = {row["ticker"]: row for row in facts}
    if len(rows) != len(by_name) or {row.get("ticker") for row in rows} != set(by_name):
        raise ValueError("Incomplete judgment universe")
    for row in rows:
        validate_row(row, by_name[row["ticker"]])
    return rows


# Reject fabricated levels, prose numbers and judgments outside entry permission.
def validate_row(row, fact):
    if row["entry"] not in ENTRIES or row["exit"] not in ("review", "hold"):
        raise ValueError("Unknown judgment")
    if any(
        row[key] not in ("high", "medium", "low")
        for key in ("entry_priority", "exit_priority")
    ):
        raise ValueError("Unknown priority")
    reason = row["reason"]
    if (
        not isinstance(reason, str)
        or not 20 <= len(reason) <= 240
        or any(c.isdigit() for c in reason)
    ):
        raise ValueError("Ungrounded judgment prose")
    for key in ("confirmation_ref", "invalidation_ref"):
        if row[key] != "none" and row[key] not in fact["levels"]:
            raise ValueError("Unknown stock level")
    if row["confirmation"] not in RELATIONS:
        raise ValueError("Unknown confirmation")
    if (row["confirmation"] == "none") != (row["confirmation_ref"] == "none"):
        raise ValueError("Incomplete confirmation")
    if row["entry"] == "unavailable" and fact.get("candles"):
        raise ValueError("Supplied chart evidence cannot be called unavailable")
    if row["entry"] == "ready" and (
        not fact["entry_permitted"] or not fact.get("candles")
    ):
        raise ValueError("Entry policy violation")


# Ask the installed model once; failed inference never becomes a buy judgment.
def assess(facts, writer):
    if not facts or writer is None:
        return []
    try:
        reply = writer.chat_with_tools(
            [
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps({"stocks": facts}, allow_nan=False),
                },
            ],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "record_chart_setups",
                        "description": (
                            "Record grounded chart judgments, including waits and "
                            "avoids. Display analysis only; never execute trades."
                        ),
                        "parameters": schema(facts),
                    },
                }
            ],
            max_tokens=min(8192, 256 + 280 * len(facts)),
        )
        calls = reply.get("tool_calls") or []
        if (
            len(calls) != 1
            or calls[0].get("function", {}).get("name") != "record_chart_setups"
        ):
            return []
        data = json.loads(calls[0]["function"]["arguments"])
        return validate(list(data["rows"].values()), facts)
    except Exception:  # noqa: BLE001 - display judgments fail closed
        return []
