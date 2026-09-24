"""The recorder must preserve observations, missing sources and immutable archives."""

import hashlib
import json

import numpy as np
import pytest

from backend.market.research_journal import ResearchJournal


# Build a synthetic recorder with a named security whose prices are missing.
def _journal():
    sessions = np.array(
        ["2024-01-02", "2024-01-03", "2024-01-04"], dtype="datetime64[D]"
    )
    opens = np.array([[90, np.nan], [100, np.nan], [105, np.nan]])
    closes = np.array([[100, np.nan], [110, np.nan], [120, np.nan]])
    return ResearchJournal(
        sessions,
        ("TEST", "MISSING"),
        opens,
        closes,
        run_id="synthetic-test-run",
        account_id="synthetic-test-account",
        policy_id="test-policy/1",
        cost_bps=10,
        provenance={"basis": "synthetic fixture; not historical evidence"},
        raw_prices={"open": 2 * opens, "close": 2 * closes},
    )


# Preserve one small funded path without deriving its fills from requested weights.
def _record_complete(journal):
    journal.open_account(0, 101, [0, 0])
    journal.mark(0, 101, [0, 0], 101, 0)
    decision = journal.decision(0, [1, 0], [1, 0], "test entry")
    journal.fill_batch(
        decision,
        1,
        "open",
        [1, 0],
        [100, np.nan],
        [0, 0],
        101,
        [1, 0],
        0.9,
        101,
        1,
        False,
    )
    journal.mark(1, 0.9, [1, 0], 110.9, 100)
    journal.mark(2, 0.9, [1, 0], 120.9, 100)
    journal.finish(2, 0.9, [1, 0], 100, {})
    return journal


# Canonical fixture hashing remains independent of the recorder's encoder helper.
def _bytes(value):
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


# Source and event hashes bind all named cells, including explicit unavailable ones.
def test_snapshot_preserves_observed_state_and_research_limitations():
    snapshot = _record_complete(_journal()).snapshot()
    manifest, prices, events = (
        snapshot["manifest"],
        snapshot["prices"],
        snapshot["events"],
    )
    assert manifest["status"] == "complete"
    assert manifest["price_basis"] == "adjusted_synthetic_units"
    assert manifest["cash_yield"] == 0
    assert "not_actual_settlement" in manifest["cash_model"]
    for field in (
        "historical_availability_verified",
        "security_identity_verified",
        "settlement_verified",
        "adoption_eligible",
    ):
        assert manifest[field] is False
    assert prices["open"] == [[90.0, None], [100.0, None], [105.0, None]]
    assert prices["raw"]["close"] == [[200.0, None], [220.0, None], [240.0, None]]
    assert len(events) == 7
    assert [event["seq"] for event in events] == list(range(7))
    assert events[2]["decision_id"] == "decision-000002"
    fill = events[3]
    assert fill["filled_units"] == [1, 0]
    assert fill["notional"] == [100, 0]
    assert fill["fees"] == pytest.approx([0.1, 0])
    assert fill["cash_after"] == 0.9
    assert fill["price_ref"] == {
        "file": "prices.json",
        "field": "open",
        "session_index": 1,
    }
    assert events[-1]["positions"] == [1, 0]
    assert events[-1]["pending"] == {}
    for name in ("prices", "events"):
        body = _bytes(snapshot[name])
        assert manifest["files"][f"{name}.json"] == {
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
        }


# Caller-owned inputs, metadata and returned snapshots cannot rewrite retained evidence.
def test_input_and_snapshot_mutations_do_not_change_journal():
    opens = np.array([[1.0], [2.0]])
    closes = opens.copy()
    metadata = {"source": {"name": "original"}}
    journal = ResearchJournal(
        ["2024-01-02", "2024-01-03"],
        ["TEST"],
        opens,
        closes,
        run_id="run",
        account_id="account",
        policy_id="policy",
        cost_bps=0,
        provenance=metadata,
    )
    opens[:] = 999
    metadata["source"]["name"] = "changed"
    journal.open_account(0, 1, [0])
    units = np.array([1.0])
    decision_metadata = {"gate": ["original"]}
    journal.decision(0, units, metadata=decision_metadata)
    units[:] = 999
    decision_metadata["gate"].append("changed")
    snapshot = journal.snapshot()
    snapshot["prices"]["open"][0][0] = 777
    snapshot["events"][1]["submitted_units"][0] = 777
    fresh = journal.snapshot()
    assert fresh["prices"]["open"] == [[1], [2]]
    assert fresh["manifest"]["provenance"] == {"source": {"name": "original"}}
    assert fresh["events"][1]["submitted_units"] == [1]
    assert fresh["events"][1]["metadata"] == {"gate": ["original"]}


# Input binding admits missing cells but refuses changed sources or costs.
@pytest.mark.parametrize("mismatch", ["open", "close", "date", "symbols", "cost"])
def test_assert_inputs_fails_closed_on_producer_mismatch(mismatch):
    journal = _journal()
    sessions = journal.sessions
    symbols = journal.symbols
    opens = np.array([[90, np.nan], [100, np.nan], [105, np.nan]])
    closes = np.array([[100, np.nan], [110, np.nan], [120, np.nan]])
    journal.assert_inputs(sessions, symbols, opens, closes, 10)
    cost = 10
    if mismatch == "open":
        opens[1, 0] += 1
    elif mismatch == "close":
        closes[1, 0] += 1
    elif mismatch == "date":
        sessions[-1] = np.datetime64("2024-01-05")
    elif mismatch == "symbols":
        symbols = tuple(reversed(symbols))
    else:
        cost = 11
    with pytest.raises(ValueError, match="differ"):
        journal.assert_inputs(sessions, symbols, opens, closes, cost)


# Filled units follow observed changes even when an intention asks for much more.
def test_partial_fill_and_adjustment_keep_request_separate_from_execution():
    journal = _journal()
    journal.open_account(0, 100.1, [0, 0])
    decision = journal.decision(0, [10, 0], [1, np.nan], "partial test")
    journal.adjustment(decision, 1, "open", [5, 0], "gate reduced requested quantity")
    journal.fill_batch(
        decision,
        1,
        "open",
        [5, 0],
        [100, np.nan],
        [0, 0],
        100.1,
        [1, 0],
        0,
        100.1,
        0.2,
        False,
    )
    fill = journal.snapshot()["events"][-1]
    assert fill["submitted_units"] == [5, 0]
    assert fill["filled_units"] == [1, 0]
    assert fill["residual_units"] == [4, 0]
    assert fill["unfilled_reasons"] == ["cash_budget_limited", None]
    journal.finish(2, 0, [1, 0], 100, {})
    assert journal.snapshot()["events"][-1]["pending"] == {}


# An explicit no-op batch preserves blocked prices and unavailable intention cells.
def test_noop_missing_price_batch_keeps_zero_actual_fills():
    journal = _journal()
    journal.open_account(0, 101, [0, 0])
    decision = journal.decision(0, [np.nan, 1])
    journal.fill_batch(
        decision,
        1,
        "open",
        [np.nan, 1],
        [100, np.nan],
        [0, 0],
        101,
        [0, 0],
        101,
        101,
        0,
        False,
    )
    fill = journal.snapshot()["events"][-1]
    assert fill["filled_units"] == [0, 0]
    assert fill["fees"] == [0, 0]
    assert fill["residual_units"] == [None, 1]
    assert fill["unfilled_reasons"] == [
        "submitted_units_unavailable",
        "price_unavailable",
    ]


# Invalid observed cash is rejected, never serialized as a fictional missing balance.
@pytest.mark.parametrize("cash", [float("nan"), float("inf"), True])
def test_nonfinite_observed_state_is_rejected(cash):
    journal = _journal()
    with pytest.raises(ValueError, match="finite number"):
        journal.open_account(0, cash, [0, 0])
    assert journal.snapshot()["events"] == []


# Missing held prices remain unavailable without making an observer stop its producer.
def test_unavailable_mark_preserves_null_nav_and_named_missing_holding():
    journal = _journal()
    journal.open_account(0, 101, [0, 1])
    journal.mark(0, 101, [0, 1], np.nan, 0)
    event = journal.snapshot()["events"][-1]
    assert event["nav"] is None
    assert event["cash"] == 101
    assert event["positions"] == [0, 1]
    assert event["unavailable_held_symbols"] == ["MISSING"]
    assert b"NaN" not in _bytes(journal.snapshot())


# A filled holding cannot acquire a price by turning an unavailable cell into zero.
def test_observed_fill_at_missing_price_is_not_recorded():
    journal = _journal()
    journal.open_account(0, 101, [0, 0])
    decision = journal.decision(0, [0, 1])
    with pytest.raises(ValueError, match="finite positive price"):
        journal.fill_batch(
            decision,
            1,
            "open",
            [0, 1],
            [100, np.nan],
            [0, 0],
            101,
            [0, 1],
            1,
            101,
            1,
            False,
        )
    assert len(journal.snapshot()["events"]) == 2


# Explicit failure and unfinished recording remain different from successful completion.
def test_failed_and_incomplete_journals_never_claim_complete():
    journal = _journal()
    journal.open_account(0, 101, [0, 0])
    assert journal.snapshot()["manifest"]["status"] == "recording"
    journal.finish(0, 101, [0, 0], 0, {"retry": True}, status="failed")
    assert journal.snapshot()["manifest"]["status"] == "failed"
    with pytest.raises(ValueError, match="finished journal"):
        journal.mark(1, 101, [0, 0], 101, 0)


# Queue evidence stays explicit and cannot refer to an undeclared security or field.
@pytest.mark.parametrize(
    "pending",
    [{"unknown": True}, {"deferred_units": {"OTHER": 1}}, {"retry": "yes"}],
)
def test_unknown_pending_shape_is_rejected(pending):
    journal = _journal()
    journal.open_account(0, 101, [0, 0])
    with pytest.raises(ValueError, match="pending|Deferred"):
        journal.finish(2, 101, [0, 0], 0, pending)
    assert journal.snapshot()["manifest"]["status"] == "recording"


# Retain explicitly queued intent and event state without mutating caller-owned arrays.
def test_pending_queue_keeps_nullable_intent_and_explicit_retry_state():
    journal = _journal()
    journal.open_account(0, 101, [0, 0])
    decision = journal.decision(0, [np.nan, 1])
    pending = {
        "decision_id": decision,
        "submitted_units": np.array([np.nan, 1]),
        "deferred_units": {"MISSING": 1},
        "event_state": {
            "baseline_units": np.array([2, 0]),
            "sold_units": np.array([1, 0]),
        },
        "retry": True,
    }
    journal.finish(2, 101, [0, 0], 0, pending)
    pending["submitted_units"][:] = 999
    retained = journal.snapshot()["events"][-1]["pending"]
    assert retained["submitted_units"] == [None, 1]
    assert retained["deferred_units"] == {"MISSING": 1}
    assert retained["event_state"] == {
        "baseline_units": [2, 0],
        "sold_units": [1, 0],
    }
    assert retained["retry"] is True


# New archives persist byte-identical sources/events and cannot be overwritten on retry.
def test_archive_persists_and_preserves_every_file(tmp_path):
    journal = _record_complete(_journal())
    destination = tmp_path / "new-archive"
    manifest = journal.archive(destination)
    assert manifest == destination / "manifest.json"
    before = {path.name: path.read_bytes() for path in destination.iterdir()}
    for name in ("manifest", "prices", "events"):
        assert before[f"{name}.json"] == _bytes(journal.snapshot()[name])
    with pytest.raises(FileExistsError):
        journal.archive(destination)
    assert before == {path.name: path.read_bytes() for path in destination.iterdir()}


# A fresh target under a symlink or a parent traversal is outside the archive boundary.
@pytest.mark.parametrize("kind", ["symlink", "traversal"])
def test_archive_rejects_symlink_and_parent_traversal(tmp_path, kind):
    actual = tmp_path / "actual"
    actual.mkdir()
    if kind == "symlink":
        link = tmp_path / "link"
        link.symlink_to(actual, target_is_directory=True)
        destination = link / "new"
    else:
        destination = actual / ".." / "new"
    with pytest.raises(ValueError, match="symlinks|traversal"):
        _journal().archive(destination)
    assert not (actual / "new").exists()
    assert not (tmp_path / "new").exists()


# Recording may be preserved after interruption, but no successful finish is invented.
def test_incomplete_archive_retains_recording_status(tmp_path):
    journal = _journal()
    journal.open_account(0, 101, [0, 0])
    path = journal.archive(tmp_path / "interrupted")
    manifest = json.loads(path.read_bytes())
    events = json.loads((path.parent / "events.json").read_bytes())
    assert manifest["status"] == "recording"
    assert not any(event["type"] == "finish" for event in events)
