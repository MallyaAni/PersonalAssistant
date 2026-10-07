"""Pin the extracted nightly dispatch against real paper and event planners."""

from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from backend.agents.trading.desk import (
    event_execution,
    event_risk,
    intraday_orders,
    live_policy,
    nightly_plan,
    paper,
    policy_v4,
)


# Supply ordinary planning inputs without a broker, provider or policy force inference.
def inputs(state=None, **changes):
    args = dict(
        session="2026-09-14",
        state=state or paper.PaperState(policy_version=live_policy.ACTIVE),
        equity=10000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={"AAA": 0.2, "BBB": 0.2},
        grades={"AAA": "A", "BBB": "A+"},
        event_policy={
            "calendar_known": True,
            "factor": 1.0,
            "decision_date": "2026-09-16",
        },
        finished={},
        entry_blocked=set(),
        entries={},
        cash=1000.0,
    )
    args.update(changes)
    return args


# Derive the pre-extraction ordinary result from the actual paper planner boundary.
def ordinary_reference(args):
    orders, new, what = paper.plan(
        args["session"],
        paper.PaperState(**asdict(args["state"])),
        args["equity"],
        args["held"],
        args["prices"],
        args["targets"],
        args["grades"],
        finished=args["finished"],
        entry_blocked=args["entry_blocked"],
        entries=args["entries"],
        cash=args["cash"],
        force_rebalance=args.get("force_rebalance", False),
    )
    if intraday_orders.INTRADAY_EXECUTION:
        orders = [
            replace(o, execution_timing=intraday_orders.INTRADAY_TIMING)
            if not o.event_id and not o.priority
            else o
            for o in orders
        ]
    if (
        not live_policy.needs_rebalance(args["state"].policy_version)
        or what == "rebalance"
    ):
        new.policy_version = live_policy.ACTIVE
    return orders, new, what


# Keep actual ordinary plan payloads identical under reset, rotation and cash paths.
@pytest.mark.parametrize(
    "scenario", ["reset", "downgrade", "deferred", "redeploy", "blocked", "drift"]
)
def test_ordinary_dispatch_matches_original_planner(scenario):
    state = paper.PaperState(
        last_rebalance="2026-09-10",
        sessions_since_rebalance=2,
        policy_version=live_policy.ACTIVE,
        rebalance_targets={"AAA": 0.2, "BBB": 0.2},
    )
    args = inputs(state)
    if scenario == "reset":
        args.update(force_rebalance=True, held={"AAA": 100.0}, targets={"BBB": 0.2})
    elif scenario == "downgrade":
        args.update(
            held={"AAA": 10.0, "BBB": 10.0},
            cash=0.0,
            equity=20000.0,
            finished={"AAA": "graded B; rotate"},
            grades={"AAA": "B", "BBB": "A"},
        )
    elif scenario == "deferred":
        state.deferred_buys = {"BBB": 8.0}
    elif scenario == "redeploy":
        args.update(held={"AAA": 10.0}, cash=3000.0, targets={"AAA": 0.2})
    elif scenario == "blocked":
        args.update(force_rebalance=True, entry_blocked={"AAA"}, held={"AAA": 40.0})
    else:
        args.update(held={"AAA": 25.0}, targets={"AAA": 0.2}, cash=0.0)
    before = deepcopy(args)
    expected = ordinary_reference(args)
    actual = nightly_plan.plan(**args)
    assert actual[0] == expected[0]
    assert asdict(actual[1]) == asdict(expected[1])
    assert actual[2] == expected[2]
    assert asdict(args["state"]) == asdict(before["state"])
    assert {k: v for k, v in args.items() if k != "state"} == {
        k: v for k, v in before.items() if k != "state"
    }
    check_ordinary_outcomes(scenario, args, actual)


# Assert real quantities and funding consequences rather than only planner equality.
def check_ordinary_outcomes(scenario, args, actual):
    if scenario == "reset":
        assert (
            sum(o.qty * args["prices"][o.symbol] for o in actual[0] if o.side == "buy")
            <= args["cash"]
        )
        assert any(o.side == "sell" and o.qty == 100 for o in actual[0])
        assert actual[1].deferred_buys["BBB"] > 0
    elif scenario == "downgrade":
        assert [(o.symbol, o.side, o.qty) for o in actual[0]] == [("AAA", "sell", 10)]
        assert actual[1].deferred_buys["BBB"] > 0
    elif scenario == "deferred":
        assert [(o.symbol, o.qty) for o in actual[0]] == [("BBB", 8)]
        assert actual[2] == "deferred buys"
        assert not actual[1].deferred_buys
    elif scenario == "redeploy":
        assert [(o.symbol, o.qty, o.kind) for o in actual[0]] == [
            ("AAA", 10, paper.REDEPLOY_KIND)
        ]
    elif scenario == "blocked":
        assert any(o.symbol == "AAA" and o.side == "sell" for o in actual[0])
        assert not any(o.symbol == "AAA" and o.side == "buy" for o in actual[0])
    else:
        assert not actual[0]


# The extraction must not infer policy migration force which belongs before reconcile.
def test_force_is_explicit_and_old_stamp_waits_for_a_real_reset():
    state = paper.PaperState(
        last_rebalance="2026-09-10",
        sessions_since_rebalance=2,
        policy_version="old-policy",
        rebalance_targets={},
    )
    args = inputs(state, cash=0.0)
    orders, new, what = nightly_plan.plan(**args)
    assert not orders
    assert what == "hold"
    assert new.policy_version == "old-policy"
    assert new.last_rebalance == state.last_rebalance
    orders, new, what = nightly_plan.plan(**args, force_rebalance=True)
    assert not orders
    assert what == "rebalance"
    assert new.policy_version == live_policy.ACTIVE
    assert new.last_rebalance == args["session"]
    assert state.policy_version == "old-policy"


# Real breakout sizing remains grade screened, cash funded and blocked where declared.
@pytest.mark.parametrize(
    ("grade", "blocked", "quantity"), [("A", False, 2), ("B", False, 0), ("A", True, 0)]
)
def test_price_entry_preserves_actual_band_and_grade_rules(grade, blocked, quantity):
    state = paper.PaperState(
        last_rebalance="2026-09-10",
        policy_version=live_policy.ACTIVE,
        rebalance_targets={},
    )
    args = inputs(
        state,
        targets={},
        grades={"AAA": grade},
        entries={"AAA": paper.ENTRY_SIZE_REF},
        entry_blocked={"AAA"} if blocked else set(),
    )
    orders, _, what = nightly_plan.plan(**args)
    assert (
        sum(o.qty for o in orders if o.symbol == "AAA" and o.side == "buy") == quantity
    )
    assert all(o.execution_timing == intraday_orders.INTRADAY_TIMING for o in orders)
    assert what == ("entries" if quantity else "hold")


# A duplicate-session family stamp changes only the returned snapshot, not caller state.
def test_duplicate_session_does_not_mutate_input_when_re_stamping():
    state = paper.PaperState(
        sessions_seen=["2026-09-14"], policy_version=policy_v4.POLICY_VERSION
    )
    before = asdict(state)
    orders, new, what = nightly_plan.plan(**inputs(state))
    assert not orders
    assert what == "already planned for this session"
    assert new is not state
    assert new.policy_version == live_policy.ACTIVE
    assert asdict(state) == before


# Forced replacements consume the planner's sequence while identical inputs repeat IDs.
def test_deterministic_ids_and_forced_replacement_sequence():
    args = inputs(cash=10000.0)
    first = nightly_plan.plan(**args)
    again = nightly_plan.plan(**args)
    assert [o.client_order_id for o in first[0]] == [
        o.client_order_id for o in again[0]
    ]
    forced = nightly_plan.plan(**{**args, "state": first[1]}, force_rebalance=True)
    assert not {o.client_order_id for o in first[0]} & {
        o.client_order_id for o in forced[0]
    }
    assert args["state"].order_seq == 0
    assert all(isinstance(o.qty, int) and o.qty > 0 for o in first[0])


# Broker settlement gates every ordinary plan even when a force was already declared.
def test_pending_orders_use_real_event_gate_without_overwriting_intent():
    state = paper.PaperState(
        last_rebalance="2026-09-10",
        policy_version=None,
        pending=[{"symbol": "AAA", "client_order_id": "working"}],
    )
    before = asdict(state)
    orders, new, what = nightly_plan.plan(**inputs(state), force_rebalance=True)
    assert not orders
    assert what == "FOMC waiting for broker settlement"
    assert new.pending == state.pending
    assert new.last_rebalance == state.last_rebalance
    assert new.policy_version is None
    assert asdict(state) == before


# Unknown event calendars fail closed while advancing the original session clock once.
def test_unknown_calendar_pauses_exposure_and_preserves_old_stamp():
    state = paper.PaperState(
        last_rebalance="2026-09-10", policy_version=None, sessions_since_rebalance=3
    )
    args = inputs(state, event_policy={"calendar_known": False})
    orders, new, what = nightly_plan.plan(**args, force_rebalance=True)
    assert not orders
    assert "calendar unavailable" in what
    assert new.sessions_since_rebalance == 4
    assert new.last_rebalance == state.last_rebalance
    assert new.policy_version is None
    assert state.sessions_since_rebalance == 3
    repeated = nightly_plan.plan(**{**args, "state": new})
    assert repeated[1].sessions_since_rebalance == 4


# Reduced exposure invokes the real FOMC planner and never tags event orders intraday.
def test_fomc_reduction_matches_original_event_plan():
    state = paper.PaperState(last_rebalance="2026-09-10", policy_version=None)
    args = inputs(
        state,
        held={"AAA": 100.0},
        cash=0.0,
        event_policy={
            "calendar_known": True,
            "factor": event_risk.REDUCED,
            "decision_date": "2026-09-16",
        },
    )
    expected = event_execution.plan(
        args["session"],
        state,
        args["held"],
        args["prices"],
        args["cash"],
        args["event_policy"],
    )
    actual = nightly_plan.plan(**args, force_rebalance=True)
    assert actual[0] == expected[0]
    assert asdict(actual[1]) == asdict(expected[1])
    assert actual[2] == "FOMC reduction"
    assert [(o.side, o.qty) for o in actual[0]] == [("sell", 50)]
    assert all(o.event_id and o.execution_timing is None for o in actual[0])
    assert actual[1].policy_version is None
    assert not state.event_cycle


# Restore only confirmed reduction fills under the event's cash and baseline limits.
def test_fomc_restoration_preserves_original_share_and_cash_bounds():
    state = paper.PaperState(
        policy_version=live_policy.ACTIVE,
        event_cycle={
            "id": "cycle",
            "decision_date": "2026-09-16",
            "baseline": {"AAA": 100.0},
        },
        journal=[
            {"event_id": "cycle", "symbol": "AAA", "side": "sell", "filled_qty": 50}
        ],
    )
    args = inputs(state, session="2026-09-16", held={"AAA": 50.0}, cash=1000.0)
    orders, new, what = nightly_plan.plan(**args)
    assert what == "FOMC restoration"
    assert [(o.side, o.qty) for o in orders] == [("buy", 9)]
    assert orders[0].event_id == "cycle"
    assert orders[0].execution_timing is None
    assert new.event_cycle == state.event_cycle
    assert new.policy_version == live_policy.ACTIVE
    state.journal.append(
        {"event_id": "cycle", "symbol": "AAA", "side": "buy", "filled_qty": 50}
    )
    orders, new, what = nightly_plan.plan(**{**args, "held": {"AAA": 100.0}})
    assert not orders
    assert what == "FOMC restoration complete"
    assert not new.event_cycle
    assert state.event_cycle


# The execution switch affects only ordinary timing and leaves priorities unchanged.
@pytest.mark.parametrize("enabled", [False, True])
def test_board_clock_preserves_event_and_priority_orders(enabled, monkeypatch):
    monkeypatch.setattr(intraday_orders, "INTRADAY_EXECUTION", enabled)
    orders = [
        paper.PaperOrder("AAA", "buy", 1, "normal"),
        paper.PaperOrder("BBB", "sell", 1, "event", event_id="cycle"),
        paper.PaperOrder(
            "CCC", "sell", 1, "priority", priority="risk", execution_timing="next_open"
        ),
    ]
    tagged = nightly_plan.on_the_boards_clock(orders)
    assert tagged[0].execution_timing == (
        intraday_orders.INTRADAY_TIMING if enabled else None
    )
    assert tagged[1:] == orders[1:]
    assert orders[0].execution_timing is None
    result = nightly_plan.plan(**inputs(cash=10000.0))
    assert all(
        o.execution_timing == (intraday_orders.INTRADAY_TIMING if enabled else None)
        for o in result[0]
    )
