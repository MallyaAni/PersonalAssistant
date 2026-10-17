"""Pure nightly inference audits reject model, target and whole-share action drift."""

from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import paper
from backend.market import (
    direct_daily_arithmetic,
    learned_retention_models,
    live_policy_replay,
)
from backend.market import live_model_history_nightly_model as audit
from backend.market.grade_led_policy import POLICY
from backend.market.live_model_history import FrozenCurrentGradePolicy
from backend.market.panel import Panel
from backend.tests.test_joint_funded_policy import report


# Construct a fixed declared numeric head and real causal features without fitting.
def feature_fixture():
    dates = np.busday_offset("2020-01-02", np.arange(400)).astype("datetime64[D]")
    names = ("AAA", "BBB", "SPY", "QQQ")
    rows = np.arange(len(dates))[:, None]
    prices = 100 * np.exp(rows * np.array([0.001, 0.0002, 0.0004, 0.0003]))
    panel = Panel(
        dates,
        names,
        prices,
        prices * 1.01,
        prices * 0.99,
        prices,
        prices,
        np.ones_like(prices),
        {},
        "SPY",
    )
    raw = SimpleNamespace(
        grades=np.full(prices.shape, 3, dtype=np.int16),
        eligible=np.ones(prices.shape, dtype=bool),
    )
    values = learned_retention_models.completed_features(
        panel, raw.grades, raw.eligible, panel.dates, {"synthetic": True}
    )
    head = direct_daily_arithmetic.NumericHead(
        np.arange(13, dtype=np.int64), np.array([[0.01]]), ()
    )
    forecasts, _ = direct_daily_arithmetic.predict(
        head, values["X"], values["risk_valid"]
    )
    reader = SimpleNamespace(_parent=SimpleNamespace(_head=head))

    # Select independently cached synthetic rows without loading any original account.
    def select(day):
        reader.current = SimpleNamespace(
            features=values["X"][day].copy(),
            support=values["risk_valid"][day].copy(),
            prices=values["prices"][day].copy(),
            forecasts=forecasts[day].copy(),
        )

    reader.select = select
    return panel, raw, reader


# Score every declared prefix rather than trusting a current full-grid row alone.
def test_every_selected_prefix_uses_real_features_and_fixed_numeric_head():
    panel, raw, reader = feature_fixture()
    for day in (260, 299, 350, 399):
        value = audit.prefix_model(panel, raw, reader, day)
        assert value["session"] == str(panel.dates[day])
        assert all(len(value[key]) == 64 for key in value if key != "session")
    raw.grades[-1] = 0
    assert audit.prefix_model(panel, raw, reader, 260)["session"] == str(
        panel.dates[260]
    )


# A corrupted cached row or head output cannot borrow successful prefix evidence.
@pytest.mark.parametrize("field", ["features", "support", "prices", "forecasts"])
def test_prefix_audit_refuses_each_inference_boundary(field):
    panel, raw, reader = feature_fixture()
    original = reader.select

    # Inject one synthetic corruption after the normal selected row is constructed.
    def corrupt(day):
        original(day)
        target = getattr(reader.current, field)
        target.flat[0] = (
            not target.flat[0] if field == "support" else target.flat[0] + 1
        )

    reader.select = corrupt
    with pytest.raises(ValueError, match="differs"):
        audit.prefix_model(panel, raw, reader, 300)


# Declare original independent economic collections without filling missing claims.
def records():
    return dict.fromkeys(
        (
            "security_distributions",
            "share_consolidations",
            "security_exchanges",
            "cash_mergers",
        ),
        [],
    )


# Unpaid receivables add equity while spendable cash remains the original ledger cash.
def test_independent_account_keeps_unspendable_claims_and_missing_states():
    claims = records()
    claims["cash_mergers"] = [{"amount": 50, "paid": False}]
    account = audit.account(
        9000,
        {"AAA": 10},
        {"AAA": 100},
        [{"amount": 5, "paid": False}],
        claims,
        {"AAA": 100},
    )
    assert account["cash"] == 9000
    assert account["equity"] == 10055
    assert account["positions"][0]["market_value"] == 1000
    assert (
        audit.account(9000, {"AAA": 10}, {"AAA": 100}, [], records(), {})["problem"]
        == "missing_held_close"
    )
    claims["security_distributions"] = [{"fractional_qty": 0.5, "cash_in_lieu": None}]
    assert (
        audit.account(9000, {}, {}, [], claims, {})["problem"]
        == "unknown_distribution_cash_in_lieu"
    )


# Missing economic kinds and invalid basis cannot become a plausible model account.
@pytest.mark.parametrize(
    "change",
    ["missing", "extra", "basis_missing", "basis_extra", "nan", "negative", "bool"],
)
def test_independent_account_requires_complete_evidence(change):
    claims, basis = records(), {"AAA": 100}
    if change == "missing":
        del claims["cash_mergers"]
    elif change == "extra":
        claims["invented"] = []
    elif change == "basis_missing":
        basis = {}
    elif change == "basis_extra":
        basis["BBB"] = 100
    else:
        basis["AAA"] = {"nan": float("nan"), "negative": -1, "bool": True}[change]
    original = deepcopy((claims, basis))
    with pytest.raises(ValueError, match="required"):
        audit.account(9000, {"AAA": 10}, basis, [], claims, {"AAA": 100})
    assert repr((claims, basis)) == repr(original)


# Unknown and zero original basis remain explicit and cannot mutate ledger evidence.
@pytest.mark.parametrize("basis_value", [None, 0])
def test_independent_account_preserves_unknown_and_zero_basis(basis_value):
    claims, basis, held = records(), {"AAA": basis_value}, {"AAA": 10}
    original = deepcopy((claims, basis, held))
    value = audit.account(9000, held, basis, [], claims, {"AAA": 100})
    assert value["equity"] == 10000
    assert value["positions"][0]["unrealized_pl"] == (
        None if basis_value is None else 1000
    )
    assert (claims, basis, held) == original


# Persistence turns numeric-text symbols into JSON text while preserving integer shares.
def test_comparison_serialization_matches_actual_json_representation():
    value = audit.serialized(
        {"symbol": np.str_("AAA"), "qty": np.int64(1), "cash": 100000.0}
    )
    assert type(value["symbol"]) is str
    assert type(value["qty"]) is int
    assert type(value["cash"]) is float
    audit.exact_integers(value, {"symbol": "AAA", "qty": 1, "cash": 100000.0}, "saved")


# Economic split quantities reach the real planner unchanged, including fractions.
@pytest.mark.parametrize("quantity", [20.0, 2.5])
def test_split_quantity_is_not_rounded_or_refused_before_policy_dispatch(quantity):
    policy, shown = analytic_policy()
    day = str(shown.panel.dates[-1])
    held, basis = {"AAA": quantity}, {"AAA": 50}
    observed = audit.account(9000, held, basis, [], records(), {"AAA": 100})
    assert type(observed["held"]["AAA"]) is float
    assert observed["held"]["AAA"] == quantity
    state, pending, _, mode = audit.pure_plan(
        shown,
        policy,
        paper.PaperState(),
        observed,
        day,
        day + "T16:01:00-04:00",
        [],
        {},
    )
    assert mode["model_required"]
    assert not pending
    reason = state.allocation_state["receipt"]["reason"]
    assert (reason == "whole_share_holdings_unavailable") == (quantity % 1 != 0)
    assert held == {"AAA": quantity}
    assert basis == {"AAA": 50}


# Bind known analytic joint scenarios to the exact grade-led planner without a broker.
def analytic_policy(grades=(3, 2), *, values=None):
    dates = np.busday_offset("2020-01-02", np.arange(400)).astype("datetime64[D]")
    reader = SimpleNamespace(dates=dates, symbols=("AAA", "BBB", "SPY", "QQQ"))

    # Supply declared negative returns to isolate grade preservation from zero sizing.
    def distribution(day, symbols):
        scenarios = (
            np.array([values[name] for name in symbols]).T
            if values
            else np.full((2, len(symbols)), -0.02)
        )
        return SimpleNamespace(
            scenarios=scenarios,
            probabilities=np.array([0.5, 0.5]),
            receipt={"status": "available", "synthetic": True},
        )

    reader.distribution = distribution
    policy = FrozenCurrentGradePolicy.__new__(FrozenCurrentGradePolicy)
    policy.reader, policy.cost_bps = reader, 10
    policy.identity = {"policy": POLICY, "cost_bps": 10, "synthetic": True}
    return policy, report(reader, grades=grades)


# The actual numeric optimizer's zero proposal cannot liquidate an eligible holding.
def test_pure_plan_recomputes_raw_zero_and_grade_constrained_hold():
    policy, shown = analytic_policy()
    day = str(shown.panel.dates[-1])
    observed = audit.account(
        9000, {"AAA": 10}, {"AAA": 100}, [], records(), {"AAA": 100}
    )
    state, intents, entry, mode = audit.pure_plan(
        shown,
        policy,
        paper.PaperState(),
        observed,
        day,
        day + "T16:01:00-04:00",
        [],
        {},
    )
    assert mode["model_required"]
    receipt = state.allocation_state["receipt"]
    assert receipt["sizing_model_targets"]["AAA"] == 0
    assert receipt["targets"]["AAA"] == 0.1
    assert not intents
    actual = next(row for row in entry["actions"] if row["ticker"] == "AAA")
    assert actual["order_quantity"] == 0
    assert actual["action"] == "hold"


# Reject saved raw, constrained, action and control corruption from fresh inference.
@pytest.mark.parametrize(
    "change",
    [
        None,
        "raw",
        "constrained",
        "action",
        "order_seq",
        "clock",
        "action_float",
        "action_fraction",
        "count_float",
        "count_fraction",
    ],
)
def test_compare_saved_uses_recomputed_outputs_not_saved_model_targets(change):
    policy, shown = analytic_policy()
    day = str(shown.panel.dates[-1])
    previous = paper.PaperState()
    observed = audit.account(
        9000, {"AAA": 10}, {"AAA": 100}, [], records(), {"AAA": 100}
    )
    state, pending, entry, _ = audit.pure_plan(
        shown, policy, previous, observed, day, day + "T16:01:00-04:00", [], {}
    )
    expected_entry = live_policy_replay.plain(
        {
            **entry,
            "written": "2026-10-17T13:00:00+00:00",
            "pl": 0,
            "pl_pct": 0,
            "settled": [],
        }
    )
    recorded_state = deepcopy(state)
    recorded_state.start_equity = observed["equity"]
    recorded_state.history = [expected_entry]
    value = {
        "nightly": {
            "session": day,
            "at": day + "T16:01:00-04:00",
            "status": "planned",
            "persisted_policy": POLICY,
            "entry": deepcopy(expected_entry),
        },
        "new_intents": deepcopy(pending),
        "paper_state": live_policy_replay.plain(asdict(recorded_state)),
    }
    if change == "raw":
        value["nightly"]["entry"]["joint_funded"]["receipt"]["sizing_model_targets"][
            "AAA"
        ] = 0.9
    elif change == "constrained":
        value["nightly"]["entry"]["joint_funded"]["targets"]["AAA"] = 0.8
    elif change == "action":
        value["nightly"]["entry"]["actions"][0]["order_quantity"] = 999
    elif change == "order_seq":
        value["paper_state"]["order_seq"] = 999
    elif change == "clock":
        value["nightly"]["entry"]["written"] = "2019-01-01T00:00:00Z"
    elif change in ("action_float", "action_fraction"):
        key = value["nightly"]["entry"]["actions"][0]
        key["order_quantity"] = float(key["order_quantity"]) + (
            1e-8 if change.endswith("fraction") else 0
        )
    elif change in ("count_float", "count_fraction"):
        key = value["paper_state"]
        key["order_seq"] = float(key["order_seq"]) + (
            1e-8 if change.endswith("fraction") else 0
        )
    args = dict(
        report=shown,
        started="2026-10-17T12:00:00+00:00",
        verified_at=datetime(2026, 10, 17, 14, tzinfo=UTC),
    )
    if change is None:
        audit.compare_saved(value, previous, state, pending, entry, [], **args)
    else:
        with pytest.raises(ValueError, match="differs|required"):
            audit.compare_saved(value, previous, state, pending, entry, [], **args)


# An eligible trim keeps grade permission while recomputing its original funded shares.
def test_eligible_trim_keeps_the_shared_whole_share_quantity_and_timing():
    policy, shown = analytic_policy(values={"AAA": [0.02, 0.03], "BBB": [-0.02, -0.03]})
    day = str(shown.panel.dates[-1])
    observed = audit.account(
        5000, {"AAA": 50}, {"AAA": 100}, [], records(), {"AAA": 100}
    )
    state, pending, entry, _ = audit.pure_plan(
        shown,
        policy,
        paper.PaperState(),
        observed,
        day,
        day + "T16:01:00-04:00",
        [],
        {},
    )
    assert state.allocation_state["receipt"]["sizing_model_targets"]["AAA"] == 0.25
    assert [(row["symbol"], row["side"], row["qty"]) for row in pending] == [
        ("AAA", "sell", 25)
    ]
    assert pending[0]["execution_timing"] == "dip_or_close"
    row = next(row for row in entry["actions"] if row["ticker"] == "AAA")
    assert row["action"] == "trim"
    assert row["order_quantity"] == 25
    assert row["grade_signal"] == "hold"


# Below-A liquidation requires the original next-open request and acknowledgment.
def test_grade_exit_requires_the_original_immediate_request_and_id():
    policy, shown = analytic_policy(grades=(1, 3))
    day = str(shown.panel.dates[-1])
    at = day + "T16:01:00-04:00"
    cid = paper.order_id(day, "AAA", "sell", 0)
    request = {
        "client_order_id": cid,
        "symbol": "AAA",
        "side": "sell",
        "qty": 10,
        "at": datetime.fromisoformat(at).astimezone(UTC).isoformat(),
        "accepted": True,
        "reason": None,
        "observed_price": 100,
        "available_cash": 9000,
    }
    observed = audit.account(
        9000, {"AAA": 10}, {"AAA": 100}, [], records(), {"AAA": 100}
    )
    _, pending, entry, _ = audit.pure_plan(
        shown, policy, paper.PaperState(), observed, day, at, [request], {cid: request}
    )
    assert pending[0]["client_order_id"] == cid
    assert pending[0]["qty"] == 10
    assert pending[0]["execution_timing"] == "next_open"
    assert pending[0]["execution"]["created_at"] == request["at"]
    assert entry["orders"][0]["qty"] == 10
    with pytest.raises(ValueError, match="immediate nightly attempt"):
        audit.pure_plan(shown, policy, paper.PaperState(), observed, day, at, [], {})


# An event-only saved night must not claim a model proposal when dispatch skipped it.
def test_event_branch_builds_actual_actions_without_invoking_the_model(monkeypatch):
    policy, shown = analytic_policy()
    day = str(shown.panel.dates[-1])

    # Unknown event calendar blocks the model rather than falling back to saved sizes.
    def event(panel):
        return {"calendar_known": False, "factor": None}

    # Any model call would be a false inference count for the event branch.
    def forbidden(*args):
        raise AssertionError("Event dispatch must not invoke the model")

    monkeypatch.setattr(audit.event_risk, "decision", event)
    monkeypatch.setattr(policy, "plan", forbidden)
    observed = audit.account(
        9000, {"AAA": 10}, {"AAA": 100}, [], records(), {"AAA": 100}
    )
    _, pending, entry, mode = audit.pure_plan(
        shown,
        policy,
        paper.PaperState(),
        observed,
        day,
        day + "T16:01:00-04:00",
        [],
        {},
    )
    assert not pending
    assert not mode["model_required"]
    assert entry["joint_funded"]["status"] == "event_priority"
    assert all(
        row["decision_source"] == "settlement_or_event_priority"
        for row in entry["actions"]
    )


# Each incomplete fractional entitlement blocks NAV before any numeric model call.
@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("security_distributions", "unknown_distribution_cash_in_lieu"),
        ("share_consolidations", "unknown_consolidation_cash_in_lieu"),
        ("security_exchanges", "unknown_exchange_cash_in_lieu"),
    ],
)
def test_all_fractional_entitlement_missing_states_are_explicit(kind, reason):
    claims = records()
    claims[kind] = [{"fractional_qty": 0.5, "cash_in_lieu": None}]
    observed = audit.account(10000, {}, {}, [], claims, {})
    assert observed == {"problem": reason}
    mode = audit.controls.branch(
        paper.PaperState(), {}, "2021-07-14", account_problem=reason
    )
    assert not mode["model_required"]
    assert mode["path"] == "nightly_broker_unavailable"


# Real event reduction and restoration quantities bypass numerical sizing entirely.
@pytest.mark.parametrize("restore", [False, True])
def test_nonempty_event_reduction_and_restoration_do_not_invoke_model(
    monkeypatch, restore
):
    policy, shown = analytic_policy()
    day = str(shown.panel.dates[-1])
    event_day = day if restore else "2099-01-01"
    event_id = "fomc-3-session-weakness/2:" + event_day
    before = paper.PaperState()
    if restore:
        before.event_cycle = {
            "id": event_id,
            "decision_date": event_day,
            "baseline": {"AAA": 10.0},
        }
        before.journal = [
            {
                "client_order_id": "original-sale",
                "symbol": "AAA",
                "event_id": event_id,
                "side": "sell",
                "filled_qty": 5,
            }
        ]

    # Supply a declared event decision while leaving the real event planner intact.
    def event(panel):
        return {
            "calendar_known": True,
            "factor": 1 if restore else 0.5,
            "decision_date": event_day,
        }

    # Event dispatch cannot count or call an ordinary numeric plan.
    def forbidden(*args):
        raise AssertionError("Numeric plan unexpectedly invoked")

    monkeypatch.setattr(audit.event_risk, "decision", event)
    monkeypatch.setattr(policy, "plan", forbidden)
    side, quantity = ("buy", 5) if restore else ("sell", 5)
    at = day + "T16:01:00-04:00"
    cid = paper.order_id(day, "AAA", side, 0)
    request = {
        "client_order_id": cid,
        "symbol": "AAA",
        "side": side,
        "qty": quantity,
        "at": datetime.fromisoformat(at).astimezone(UTC).isoformat(),
        "accepted": True,
    }
    observed = audit.account(
        9000, {"AAA": 5 if restore else 10}, {"AAA": 100}, [], records(), {"AAA": 100}
    )
    state, pending, entry, mode = audit.pure_plan(
        shown, policy, before, observed, day, at, [request], {cid: request}
    )
    assert not mode["model_required"]
    assert mode["path"] == "event_priority"
    assert pending[0]["qty"] == quantity
    assert pending[0]["side"] == side
    assert entry["orders"][0]["qty"] == quantity
    assert pending[0]["event_id"] == event_id
    assert state.journal == before.journal


# Rejected immediate requests stay durable with their explicit original refusal.
def test_immediate_refusal_is_not_acknowledged_or_silently_removed():
    policy, shown = analytic_policy(grades=(1, 3))
    day = str(shown.panel.dates[-1])
    at = day + "T16:01:00-04:00"
    cid = paper.order_id(day, "AAA", "sell", 0)
    request = {
        "client_order_id": cid,
        "symbol": "AAA",
        "side": "sell",
        "qty": 10,
        "at": at,
        "accepted": False,
        "reason": "uncovered_sell",
    }
    observed = audit.account(
        9000, {"AAA": 10}, {"AAA": 100}, [], records(), {"AAA": 100}
    )
    state, pending, entry, mode = audit.pure_plan(
        shown, policy, paper.PaperState(), observed, day, at, [request], {}
    )
    assert mode["model_required"]
    assert state.pending == pending
    assert pending[0]["qty"] == 10
    assert "created_at" not in pending[0]["execution"]
    assert entry["orders"] == []
    assert entry["refused"] == ["sell AAA: uncovered_sell"]


# A previously planned session preserves prior allocation without evaluating a model.
def test_duplicate_session_does_not_claim_fresh_model_evaluation(monkeypatch):
    policy, shown = analytic_policy()
    day = str(shown.panel.dates[-1])
    observed = audit.account(10000, {}, {}, [], records(), {})
    before, _, _, _ = audit.pure_plan(
        shown,
        policy,
        paper.PaperState(),
        observed,
        day,
        day + "T16:01:00-04:00",
        [],
        {},
    )

    # Repeated dispatch must return before the numeric decision boundary.
    def forbidden(*args):
        raise AssertionError("Duplicate session evaluated numeric model")

    monkeypatch.setattr(policy, "decide", forbidden)
    state, pending, _, mode = audit.pure_plan(
        shown, policy, before, observed, day, day + "T16:01:00-04:00", [], {}
    )
    assert not mode["model_required"]
    assert mode["path"] == "already_planned"
    assert not pending
    assert state.allocation_state == before.allocation_state


# Positive joint scenarios reach funded whole-share buys without spending sale proceeds.
def test_pure_plan_recomputes_whole_share_buys_from_original_cash():
    policy, shown = analytic_policy(values={"AAA": [0.02, 0.03], "BBB": [0.01, 0.02]})
    day = str(shown.panel.dates[-1])
    observed = audit.account(10000, {}, {}, [], records(), {})
    _, pending, entry, _ = audit.pure_plan(
        shown,
        policy,
        paper.PaperState(),
        observed,
        day,
        day + "T16:01:00-04:00",
        [],
        {},
    )
    assert [(row["symbol"], row["side"], row["qty"]) for row in pending] == [
        ("AAA", "buy", 25),
        ("BBB", "buy", 25),
    ]
    assert sum(row["qty"] * 100 * 1.001 for row in pending) <= observed["cash"]
    assert all(row["order_quantity"] == 25 for row in entry["actions"])


# Later submission of a nightly CID and earlier intraday rows cannot alter its close.
def test_nightly_receipts_select_exact_close_without_mutating_cumulative_evidence():
    policy, shown = analytic_policy(values={"AAA": [0.02, 0.03], "BBB": [0.01, 0.02]})
    day = str(shown.panel.dates[-1])
    at = day + "T16:01:00-04:00"
    observed = audit.account(10000, {}, {}, [], records(), {})
    expected = audit.pure_plan(
        shown, policy, paper.PaperState(), observed, day, at, [], {}
    )
    cid = expected[1][0]["client_order_id"]
    later = {"client_order_id": cid, "at": day + "T16:02:00-04:00", "accepted": True}
    earlier = {"client_order_id": "earlier-intraday", "at": day + "T15:45:00-04:00"}
    accepted, attempts = {cid: later}, [earlier, later]
    original = deepcopy((accepted, attempts))
    actual = audit.pure_plan(
        shown, policy, paper.PaperState(), observed, day, at, attempts, accepted
    )
    assert actual == expected
    assert (accepted, attempts) == original
    with pytest.raises(ValueError, match="Unplanned same-close"):
        audit.pure_plan(
            shown,
            policy,
            paper.PaperState(),
            observed,
            day,
            at,
            [{"client_order_id": "unknown", "at": at}],
            {},
        )
    with pytest.raises(ValueError, match="timed intent was submitted"):
        audit.pure_plan(
            shown,
            policy,
            paper.PaperState(),
            observed,
            day,
            at,
            [{**later, "at": at}],
            {cid: {**later, "at": at}},
        )
