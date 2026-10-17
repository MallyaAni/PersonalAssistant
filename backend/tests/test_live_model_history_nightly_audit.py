"""Saved-night pre-plan reconstruction must not use current planning outputs."""

from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from backend.agents.trading.desk import nightly_plan, paper
from backend.market import live_model_history_nightly_audit as audit
from backend.tests.test_live_model_history_verification import receipts


# Supply only a prior funded intent and independently checked original request/outcome.
def fixture():
    value, intents = receipts()
    cid, intent = next(iter(intents.items()))
    prior = paper.PaperState(
        pending=[deepcopy(intent)],
        sessions_seen=["2021-01-04"],
        order_seq=7,
        opened={"AAA": "2021-01-04"},
        allocation_state={"prior": "verified control, not today's saved output"},
    )
    return prior, {cid: value["attempts"][0]}, {cid: value["fills"][0]}


# Supply an explicit conserved cancellation record, distinct from a cancel request.
def cancel_map(previous, accepted):
    cid = next(iter(accepted))
    return {
        cid: {
            **deepcopy(previous.pending[0]),
            "status": "dead",
            "terminal": True,
            "filled_qty": 0,
            "execution": {
                **previous.pending[0]["execution"],
                "created_at": accepted[cid]["at"],
                "submitted_at": accepted[cid]["at"],
                "canceled_at": "2021-01-05T21:01:00+00:00",
            },
        }
    }


# Fold submitted3/fill2 into funded5 without a broker or state writes.
def test_before_plan_retains_prior_controls_and_original_partial_receipt():
    previous, accepted, outcomes = fixture()
    before = deepcopy((asdict(previous), accepted, outcomes))
    state, settled, withdrawn = audit.before_plan(
        previous, accepted, outcomes, "2021-01-05", "2021-01-05T16:01:00-05:00"
    )
    assert not state.pending and not withdrawn
    assert state.order_seq == 7 and state.sessions_seen == ["2021-01-04"]
    assert state.opened == previous.opened
    assert state.allocation_state == previous.allocation_state
    assert settled[0].qty == 5 and settled[0].filled_qty == 2
    assert settled[0].status == "partial" and settled[0].terminal
    assert state.journal[0]["execution"]["decision_at"] == "2021-01-04T16:01:00-05:00"
    assert (asdict(previous), accepted, outcomes) == before


# Derive the original stale-request cancellation without calling a cancel method.
def test_before_plan_reconciles_working_then_canceled_request_in_order():
    previous, accepted, _ = fixture()
    cid = next(iter(accepted))
    cancellations = cancel_map(previous, accepted)
    before = deepcopy((accepted, cancellations))
    with pytest.raises(ValueError, match="confirmed cancellation receipt set"):
        audit.before_plan(
            previous, accepted, {}, "2021-01-05", "2021-01-05T16:01:00-05:00"
        )
    state, settled, withdrawn = audit.before_plan(
        previous,
        accepted,
        {},
        "2021-01-05",
        "2021-01-05T16:01:00-05:00",
        cancellations=cancellations,
    )
    assert withdrawn == [previous.pending[0]["client_order_id"]]
    assert [row.status for row in settled] == ["open", "dead"]
    assert not state.pending
    assert state.journal[0]["execution"]["canceled_at"] == "2021-01-05T21:01:00+00:00"
    assert accepted[next(iter(accepted))]["accepted"] is True
    assert (accepted, cancellations) == before
    for part in ("canceled_at", "created_at", "submitted_at"):
        changed = deepcopy(cancellations)
        changed[cid]["execution"][part] = "2021-01-05T20:01:00+00:00"
        with pytest.raises(ValueError, match="cancellation evidence"):
            audit.before_plan(
                previous,
                accepted,
                {},
                "2021-01-05",
                "2021-01-05T16:01:00-05:00",
                cancellations=changed,
            )


# Preserve a future unsent window rather than invent a terminal missing outcome.
def test_before_plan_keeps_future_pending_and_names_event_wait():
    previous, _, _ = fixture()
    previous.pending[0]["execute_on"] = "2021-01-06"
    state, settled, _ = audit.before_plan(
        previous, {}, {}, "2021-01-05", "2021-01-05T16:01:00-05:00"
    )
    assert not settled and state.pending == previous.pending
    assert audit.branch(state, {"calendar_known": True, "factor": 1}, "2021-01-05") == {
        "path": "event_priority",
        "reason": "pending_settlement",
        "model_required": False,
    }


# Refuse unknown acknowledged requests or outcomes instead of guessing their settlement.
@pytest.mark.parametrize("missing", ["accepted", "outcome_accepted", "clock"])
def test_before_plan_refuses_missing_or_inconsistent_original_evidence(missing):
    previous, accepted, outcomes = fixture()
    if missing == "accepted":
        previous.pending[0]["execution"]["created_at"] = accepted[next(iter(accepted))][
            "at"
        ]
        accepted, outcomes = {}, {}
    elif missing == "outcome_accepted":
        accepted = {}
    else:
        outcomes[next(iter(outcomes))]["at"] = "2021-01-06T14:45:00+00:00"
    with pytest.raises(ValueError, match="submission|accepted|outcome"):
        audit.before_plan(
            previous, accepted, outcomes, "2021-01-05", "2021-01-05T16:01:00-05:00"
        )


# Classify every branch and count only ordinary unseen sessions as model calls.
@pytest.mark.parametrize(
    ("state", "event", "problem", "path", "reason"),
    [
        (
            paper.PaperState(),
            {"calendar_known": True, "factor": 1},
            None,
            "model",
            None,
        ),
        (
            paper.PaperState(sessions_seen=["2021-01-05"]),
            {"calendar_known": True, "factor": 1},
            None,
            "already_planned",
            None,
        ),
        (
            paper.PaperState(),
            {"calendar_known": False, "factor": None},
            None,
            "event_priority",
            "calendar_unavailable",
        ),
        (
            paper.PaperState(event_cycle={"id": "original-cycle"}),
            {"calendar_known": True, "factor": 1},
            None,
            "event_priority",
            "existing_event_cycle",
        ),
        (
            paper.PaperState(),
            {"calendar_known": True, "factor": 0.5},
            None,
            "event_priority",
            "event_reduction",
        ),
        (
            paper.PaperState(),
            None,
            "missing_held_close",
            "nightly_broker_unavailable",
            "missing_held_close",
        ),
        (
            paper.PaperState(),
            None,
            "unknown_exchange_cash_in_lieu",
            "nightly_broker_unavailable",
            "unknown_exchange_cash_in_lieu",
        ),
    ],
)
def test_nightly_branch_does_not_count_bypasses_as_model_inference(
    state, event, problem, path, reason
):
    actual = audit.branch(state, event, "2021-01-05", account_problem=problem)
    assert actual == {"path": path, "reason": reason, "model_required": path == "model"}


# The real dispatcher bypasses the model for event protection or unknown calendars.
@pytest.mark.parametrize(
    "event",
    [
        {"calendar_known": False, "factor": None},
        {"calendar_known": True, "factor": 0.5, "decision_date": "2021-01-06"},
    ],
)
def test_event_dispatch_never_calls_the_model(event):
    # A forbidden model proves event paths do not masquerade as numeric evaluations.
    def forbidden(*args):
        raise AssertionError("Event branch must not evaluate the model")

    policy = SimpleNamespace(version="grade-led-learned-sizing/1", plan=forbidden)
    orders, state, _ = nightly_plan.plan(
        "2021-01-05",
        paper.PaperState(),
        100000,
        {},
        {},
        {},
        {},
        event,
        finished={},
        entry_blocked=set(),
        entries={},
        cash=100000,
        holding_policy=policy,
        report=None,
    )
    assert not orders and state.policy_version == policy.version


# Reject saved settlement corruption against independently reconstructed state.
def test_archived_settled_core_requires_original_identity_quantity_and_clocks():
    previous, accepted, outcomes = fixture()
    _, settled, _ = audit.before_plan(
        previous, accepted, outcomes, "2021-01-05", "2021-01-05T16:01:00-05:00"
    )
    saved = [{**asdict(row), "filled": row.filled_qty} for row in settled]
    audit.compare_settled(saved, settled)
    for name, value in (
        ("qty", 999),
        ("filled", 3),
        ("terminal", False),
        ("client_order_id", "new-id"),
        ("execution", {}),
    ):
        changed = deepcopy(saved)
        changed[0][name] = value
        with pytest.raises(ValueError, match="settlement evidence"):
            audit.compare_settled(changed, settled)


# Refuse incomplete event evidence rather than guessing ordinary model permission.
@pytest.mark.parametrize(
    "event",
    [
        {},
        {"calendar_known": True},
        {"calendar_known": True, "factor": True},
        {"calendar_known": True, "factor": 0.75},
        {"calendar_known": False, "factor": 1},
    ],
)
def test_incomplete_event_evidence_cannot_become_model_evaluation(event):
    with pytest.raises(ValueError, match="Independent|independent"):
        audit.branch(paper.PaperState(), event, "2021-01-05")


# A different day, in-session clock or weekend cannot stand for the original close.
@pytest.mark.parametrize(
    ("session", "at"),
    [
        ("2021-01-05", "2021-01-05T15:45:00-05:00"),
        ("2021-01-05", "2021-01-06T16:01:00-05:00"),
        ("2021-01-09", "2021-01-09T16:01:00-05:00"),
    ],
)
def test_before_plan_requires_exact_original_completed_session(session, at):
    with pytest.raises(ValueError, match="completed-close clock"):
        audit.before_plan(paper.PaperState(), {}, {}, session, at)


# Reject unknown, current-session or already terminal cancellation identities.
@pytest.mark.parametrize(
    "change", ["unknown", "current_session", "terminal", "wrong_id"]
)
def test_cancellations_cannot_be_claimed_outside_the_original_stale_working_set(change):
    previous, accepted, outcomes = fixture()
    cancellations = cancel_map(previous, accepted)
    cid = next(iter(accepted))
    if change == "unknown":
        cancellations["unknown"] = deepcopy(cancellations[cid])
    elif change == "current_session":
        previous.pending[0]["session"] = "2021-01-05"
    elif change == "wrong_id":
        cancellations[cid]["client_order_id"] = "unknown"
    before = deepcopy((asdict(previous), accepted, outcomes, cancellations))
    with pytest.raises(ValueError, match="cancellation"):
        audit.before_plan(
            previous,
            accepted,
            outcomes if change == "terminal" else {},
            "2021-01-05",
            "2021-01-05T16:01:00-05:00",
            cancellations=cancellations,
        )
    assert (asdict(previous), accepted, outcomes, cancellations) == before
