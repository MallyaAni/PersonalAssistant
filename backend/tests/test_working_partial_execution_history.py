"""Known actual partial fills stay visible while their original order is unresolved."""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime

import pytest

from backend.agents.trading.desk import paper
from backend.market import live_model_decision as projection
from backend.tests.test_partial_fill_receipt_absence import (
    CID,
    SINCE,
    ReadOnlySyntheticClient,
    receipt,
    saved_partial,
)

NEXT_DAY = datetime.fromisoformat("2026-10-15T10:15:00-04:00")


# Preserve the actual saved native execution when a later activity day has no broker receipt.
def test_saved_working_partial_remains_dated_execution_after_nextday_absence(tmp_path):
    from backend.cli import market_daily

    state = saved_partial(tmp_path)
    original = deepcopy(asdict(state))
    path = paper.state_path(tmp_path)
    original_bytes = path.read_bytes()
    client = ReadOnlySyntheticClient([[]])
    updated, outcomes = market_daily._reconcile(
        client, state, tmp_path, True, decision_at=NEXT_DAY
    )
    reopened = paper.load_state(tmp_path)
    assert outcomes == []
    assert asdict(updated) == asdict(reopened) == asdict(state) == original
    assert path.read_bytes() == original_bytes
    assert reopened.pending == original["pending"]
    assert projection._terminal_entry(reopened.journal[0], NEXT_DAY) is None
    rows = projection.recorded_fills(reopened.journal, NEXT_DAY)
    assert len(rows) == 1
    row = rows[0]
    assert (row["client_order_id"], row["qty"], row["price"]) == (CID, 2, 101.25)
    assert row["filled_at"] == reopened.journal[0]["execution"]["filled_at"]
    assert row["created_at"] == reopened.journal[0]["execution"]["created_at"]
    assert row["execution"] == reopened.journal[0]["execution"]
    assert row["session"] == "2026-10-13"
    assert row["original_qty"] == 8
    assert projection.recorded_fills(reopened.journal, NEXT_DAY) == rows
    assert asdict(reopened) == original
    assert client.reads == [SINCE]
    assert client.responses == []
    assert client.mutations == []


# Advance one original execution from working two to terminal five without treating both as trades.
def test_later_terminal_replaces_visible_working_partial_once(tmp_path):
    from backend.cli import market_daily

    state = saved_partial(tmp_path)
    original = deepcopy(asdict(state))
    terminal = receipt(status="filled", filled="5", price="102.5")
    terminal["filled_at"] = "2026-10-15T13:35:00Z"
    original_terminal = deepcopy(terminal)
    client = ReadOnlySyntheticClient([[], [terminal]])
    preserved, _ = market_daily._reconcile(
        client, state, tmp_path, True, decision_at=NEXT_DAY
    )
    assert asdict(preserved) == asdict(state) == original
    assert projection._terminal_entry(preserved.journal[0], NEXT_DAY) is None
    before = projection.recorded_fills(preserved.journal, NEXT_DAY)
    assert [(row["client_order_id"], row["qty"]) for row in before] == [(CID, 2)]
    updated, settled = market_daily._reconcile(
        client, preserved, tmp_path, True, decision_at=NEXT_DAY
    )
    saved = paper.load_state(tmp_path)
    assert asdict(updated) == asdict(saved)
    assert asdict(state) == original
    assert saved.pending == []
    assert len(saved.journal) == len(settled) == 1
    assert projection._terminal_entry(saved.journal[0], NEXT_DAY) is not None
    after = projection.recorded_fills(saved.journal, NEXT_DAY)
    assert len(after) == 1
    assert (after[0]["client_order_id"], after[0]["qty"], after[0]["price"]) == (
        CID, 5, 102.5,
    )
    assert after[0]["filled_at"] == original_terminal["filled_at"]
    assert projection.recorded_fills(saved.journal, NEXT_DAY) == after
    assert before[0]["qty"] == 2
    assert terminal == original_terminal
    assert client.reads == [SINCE, SINCE]
    assert client.responses == []
    assert client.mutations == []


# Invalid working receipts cannot become executions merely because their terminal flag is false.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("terminal", None),
        ("terminal", 0),
        ("terminal", "false"),
        ("terminal", []),
        ("status", "open"),
        ("status", "dead"),
        ("qty", 0),
        ("filled_qty", -1),
        ("filled_qty", 9),
        ("filled_qty", True),
        ("filled_qty", float("nan")),
        ("filled_price", 0),
    ],
)
def test_invalid_working_partial_metadata_is_withheld(tmp_path, field, value):
    state = saved_partial(tmp_path)
    original = deepcopy(asdict(state))
    invalid = deepcopy(state.journal)
    invalid[0][field] = value
    assert projection.recorded_fills(invalid, NEXT_DAY) == []
    assert asdict(state) == original


# Actual execution chronology remains mandatory for a working partial's historical visibility.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("filled_at", "2026-10-16T13:31:00Z"),
        ("filled_at", "2026-10-14T13:31:00"),
        ("submitted_at", "2026-10-14T13:32:00Z"),
        ("reconciled_at", "2026-10-14T13:30:00Z"),
    ],
)
def test_invalid_working_partial_clocks_are_withheld(tmp_path, field, value):
    state = saved_partial(tmp_path)
    original = deepcopy(asdict(state))
    invalid = deepcopy(state.journal)
    invalid[0]["execution"][field] = value
    assert projection.recorded_fills(invalid, NEXT_DAY) == []
    assert asdict(state) == original
