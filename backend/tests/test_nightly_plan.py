"""The shared boundary preserves existing planners and records their exact inputs."""

import json
from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from backend.agents.trading.desk import (
    event_execution,
    event_risk,
    live_policy,
    nightly_plan,
    paper,
)
from backend.cli import market_daily
from backend.tests.test_market_daily import (
    _Broker,
    _midcycle_state,
    _report,
    _stretch_report,
)


# Include an unheld downgrade to detect accidental paper-account filtering.
def _inputs(*, event=False):
    report = _stretch_report(
        {"KEEP": 100.0, "ENTRY": 120.0, "DROP": 100.0, "UNHELD": 100.0},
        {"KEEP": "A", "ENTRY": "A+", "DROP": "B", "UNHELD": "C"},
    )
    inputs = nightly_plan.build(report, str(report.panel.dates[-1]))
    _, flags = market_daily._band_blocked(report)
    inputs = nightly_plan.complete(
        inputs,
        {"calendar_known": True, "factor": 1.0, "decision_date": "2026-09-16"},
        flags,
        entries=None if event else market_daily._price_entries(report),
        downgrades=None
        if event
        else market_daily._downgraded(report, dict.fromkeys(inputs["grades"], 1)),
    )
    return report, inputs


# The pre-refactor dispatch, using the original account-dependent downgrade helper.
def _direct(report, inputs, state, held, cash, *, force=False):
    policy = inputs["event_policy"]
    event_active = bool(state.event_cycle) or policy.get("factor") == event_risk.REDUCED
    if state.pending or event_active or not policy["calendar_known"]:
        return event_execution.plan(
            inputs["session"], state, held, inputs["prices"], cash, policy
        )
    return paper.plan(
        inputs["session"],
        state,
        100000,
        held,
        inputs["prices"],
        inputs["targets"],
        inputs["grades"],
        finished=market_daily._downgraded(report, held),
        force_rebalance=force,
        entry_blocked={s for s, flag in inputs["blocking_flags"].items() if flag},
        entries=inputs["entries"],
        cash=cash,
    )


# Every existing branch produces exactly the same ordered orders and next state.
@pytest.mark.parametrize(
    "case",
    [
        "rebalance",
        "forced",
        "midcycle",
        "cash",
        "retry",
        "seen",
        "event",
        "restore",
        "pending",
        "calendar",
    ],
)
def test_shared_dispatch_matches_original_and_does_not_mutate(case):
    report, inputs = _inputs(event=case in {"event", "restore", "pending", "calendar"})
    held = {"KEEP": 100.0, "DROP": 40.0}
    state = paper.PaperState(
        policy_version=live_policy.ACTIVE,
        last_rebalance="2026-09-01",
        sessions_since_rebalance=1,
        rebalance_targets={"KEEP": 0.2},
    )
    cash = 86000.0
    if case == "rebalance":
        state.last_rebalance = None
    elif case == "cash":
        cash = 250.0
    elif case == "retry":
        state.deferred_buys = {"KEEP": 25.0, "DROP": 8.0}
    elif case == "seen":
        state.sessions_seen = [inputs["session"]]
    elif case == "event":
        inputs["event_policy"]["factor"] = event_risk.REDUCED
    elif case == "restore":
        state.event_cycle = {
            "id": "test-event",
            "decision_date": "2026-09-01",
            "baseline": {"KEEP": 150.0},
        }
        state.journal = [
            {
                "event_id": "test-event",
                "side": "sell",
                "symbol": "KEEP",
                "filled_qty": 50,
            }
        ]
    elif case == "pending":
        state.pending = [{"symbol": "KEEP", "qty": 3, "side": "buy"}]
    elif case == "calendar":
        inputs["event_policy"]["calendar_known"] = False
    original = deepcopy((inputs, state, held))
    expected = _direct(
        report, inputs, deepcopy(state), held, cash, force=case == "forced"
    )
    actual = nightly_plan.plan(
        json.loads(json.dumps(inputs)),
        state,
        100000,
        held,
        cash,
        force_rebalance=case == "forced",
    )
    assert actual == expected
    assert (inputs, state, held) == original
    assert actual[1] is not state
    actual[1].policy_version = "caller stamp"
    assert state.policy_version == live_policy.ACTIVE


# Raw executable prices are distinct from split-adjusted bands, without rounding.
def test_construction_keeps_price_bases_exact_and_all_account_independent_names():
    report, _ = _inputs()
    report = replace(report, panel=replace(report.panel, close=report.panel.close * 2))
    inputs = nightly_plan.build(report, str(report.panel.dates[-1]))
    assert inputs["prices"]["ENTRY"] == 240.0
    assert report.panel.adj_close[-1, report.panel.index("ENTRY")] == 120.0
    assert inputs["targets"] == live_policy.targets(report)
    assert nightly_plan.record_targets(inputs) == live_policy.record_targets(report)
    assert "SPY" in inputs["prices"]
    assert "SPY" not in inputs["grades"]
    assert "SPY" not in inputs["targets"]
    assert inputs["entry_basis"] == "adjusted_close_bollinger_z"
    assert not {"held", "cash", "equity", "state", "force_rebalance"} & inputs.keys()


# One shared block can close different downgraded holdings in independent accounts.
def test_downgrades_are_filtered_by_the_supplied_account_not_the_paper_account():
    _, inputs = _inputs()
    assert set(inputs["downgrades"]) == {"DROP", "UNHELD"}
    state = paper.PaperState(last_rebalance="2026-09-01", sessions_since_rebalance=1)
    for symbol in ("DROP", "UNHELD"):
        orders, _, _ = nightly_plan.plan(inputs, state, 100000, {symbol: 5}, 0)
        assert [(o.symbol, o.qty) for o in orders if o.side == "sell"] == [(symbol, 5)]


# An event-only record is not silently treated as complete ordinary-session data.
def test_ordinary_dispatch_refuses_unevaluated_entry_inputs():
    _, inputs = _inputs(event=True)
    with pytest.raises(ValueError, match="not evaluated"):
        nightly_plan.plan(inputs, paper.PaperState(), 100000, {}, 100000)


# The actual nightly dry-run carries the block without submitting or rewriting state.
def test_nightly_record_uses_exact_planner_inputs_without_recalculation(
    tmp_path, monkeypatch
):
    broker = _Broker(cash=90000, positions={"SNDK": 100})
    _midcycle_state(tmp_path, monkeypatch, broker)
    before = paper.state_path(tmp_path).read_bytes()
    report = _report()
    entry = market_daily.paper_trade(report, tmp_path, "2026-09-03", False)
    inputs = deepcopy(entry["planner_inputs"])
    assert inputs["downgrades"] == {
        "IREN": "graded C; the desk wants the money elsewhere"
    }

    # The record must reuse captured inputs rather than calculate a second version.
    def must_not_recompute(*args, **kwargs):
        pytest.fail("Record must use the values supplied to the planner")

    monkeypatch.setattr(market_daily, "_band_blocked", must_not_recompute)
    monkeypatch.setattr(live_policy, "record_targets", must_not_recompute)
    monkeypatch.setattr(event_risk, "decision", must_not_recompute)
    record = market_daily.record(report, paper=entry)
    assert record["planner_inputs"] == inputs
    assert "planner_inputs" not in record["paper"]
    assert record["targets"] == nightly_plan.record_targets(inputs)
    assert record["event_risk"]["factor"] == inputs["event_policy"]["factor"]
    record["planner_inputs"]["prices"]["SNDK"] = 999
    assert entry["planner_inputs"]["prices"]["SNDK"] == 100
    assert paper.state_path(tmp_path).read_bytes() == before
    assert broker.sent == []


# Event protection remains available even if ordinary entry calculation would fail.
def test_nightly_event_does_not_evaluate_entries_or_downgrades(tmp_path, monkeypatch):
    broker = _Broker(cash=90000, positions={"SNDK": 100})
    _midcycle_state(tmp_path, monkeypatch, broker)
    monkeypatch.setattr(
        event_risk,
        "decision",
        lambda panel: {
            "calendar_known": True,
            "factor": event_risk.REDUCED,
            "decision_date": "2026-09-16",
        },
    )

    # An event branch must remain independent of ordinary-entry calculations.
    def must_not_evaluate(*args, **kwargs):
        pytest.fail("Event protection must not depend on ordinary-entry calculation")

    monkeypatch.setattr(market_daily, "_price_entries", must_not_evaluate)
    monkeypatch.setattr(market_daily, "_downgraded", must_not_evaluate)
    entry = market_daily.paper_trade(_report(), tmp_path, "2026-09-03", False)
    assert entry["plan"] == "FOMC reduction"
    assert entry["planner_inputs"]["entries"] is None
    assert entry["planner_inputs"]["downgrades"] is None
    assert broker.sent == []


# Old records remain readable and never invent evidence of an account planner call.
@pytest.mark.parametrize("entry", [None, {"equity": 100000}, {"planner_inputs": {}}])
def test_legacy_record_keeps_existing_targets_and_no_fabricated_input_block(entry):
    report = _report()
    result = market_daily.record(report, paper=entry)
    assert result["planner_inputs"] is None
    assert result["targets"] == live_policy.record_targets(report)


# A live-policy migration is decided before reconciliation, exactly as before.
def test_migration_force_is_not_recomputed_after_reconciliation(tmp_path, monkeypatch):
    broker = _Broker(cash=90000, positions={"SNDK": 100})
    _midcycle_state(tmp_path, monkeypatch, broker)
    old = paper.load_state(tmp_path)
    old.policy_version = "previous-policy"
    paper.save_state(tmp_path, old)

    # Change the reconciled stamp to detect moving migration checks after this call.
    def reconcile(client, state, root, live):
        new = deepcopy(state)
        new.policy_version = live_policy.ACTIVE
        return new, []

    monkeypatch.setattr(market_daily, "_reconcile", reconcile)
    entry = market_daily.paper_trade(_report(), tmp_path, "2026-09-03", False)
    assert entry["plan"] == "rebalance"
    assert asdict(paper.load_state(tmp_path)) == asdict(old)


# Saved older policy labels cannot silently execute newer installed planner code.
@pytest.mark.parametrize(
    "field", ["schema", "allocation_policy", "execution_policy", "event_policy_version"]
)
def test_dispatch_refuses_unknown_versions_before_planning(field, monkeypatch):
    _, inputs = _inputs()
    inputs[field] = "different-version"

    # Reject unsupported policy evidence before any planner can run.
    def must_not_plan(*args, **kwargs):
        pytest.fail("Version mismatch must be rejected before entering a planner")

    monkeypatch.setattr(paper, "plan", must_not_plan)
    with pytest.raises(ValueError, match=field):
        nightly_plan.plan(inputs, paper.PaperState(), 100000, {}, 100000)


# A block from another decision or price date is not evidence for this record.
@pytest.mark.parametrize("field", ["session", "price_session"])
def test_record_does_not_attach_another_sessions_planner_block(field):
    report, inputs = _inputs()
    inputs[field] = "2026-09-01"
    result = market_daily.record(report, paper={"planner_inputs": inputs})
    assert result["planner_inputs"] is None
    assert result["targets"] == live_policy.record_targets(report)


# The real record writer/readback preserves numeric precision and tied-order inputs.
def test_saved_record_round_trip_preserves_ordered_planner_outputs(tmp_path):
    report = _stretch_report(
        {"ZZZ": 100.0, "AAA": 100.0, "MMM": 100.0},
        {"ZZZ": "A", "AAA": "A", "MMM": "A"},
    )
    session = str(report.panel.dates[-1])
    base = nightly_plan.build(report, session)
    _, flags = market_daily._band_blocked(report)
    inputs = nightly_plan.complete(
        base,
        {"calendar_known": True, "factor": 1.0, "decision_date": "2026-09-16"},
        flags,
        entries=market_daily._price_entries(report),
        downgrades=market_daily._downgraded(report, dict.fromkeys(base["grades"], 1)),
    )
    state = paper.PaperState()
    before = nightly_plan.plan(inputs, state, 100000, {}, 30000)
    record = market_daily.record(report, paper={"planner_inputs": inputs})
    path = market_daily.save(tmp_path, record)
    recovered = json.loads(path.read_text())["planner_inputs"]
    assert recovered == inputs
    for key in (
        "prices",
        "targets",
        "grades",
        "blocking_flags",
        "entries",
        "downgrades",
    ):
        assert list(recovered[key]) == list(inputs[key])
    after = nightly_plan.plan(recovered, state, 100000, {}, 30000)
    assert after == before
    assert len(before[0]) == 3
    assert len({order.qty for order in before[0]}) == 1
    assert state == paper.PaperState()
