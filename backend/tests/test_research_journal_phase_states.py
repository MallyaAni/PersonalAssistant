"""Expose completed independent replay states without changing any execution.

All inputs are synthetic. The original book and funded controls produce the
journals; no historical study, provider, private account or model is used.
"""

import copy
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import simulate
from backend.market.allocation_controls import constant_exposure
from backend.market.research_journal import ResearchJournal
from backend.market.research_journal_replay import (
    verify_archive,
    verify_payload,
    verify_snapshot,
)

STATE_FIELDS = {
    "seq",
    "event_id",
    "session",
    "session_index",
    "type",
    "phase",
    "cash",
    "positions",
    "fees",
    "traded",
}


# Encode the public transport contract independently of the recorder and verifier.
def _bytes(value):
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


# Rebind deliberately changed events so accounting failures reach the real ledger.
def _rehash(snapshot):
    for name in ("events", "prices"):
        content = _bytes(snapshot[name])
        snapshot["manifest"]["files"][f"{name}.json"] = {
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    return snapshot


# Repair sequence identifiers while retaining deliberately invalid ordering.
def _resequence(snapshot):
    for seq, event in enumerate(snapshot["events"]):
        event.update(seq=seq, event_id=f"event-{seq:06d}")
    return _rehash(snapshot)


# Attach a real recorder to a fully declared synthetic source grid.
def _journal(sessions, symbols, opens, closes, cost_bps=100):
    return ResearchJournal(
        sessions,
        symbols,
        opens,
        closes,
        run_id="synthetic-phase-states",
        account_id="synthetic-research-account",
        policy_id="synthetic-ledger-fixture/1",
        cost_bps=cost_bps,
        provenance={"evidence_basis": "synthetic-accounting-test"},
    )


# Execute real split fills with a source warm-up row and a no-fill carry session.
def _split_journal():
    sessions = np.array(
        ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"],
        dtype="datetime64[D]",
    )
    opens = np.array([[10, 20], [10, 20], [10, 20], [12, 24], [15, 30]])
    closes = np.array([[10, 20], [10, 20], [11, 22], [13, 26], [12, 35]])
    journal = _journal(sessions, ("TEST0", "TEST1"), opens, closes)
    book = simulate._Book(
        2,
        100,
        100,
        SimpleNamespace(tickers=("TEST0", "TEST1")),
        None,
        sessions,
        journal=journal,
    )
    journal.open_account(1, book.cash, book.shares)
    book.observe_mark(1, book.equity(closes[1]))
    for session, target in ((2, [2.0, 1.0]), (4, [1.0, 2.0])):
        order = np.array(target)
        book.observe_decision(session - 1, order, reason="synthetic split")
        book._fill_split(
            order,
            opens[session],
            closes[session],
            recycle_sells=False,
            session=session,
        )
        book.observe_mark(session, book.equity(closes[session]))
        if session == 2:
            book.observe_mark(3, book.equity(closes[3]))
    journal.finish(4, book.cash, book.shares, book.traded, pending={})
    return journal


# Return the public payload path without coupling tests to replay internals.
def _payload(snapshot, **options):
    return verify_payload(
        snapshot["manifest"], snapshot["events"], snapshot["prices"], **options
    )


# Publish only post-event reconstructed balances with cumulative costs and notional.
def test_split_phase_states_preserve_dates_order_carry_and_hand_calculated_balances():
    snapshot = _split_journal().snapshot()
    result = verify_snapshot(snapshot, include_phase_states=True)
    assert result["ok"], result["errors"]
    states = result["phase_states"]
    assert [state["seq"] for state in states] == [0, 4, 6, 11, 13]
    assert [state["event_id"] for state in states] == [
        f"event-{seq:06d}" for seq in (0, 4, 6, 11, 13)
    ]
    assert [state["session"] for state in states] == [
        "2024-01-03",
        "2024-01-04",
        "2024-01-04",
        "2024-01-08",
        "2024-01-08",
    ]
    assert [state["session_index"] for state in states] == [1, 2, 2, 4, 4]
    assert [state["type"] for state in states] == ["open_account"] + ["fill_batch"] * 4
    assert [state["phase"] for state in states] == [
        None,
        "open",
        "close",
        "open",
        "close",
    ]
    assert all(set(state) == STATE_FIELDS for state in states)
    assert [state["cash"] for state in states] == pytest.approx(
        [100, 59.6, 59.6, 29.3, 41.18]
    )
    assert [state["positions"] for state in states] == [
        [0, 0],
        [2, 1],
        [2, 1],
        [2, 2],
        [1, 2],
    ]
    assert [state["fees"] for state in states] == pytest.approx(
        [0, 0.4, 0.4, 0.7, 0.82]
    )
    assert [state["traded"] for state in states] == [0, 40, 40, 70, 82]
    carry = result["marks"][2]
    assert carry["session"] == "2024-01-05"
    assert carry["positions"] == states[2]["positions"]
    assert carry["cash"] == states[2]["cash"]
    assert result["marks"][-1]["nav"] == pytest.approx(123.18)
    assert states[-1]["fees"] == result["total_fees"]
    assert states[-1]["traded"] == result["total_traded"]
    assert states[-1]["cash"] == result["marks"][-1]["cash"]
    assert states[-1]["positions"] == result["marks"][-1]["positions"]
    assert result["pending_semantics_verified"] is False
    assert result["adoption_eligible"] is False


# Keep the established report exactly unchanged unless the caller explicitly opts in.
@pytest.mark.parametrize("verify", [verify_snapshot, _payload])
def test_default_and_explicit_false_preserve_report_and_original_snapshot(verify):
    snapshot = _split_journal().snapshot()
    original = _bytes(snapshot)
    default = verify(snapshot)
    explicit_false = verify(snapshot, include_phase_states=False)
    enabled = verify(snapshot, include_phase_states=True)
    assert default["ok"]
    assert "phase_states" not in default
    assert _bytes(default) == _bytes(explicit_false)
    assert _bytes(default) == _bytes(
        {key: value for key, value in enabled.items() if key != "phase_states"}
    )
    assert _bytes(snapshot) == original


# Retain an opening account with no invented fill or mark entries in its phase trace.
def test_cash_only_account_returns_only_its_opening_state():
    sessions = ["2024-01-02", "2024-01-03", "2024-01-04"]
    prices = np.full((3, 1), 100.0)
    journal = _journal(sessions, ("TEST0",), prices, prices)
    journal.open_account(0, 100, [0])
    for session in range(3):
        journal.mark(session, 100, [0], 100, 0)
    journal.finish(2, 100, [0], 0, pending={})
    result = verify_snapshot(journal.snapshot(), include_phase_states=True)
    assert result["ok"], result["errors"]
    assert result["phase_states"] == [
        {
            "seq": 0,
            "event_id": "event-000000",
            "session": "2024-01-02",
            "session_index": 0,
            "type": "open_account",
            "phase": None,
            "cash": 100,
            "positions": [0],
            "fees": 0,
            "traded": 0,
        }
    ]


# Price gaps and fees retain the actual funded control's quantities rather than targets.
@pytest.mark.parametrize("symbol", ["SPY", "QQQ"])
@pytest.mark.parametrize("cost_bps", [10, 25])
def test_funded_control_states_reconcile_without_changing_execution(symbol, cost_bps):
    sessions = ["2024-01-02", "2024-01-03", "2024-01-04"]
    opens = np.array([100.0, 200.0, 90.0])
    closes = np.array([100.0, 150.0, 100.0])
    journal = _journal(sessions, (symbol,), opens[:, None], closes[:, None], cost_bps)
    nav = constant_exposure(
        closes,
        opens,
        1.0,
        cost_bps,
        journal=journal,
        sessions=sessions,
        symbol=symbol,
    )
    snapshot = journal.snapshot()
    result = verify_snapshot(snapshot, include_phase_states=True)
    assert result["ok"], result["errors"]
    states = result["phase_states"]
    assert len(states) == 3
    assert [state["phase"] for state in states] == [None, "open", "open"]
    assert states[1]["positions"][0] == pytest.approx(
        1 / (200 * (1 + cost_bps / 10000))
    )
    assert 0 < states[1]["positions"][0] < 0.01
    for state, mark in zip(states, result["marks"], strict=True):
        assert state["cash"] == mark["cash"]
        assert state["positions"] == mark["positions"]
        assert state["traded"] == mark["traded"]
    assert states[-1]["fees"] == result["total_fees"]
    assert [mark["nav"] for mark in result["marks"]] == pytest.approx(nav)


# Return independently computed values even when producer roundoff is tolerated.
def test_phase_states_do_not_reset_to_within_tolerance_producer_balances():
    snapshot = _split_journal().snapshot()
    expected = verify_snapshot(snapshot, include_phase_states=True)["phase_states"]
    final_fill = snapshot["events"][13]
    final_fill["cash_after"] += 5e-13
    final_fill["positions_after"][0] += 5e-13
    final_fill["residual_units"][0] = -5e-13
    final_fill["unfilled_reasons"][0] = "not_filled_in_batch"
    result = verify_snapshot(_rehash(snapshot), include_phase_states=True)
    assert result["ok"], result["errors"]
    assert result["phase_states"] == expected
    assert result["phase_states"][-1]["cash"] != final_fill["cash_after"]
    assert result["phase_states"][-1]["positions"] != final_fill["positions_after"]
    assert result["max_reconciliation_residual"]["cash"] > 0
    assert result["max_reconciliation_residual"]["units"] > 0


# Isolate returned snapshots from source events, daily marks and every other phase.
def test_phase_positions_do_not_alias_input_marks_or_each_other():
    snapshot = _split_journal().snapshot()
    source_before = copy.deepcopy(snapshot)
    result = verify_snapshot(snapshot, include_phase_states=True)
    states = result["phase_states"]
    expected_states = copy.deepcopy(states)
    expected_marks = copy.deepcopy(result["marks"])
    expected_terminal = copy.deepcopy(result["terminal"])
    assert len({id(state["positions"]) for state in states}) == len(states)
    states[0]["positions"][0] = 999
    states[-1]["positions"][0] = 888
    assert states[1:-1] == expected_states[1:-1]
    assert result["marks"] == expected_marks
    assert result["terminal"] == expected_terminal
    assert snapshot == source_before
    snapshot["events"][4]["positions_after"][0] = 777
    assert states[1] == expected_states[1]
    assert (
        verify_snapshot(source_before, include_phase_states=True)["phase_states"]
        == expected_states
    )


# Build real-account corruptions that fail at distinct original verifier boundaries.
def _corrupted(kind):
    snapshot = _split_journal().snapshot()
    events = snapshot["events"]
    if kind == "hash":
        events[13]["cash_after"] += 1
        return snapshot
    if kind == "accounting":
        events[13]["cash_after"] += 1
    elif kind == "incomplete":
        events.pop()
    elif kind == "terminal":
        events[-1]["positions"][0] += 1
    elif kind == "post_finish":
        events.append(copy.deepcopy(events[-1]))
    elif kind == "phase_order":
        events[10:14] = [events[12], events[10], events[11], events[13]]
    elif kind == "closing_mark":
        events[-2]["nav"] += 1
    elif kind == "missing_mark":
        events.pop(-2)
    elif kind == "held_price":
        snapshot["prices"]["close"][3][0] = None
    else:
        raise AssertionError(f"unknown corruption: {kind}")
    return _resequence(snapshot)


# Never release a partial phase trace, including failures after every fill replayed.
@pytest.mark.parametrize("verify", [verify_snapshot, _payload])
@pytest.mark.parametrize(
    ("kind", "error"),
    [
        ("hash", "SHA256 mismatch"),
        ("accounting", "cash_after"),
        ("incomplete", "finish event missing"),
        ("terminal", "finish positions"),
        ("post_finish", "post-finish event"),
        ("phase_order", "open execution reordered after close"),
        ("closing_mark", "mark NAV"),
        ("missing_mark", "finish missing complete daily marks"),
        ("held_price", "held closing mark unavailable"),
    ],
)
def test_failed_proof_omits_phase_states_and_preserves_existing_failure(
    verify, kind, error
):
    snapshot = _corrupted(kind)
    default = verify(snapshot)
    enabled = verify(snapshot, include_phase_states=True)
    assert not enabled["ok"]
    assert error in enabled["errors"][0]
    assert "phase_states" not in enabled
    assert enabled == default


# Reject malformed snapshot envelopes without leaking any newly requested state.
@pytest.mark.parametrize("snapshot", [None, [], {}, {"events": []}])
def test_bad_snapshot_envelope_preserves_failure_without_phase_trace(snapshot):
    result = verify_snapshot(snapshot, include_phase_states=True)
    assert not result["ok"]
    assert "phase_states" not in result
    assert result == verify_snapshot(snapshot)


# Export through the real archive boundary without modifying the immutable files.
@pytest.mark.parametrize("manifest_path", [False, True])
def test_archive_opt_in_preserves_bytes_and_matches_snapshot(tmp_path, manifest_path):
    journal = _split_journal()
    destination = tmp_path / "synthetic-account"
    journal.archive(destination)
    before = {path.name: path.read_bytes() for path in destination.iterdir()}
    requested = destination / "manifest.json" if manifest_path else destination
    default = verify_archive(requested)
    assert default == verify_archive(requested, include_phase_states=False)
    result = verify_archive(requested, include_phase_states=True)
    assert result == verify_snapshot(journal.snapshot(), include_phase_states=True)
    assert result["ok"]
    assert "phase_states" not in default
    assert {path.name: path.read_bytes() for path in destination.iterdir()} == before


# Preserve archive read failures and withhold traces even when opt-in is requested.
def test_missing_archive_has_no_partial_phase_trace(tmp_path):
    requested = tmp_path / "missing" / "manifest.json"
    result = verify_archive(requested, include_phase_states=True)
    assert not result["ok"]
    assert "phase_states" not in result
    assert result == verify_archive(requested)


# Reject hostile archive paths or contents before any trace can leave verification.
@pytest.mark.parametrize(
    ("kind", "error"),
    [
        ("directory_link", "symlink path rejected"),
        ("source_link", "local regular file required"),
        ("noncanonical", "noncanonical or changed bytes"),
        ("duplicate_key", "duplicate JSON key"),
        ("hash", "SHA256 mismatch"),
        ("accounting", "cash_after"),
    ],
)
def test_hostile_archive_withholds_trace_and_preserves_failure(tmp_path, kind, error):
    journal = _split_journal()
    destination = tmp_path / "synthetic-account"
    journal.archive(destination)
    requested = destination
    if kind == "directory_link":
        requested = tmp_path / "linked-account"
        requested.symlink_to(destination, target_is_directory=True)
    elif kind == "source_link":
        original = destination / "events.json"
        relocated = tmp_path / "moved-synthetic-events.json"
        original.rename(relocated)
        original.symlink_to(relocated)
    elif kind == "noncanonical":
        source = destination / "events.json"
        source.write_bytes(source.read_bytes() + b"\n")
    elif kind == "duplicate_key":
        source = destination / "manifest.json"
        source.write_bytes(b'{"schema":"duplicate",' + source.read_bytes()[1:])
    else:
        snapshot = _corrupted(kind)
        for name in ("manifest", "prices", "events"):
            (destination / f"{name}.json").write_bytes(_bytes(snapshot[name]))
    before = {path.name: path.read_bytes() for path in destination.iterdir()}
    default = verify_archive(requested)
    result = verify_archive(requested, include_phase_states=True)
    assert not result["ok"]
    assert error in result["errors"][0]
    assert "phase_states" not in result
    assert result == default
    assert {path.name: path.read_bytes() for path in destination.iterdir()} == before


class _NoTruthiness:
    # Detect accidental execution of user-supplied truthiness instead of a Boolean gate.
    def __bool__(self):
        raise AssertionError("option truthiness must not be called")


# Require a Boolean opt-in without invoking truthiness or accepting ambiguous flags.
@pytest.mark.parametrize("option", [None, 0, 1, "true", [], {}, _NoTruthiness()])
@pytest.mark.parametrize("verify", [verify_snapshot, _payload])
def test_phase_trace_opt_in_rejects_non_boolean_without_callbacks(option, verify):
    result = verify(_split_journal().snapshot(), include_phase_states=option)
    assert result["ok"] is False
    assert result["errors"] == ["include_phase_states must be Boolean"]
    assert "phase_states" not in result
