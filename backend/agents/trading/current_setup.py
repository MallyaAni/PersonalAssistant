"""Bounded model interpretation of dated chart facts, with no trading authority."""

import json
from pathlib import Path

from backend.core.llm import StrictSchema
from backend.core.prompts import _strip_notes
from backend.market.labels import (
    ChartConfirmation,
    ChartEntry,
    ChartExit,
    ChartPriority,
    parse,
    values,
)

# /2: the judgments come back as one strict JSON-schema structured output,
# which the engine enforces, instead of a native tool call it did not.
VERSION = "current-chart-setup/2"
SYSTEM = _strip_notes(
    "trading/current_setup", Path(__file__).with_suffix(".md").read_text()
)
ENTRIES = tuple(ChartEntry)
RELATIONS = tuple(ChartConfirmation)
# The entry words a stock with current candles may take, and those a stock
# whose entry is not permitted may take, with and without candles.
_WITH_CANDLES = (ChartEntry.READY, ChartEntry.WAIT, ChartEntry.AVOID)
_BLOCKED_WITH_CANDLES = (ChartEntry.WAIT, ChartEntry.AVOID)
_BLOCKED_WITHOUT_CANDLES = (ChartEntry.WAIT, ChartEntry.AVOID, ChartEntry.UNAVAILABLE)


# Constrain model rows to known symbols, judgments and supplied references.
def schema(facts):
    refs = sorted({key for row in facts for key in row["levels"]} | {"none"})
    properties = {
        "ticker": {"type": "string"},
        "entry": {"type": "string", "enum": values(ChartEntry)},
        "exit": {"type": "string", "enum": values(ChartExit)},
        "entry_priority": {"type": "string", "enum": values(ChartPriority)},
        "exit_priority": {"type": "string", "enum": values(ChartPriority)},
        "reason": {
            "type": "string",
            "minLength": 20,
            "maxLength": 240,
            "pattern": "^[^0-9]*$",
        },
        "confirmation": {"type": "string", "enum": values(ChartConfirmation)},
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
            "enum": [str(entry) for entry in _WITH_CANDLES]
            if fact.get("candles")
            else values(ChartEntry),
        }
        if not fact["entry_permitted"] or not fact.get("candles"):
            fields["entry"] = {
                "type": "string",
                "enum": [str(entry) for entry in _BLOCKED_WITH_CANDLES]
                if fact.get("candles")
                else [str(entry) for entry in _BLOCKED_WITHOUT_CANDLES],
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
    entry = parse(ChartEntry, row["entry"], "Unknown judgment")
    parse(ChartExit, row["exit"], "Unknown judgment")
    for key in ("entry_priority", "exit_priority"):
        parse(ChartPriority, row[key], "Unknown priority")
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
    confirmation = parse(ChartConfirmation, row["confirmation"], "Unknown confirmation")
    if (confirmation is ChartConfirmation.NONE) != (row["confirmation_ref"] == "none"):
        raise ValueError("Incomplete confirmation")
    if entry is ChartEntry.UNAVAILABLE and fact.get("candles"):
        raise ValueError("Supplied chart evidence cannot be called unavailable")
    if entry is ChartEntry.READY and (
        not fact["entry_permitted"] or not fact.get("candles")
    ):
        raise ValueError("Entry policy violation")


# Ask the installed model once for a strict structured answer the engine holds
# to the schema; failed inference never becomes a buy judgment.
def assess(facts, writer):
    if not facts or writer is None:
        return []
    try:
        reply = writer.chat(
            [
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps({"stocks": facts}, allow_nan=False),
                },
            ],
            min(8192, 256 + 280 * len(facts)),
            StrictSchema(schema(facts)),
            # Greedy, as the tool call was: the same chart reads the same way.
            0.0,
        )
        data = json.loads(reply["content"])
        return validate(list(data["rows"].values()), facts)
    except Exception:  # noqa: BLE001 - display judgments fail closed
        return []
