"""Streaming composition cannot replace independent lineage with saved controls."""

import gzip
import json
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import paper
from backend.market import calendar, entry_timing
from backend.market import live_model_history_nightly_model as numerical
from backend.market import live_model_history_stream_audit as audit
from backend.market.live_model_history_receipts import ReceiptLedger
from backend.tests.test_live_model_history_nightly_model import analytic_policy, records
from backend.tests.test_live_model_history_pending_audit import evidence, fixture


# Start a private synthetic composition at an already independently derived boundary.
def stream_boundary(state=None):
    result = audit.StreamAudit.__new__(audit.StreamAudit)
    result.state = paper.PaperState() if state is None else deepcopy(state)
    result.intents, result.receipts = {}, ReceiptLedger()
    result.held, result.chain = {"AAA": 10}, "0" * 64
    result.counts = dict.fromkeys(
        (
            "nights",
            "model",
            "event_priority",
            "already_planned",
            "nightly_broker_unavailable",
            "intraday_transitions",
            "filled_receipts",
        ),
        0,
    )
    result.completion = {"actual_started_at": "2026-10-17T12:00:00+00:00"}
    result.verified_at = datetime(2026, 10, 17, 14, tzinfo=UTC)
    return result


# Assemble synthetic expected outputs from a separate pure planning invocation.
def planned_target(policy, shown, previous, observed, *, attempts=None):
    session = str(shown.panel.dates[-1])
    at = (
        datetime.combine(
            shown.panel.dates[-1].astype(object),
            calendar.session_close(shown.panel.dates[-1].astype(object)),
            calendar.NEW_YORK,
        )
        + entry_timing.BAR / 15
    )
    attempts = [] if attempts is None else attempts
    accepted = {row["client_order_id"]: row for row in attempts if row["accepted"]}
    before, settled, _ = audit.controls.before_plan(
        previous, {}, {}, session, at.isoformat()
    )
    state, planned, entry, _ = numerical.pure_plan(
        shown, policy, before, observed, session, at.isoformat(), attempts, accepted
    )
    if state.start_equity is None:
        state.start_equity = observed["equity"]
    full_entry = {
        **entry,
        "written": "2026-10-17T13:00:00+00:00",
        "pl": observed["equity"] - state.start_equity,
        "pl_pct": observed["equity"] / state.start_equity - 1,
        "settled": [],
    }
    state.history = [row for row in previous.history if row["session"] != session] + [
        full_entry
    ]
    return {
        "session": session,
        "nightly": {
            "session": session,
            "at": at.isoformat(),
            "status": "planned",
            "persisted_policy": state.policy_version,
            "entry": numerical.serialized(full_entry),
        },
        "attempts": attempts,
        "new_intents": numerical.serialized(planned),
        "paper_state": numerical.serialized(asdict(state)),
    }, numerical.serialized(asdict(state))


# Inspect exact same-close metadata without using acknowledgments to select quantities.
def test_new_acknowledgments_are_unique_same_close_receipts():
    row = {
        "client_order_id": "original",
        "at": "2019-03-01T16:01:00-05:00",
        "accepted": True,
    }
    assert audit.candidate_acknowledgments([row], {}, row["at"]) == {"original": row}
    with pytest.raises(ValueError, match="Duplicate"):
        audit.candidate_acknowledgments([row, row], {}, row["at"])
    with pytest.raises(ValueError, match="clock"):
        audit.candidate_acknowledgments([row], {}, "2019-03-04T16:01:00-05:00")


# The saved target can be compared but cannot supply the next state or action quantity.
@pytest.mark.parametrize(
    "corruption", [None, "target", "action", "state", "quantity_float"]
)
def test_connected_nightly_comparison_recomputes_controls_and_quantities(
    monkeypatch, corruption
):
    policy, shown = analytic_policy()
    stream = stream_boundary()
    stream.policy, stream.reader = policy, policy.reader
    stream.panel, stream.raw = shown.panel, SimpleNamespace(grades=None, eligible=None)
    observed = numerical.account(
        9000, {"AAA": 10}, {"AAA": 100}, [], records(), {"AAA": 100}
    )
    value, expected = planned_target(policy, shown, stream.state, observed)

    # Fix the synthetic report; native integration covers actual frozen prefixes.
    def report(*args):
        return shown

    # Record selected synthetic rows without loading a native model in this fixture.
    def select(day):
        assert day == len(shown.panel.dates) - 1

    # Existing prefix properties have their own actual-feature tests.
    def prefix(*args):
        return {"synthetic": True}

    monkeypatch.setattr(audit.continuation, "close_report", report)
    monkeypatch.setattr(stream.reader, "select", select, raising=False)
    monkeypatch.setattr(numerical, "prefix_model", prefix)
    if corruption == "target":
        value["nightly"]["entry"]["joint_funded"]["targets"]["AAA"] = 0.9
    elif corruption == "action":
        value["nightly"]["entry"]["actions"][0]["order_quantity"] = 999
    elif corruption == "state":
        value["paper_state"]["opened"] = {"invented": "2019-01-01"}
    elif corruption == "quantity_float":
        value["paper_state"]["order_seq"] = float(value["paper_state"]["order_seq"])
    before = deepcopy(value)
    if corruption is None:
        mode = stream.nightly(value, len(shown.panel.dates) - 1, stream.state, observed)
        assert mode["path"] == "model"
        assert numerical.serialized(asdict(stream.state)) == expected
        assert stream.counts["model"] == 1
    else:
        with pytest.raises(ValueError, match="differ|required"):
            stream.nightly(value, len(shown.panel.dates) - 1, stream.state, observed)
        assert stream.counts["nights"] == 0
    assert value == before


# Account failures preserve derived intraday state across consecutive closing sessions.
def test_prior_unavailable_state_propagates_without_saved_controls_or_reconciliation(
    monkeypatch,
):
    previous, expected, value, accepted, raw = fixture()
    derived, _ = audit.pending.fold_pending(
        previous,
        evidence(value),
        accepted,
        {},
        raw,
        0,
        value["session"],
        conserved_attempts=value["attempts"],
    )
    stream = stream_boundary(previous)

    # The first-account failure must precede reconciliation and model calls.
    def forbidden(*args, **kwargs):
        raise AssertionError("Unavailable account must retain pre-reconciliation state")

    monkeypatch.setattr(audit.controls, "before_plan", forbidden)
    monkeypatch.setattr(audit.continuation, "close_report", forbidden)
    for session in ("2019-03-01", "2019-03-04"):
        at = session + "T16:01:00-05:00"
        target = {
            "session": session,
            "nightly": {
                "session": session,
                "at": at,
                "text": "",
                "status": "nightly_broker_unavailable",
                "reason": "Fresh raw held mark unavailable for AAA",
            },
            "new_intents": [],
            "attempts": [],
            "paper_state": numerical.serialized(asdict(expected)),
        }
        stream.nightly(
            target,
            0,
            derived,
            {"problem": "missing_held_close", "missing_symbols": ["AAA"]},
        )
        assert stream.state == expected
        derived = stream.state
    assert stream.counts["nightly_broker_unavailable"] == 2
    assert stream.counts["model"] == 0
    assert stream.state.journal == previous.journal
    assert stream.state.history == previous.history


# Event reductions/restorations and duplicate closes cannot count as fresh model plans.
@pytest.mark.parametrize("branch", ["reduction", "restoration", "duplicate"])
def test_connected_nonmodel_paths_keep_actual_orders_and_zero_model_counts(
    monkeypatch, branch
):
    policy, shown = analytic_policy()
    stream = stream_boundary()
    stream.policy, stream.reader = policy, policy.reader
    stream.panel, stream.raw = shown.panel, SimpleNamespace(grades=None, eligible=None)
    session = str(shown.panel.dates[-1])
    day = shown.panel.dates[-1].astype(object)
    at = datetime.combine(
        day, calendar.session_close(day), calendar.NEW_YORK
    ) + timedelta(minutes=1)
    event = {
        "calendar_known": True,
        "factor": 0.5 if branch == "reduction" else 1.0,
        "decision_date": (day + timedelta(days=1)).isoformat()
        if branch == "reduction"
        else session,
    }
    quantity = 5 if branch == "restoration" else 10
    observed = numerical.account(
        10000 - quantity * 100,
        {"AAA": quantity},
        {"AAA": 100},
        [],
        records(),
        {"AAA": 100},
    )
    if branch == "duplicate":
        stream.state.sessions_seen = [session]
    elif branch == "restoration":
        stream.state.event_cycle = {
            "id": "original-event",
            "decision_date": session,
            "baseline": {"AAA": 10.0},
        }
        stream.state.journal = [
            {
                "client_order_id": "old-original-sale",
                "symbol": "AAA",
                "side": "sell",
                "qty": 5,
                "filled_qty": 5,
                "event_id": "original-event",
            }
        ]
    attempts = (
        []
        if branch == "duplicate"
        else [
            {
                "client_order_id": paper.order_id(
                    session, "AAA", "buy" if branch == "restoration" else "sell", 0
                ),
                "symbol": "AAA",
                "side": "buy" if branch == "restoration" else "sell",
                "qty": 5,
                "at": at.astimezone(UTC).isoformat(),
                "accepted": True,
                "reason": None,
                "observed_price": 100,
                "available_cash": observed["cash"],
            }
        ]
    )

    # Fix the explicit event fixture independently of current calendar publication.
    def event_decision(panel):
        return event

    # Any distribution call would falsely turn an event/duplicate into model inference.
    def forbidden(*args, **kwargs):
        raise AssertionError("No numeric distribution on event or duplicate branch")

    # Reuse the synthetic report with the actual dispatcher and action builder.
    def report(*args):
        return shown

    # Selecting a synthetic date is metadata only, with no model invocation.
    def select(day):
        return None

    monkeypatch.setattr(audit.event_risk, "decision", event_decision)
    monkeypatch.setattr(audit.continuation, "close_report", report)
    monkeypatch.setattr(stream.reader, "distribution", forbidden)
    monkeypatch.setattr(stream.reader, "select", select, raising=False)
    monkeypatch.setattr(numerical, "prefix_model", forbidden)
    value, expected = planned_target(
        policy, shown, stream.state, observed, attempts=attempts
    )
    mode = stream.nightly(value, len(shown.panel.dates) - 1, stream.state, observed)
    assert mode["path"] == (
        "already_planned" if branch == "duplicate" else "event_priority"
    )
    assert stream.counts["model"] == 0
    assert numerical.serialized(asdict(stream.state)) == expected
    assert [row["qty"] for row in stream.intents.values()] == (
        [] if branch == "duplicate" else [5]
    )


# Missing initial acknowledgments fail coverage instead of adopting an order.
def test_initial_immediate_submission_without_standalone_receipt_fails(monkeypatch):
    policy, shown = analytic_policy(grades=(1, 3))
    stream = stream_boundary()
    stream.policy, stream.reader = policy, policy.reader
    stream.panel, stream.raw = shown.panel, SimpleNamespace(grades=None, eligible=None)
    session = str(shown.panel.dates[-1])
    day = shown.panel.dates[-1].astype(object)
    at = datetime.combine(
        day, calendar.session_close(day), calendar.NEW_YORK
    ) + timedelta(minutes=1)
    observed = numerical.account(
        9000, {"AAA": 10}, {"AAA": 100}, [], records(), {"AAA": 100}
    )

    # Feed the declared synthetic daily report without constructing a broker.
    def report(*args):
        return shown

    # Keep this coverage test independent of frozen native model acceptance.
    def select(day):
        return None

    # Prefix implementation is exercised separately and in genuine native integration.
    def prefix(*args):
        return {"synthetic": True}

    monkeypatch.setattr(audit.continuation, "close_report", report)
    monkeypatch.setattr(stream.reader, "select", select, raising=False)
    monkeypatch.setattr(numerical, "prefix_model", prefix)
    value = {
        "session": session,
        "nightly": {"at": at.isoformat()},
        "paper_state": {"journal": []},
        "attempts": [],
    }
    with pytest.raises(
        ValueError, match="UNRECONSTRUCTIBLE_INITIAL_IMMEDIATE_RECEIPTS"
    ):
        stream.nightly(
            value, len(shown.panel.dates) - 1, stream.state, observed, initial=True
        )
    assert stream.counts["nights"] == 0


# A false successful cancellation cannot enter through a current allocation field.
def test_cancellation_extraction_selects_only_exact_original_receipt_fields():
    at = "2019-03-01T16:01:00-05:00"
    row = {
        "client_order_id": "old",
        "symbol": "AAA",
        "side": "buy",
        "qty": 5,
        "status": "dead",
        "terminal": True,
        "filled_qty": 0,
        "allocation_state": {"must_not_enter": True},
        "execution": {
            "created_at": at,
            "submitted_at": at,
            "canceled_at": at,
            "unrelated": True,
        },
    }
    value = {"paper_state": {"journal": [row]}}
    selected = audit.cancellation_receipts(value, {"old": {}}, {}, at)
    assert "allocation_state" not in selected["old"]
    assert set(selected["old"]["execution"]) == {
        "created_at",
        "submitted_at",
        "canceled_at",
    }
    assert row["execution"]["unrelated"]
    with pytest.raises(ValueError, match="Unconserved"):
        audit.cancellation_receipts(value, {}, {}, at)


# External archive identities and bounded decoding reject malformed original inputs.
def test_stream_archive_reading_requires_pins_and_strict_json(tmp_path):
    path = tmp_path / "initial.json.gz"
    path.write_bytes(gzip.compress(b'{"x":1,"x":2}'))
    with pytest.raises(ValueError, match="Duplicate"):
        audit.archive_value(audit.pinned(path, sha256(path.read_bytes()).hexdigest()))
    with pytest.raises(ValueError, match="Pinned"):
        audit.pinned(path, "0" * 64)
    with pytest.raises(ValueError, match="Nonfinite"):
        audit.archive_value(gzip.compress(b'{"x":NaN}'))


# Standalone initial receipts cannot be substituted with an arbitrary in-memory list.
def test_initial_receipts_require_independently_pinned_file(tmp_path):
    path = tmp_path / "receipts.json"
    path.write_text(json.dumps([{"client_order_id": "original"}]))
    receipts = audit.InitialReceipts(path, sha256(path.read_bytes()).hexdigest())
    assert receipts.attempts() == [{"client_order_id": "original"}]
    with pytest.raises(ValueError, match="standalone"):
        stream_boundary().initial(receipts=[])


# Session quote views retain global indices while storing one readonly day of prices.
def test_quote_prefix_uses_readonly_global_views_and_exact_raw_identity(
    tmp_path, monkeypatch
):
    stream = stream_boundary()
    stream.market = tmp_path
    stream.panel = SimpleNamespace(
        dates=np.array(["2019-02-28", "2019-03-01"], dtype="datetime64[D]"),
        tickers=("AAA",),
    )
    path = tmp_path / "bars_15m_sip/asof=2019-03-01/AAA.parquet"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"authenticated fixture raw source")
    stream.completion["input_sha256"] = {
        str(path): sha256(path.read_bytes()).hexdigest()
    }
    bars = [SimpleNamespace(open=100, close=101), SimpleNamespace(open=102, close=103)]

    # Return a tiny explicit complete session after its physical fixture hash passed.
    def read(*args):
        return bars, None, {"complete": "true"}

    monkeypatch.setattr(audit.intraday_sip, "read_session_full", read)
    raw = stream.quote_prefix(1)
    assert raw.observation_close.shape == (2, 25, 1)
    assert raw.session_open.shape == (2, 1)
    assert raw.observation_close.strides[0] == 0
    assert str(raw.dates[1]) == "2019-03-01"
    assert raw.tickers == ("AAA",)
    assert raw.observation_close[1, 0, 0] == 101
    assert np.isnan(raw.observation_close[1, 1, 0])
    with pytest.raises(ValueError, match="read-only"):
        raw.observation_close[1, 0, 0] = 999
    path.write_bytes(b"corrupt raw file")
    with pytest.raises(ValueError, match="Pinned"):
        stream.quote_prefix(1)
