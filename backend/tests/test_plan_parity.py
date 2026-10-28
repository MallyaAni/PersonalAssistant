"""The nightly check of the paper plan against the account simulator's plan."""

import json
from datetime import date, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import event_execution, event_risk, paper
from backend.market import grade_led_leader_policy as leader
from backend.market import plan_parity, policy_book
from backend.market.labels import PlanParity, PlanParityKind, PlanPath
from backend.tests.test_grade_led_leader_policy import chosen, leader_report
from backend.tests.test_joint_funded_policy import reader as reader  # noqa: F401


@pytest.fixture(autouse=True)
def _no_fomc_window(monkeypatch):
    # The synthetic calendar must not fall inside a real FOMC reduction window
    # unless a test puts it there.
    monkeypatch.setattr(
        event_risk, "live_path", lambda panel: np.ones(len(panel.dates))
    )


def _positions(held, prices):
    return [
        {"symbol": n, "qty": float(q), "market_value": float(q) * prices[n]}
        for n, q in held.items()
        if q > 0
    ]


def _blocked(report):
    from backend.agents.trading.desk import exit as exit_analyst

    signal = exit_analyst.evidence(report.panel).signalled()[-1]
    return {n for j, n in enumerate(report.panel.tickers) if signal[j]}


# A record as the nightly writes it, from the live leader planner's own plan.
def _ordinary_record(reader, monkeypatch, grades, held, cash):  # noqa: F811
    report = leader_report(reader, grades, prior=grades)
    day = str(report.panel.dates[-1])[:10]
    prices = {
        n: float(report.panel.close[-1, j])
        for j, n in enumerate(report.panel.tickers)
    }
    equity = cash + sum(q * prices[n] for n, q in held.items())
    policy = chosen(reader, monkeypatch)
    orders, state, _ = policy.plan(
        day, paper.PaperState(), equity, held, prices, report, cash, _blocked(report)
    )
    record = {
        "session": day,
        "paper": {
            "session": day,
            "policy": leader.POLICY,
            "positions": _positions(held, prices),
            "orders": [
                {"symbol": o.symbol, "side": o.side, "qty": o.qty} for o in orders
            ],
            "joint_funded": state.allocation_state,
            "cash": cash,
            "equity": equity,
            "actions": [],
            "event_risk": {},
        },
    }
    return record, report


# The live leader plan and the simulator's planner agree on an ordinary night:
# the same target weights, and every post-plan weight inside the band the
# simulator's own rounding and minimum trade allow.
def test_the_live_leader_plan_matches_the_simulator(reader, monkeypatch):  # noqa: F811
    record, report = _ordinary_record(
        reader, monkeypatch, (3, 2, -1, 0, 0), {"AAA": 3, "BBB": 40}, 2000.0
    )
    result = plan_parity.compare(record, report)
    assert result["verdict"] == PlanParity.OK, result["mismatches"]
    assert result["path"] == PlanPath.ORDINARY
    assert result["names"]
    assert plan_parity.line(result).endswith("OK (ordinary path)")


# A changed order quantity is caught and named.
def test_a_changed_order_is_a_mismatch_naming_the_name(reader, monkeypatch):  # noqa: F811
    record, report = _ordinary_record(
        reader, monkeypatch, (3, 2, -1, 0, 0), {"AAA": 3, "BBB": 40}, 2000.0
    )
    orders = record["paper"]["orders"]
    assert orders
    orders[0]["qty"] += 25
    result = plan_parity.compare(record, report)
    assert result["verdict"] == PlanParity.MISMATCH
    kinds = {(m["kind"], m.get("ticker")) for m in result["mismatches"]}
    assert (PlanParityKind.HOLDING, orders[0]["symbol"]) in kinds
    assert "PLAN PARITY MISMATCH" in plan_parity.line(result)


# A sizing receipt that differs from the simulator's leader target is caught.
def test_a_changed_target_is_a_sizing_mismatch(reader, monkeypatch):  # noqa: F811
    record, report = _ordinary_record(
        reader, monkeypatch, (3, 2, -1, 0, 0), {"AAA": 3, "BBB": 40}, 2000.0
    )
    receipt = record["paper"]["joint_funded"]["receipt"]
    receipt["sizing_model_targets"]["AAA"] += 0.01
    result = plan_parity.compare(record, report)
    assert {
        (m["kind"], m.get("ticker")) for m in result["mismatches"]
    } >= {(PlanParityKind.SIZING, "AAA")}


# A grade the plan recorded that the report does not have is an input mismatch.
def test_a_recorded_grade_differing_from_the_report_is_named(reader, monkeypatch):  # noqa: F811
    record, report = _ordinary_record(
        reader, monkeypatch, (3, 2, -1, 0, 0), {"AAA": 3, "BBB": 40}, 2000.0
    )
    record["paper"]["joint_funded"]["receipt"]["grades"]["BBB"] = 0
    result = plan_parity.compare(record, report)
    assert (PlanParityKind.INPUTS, "BBB") in {
        (m["kind"], m.get("ticker")) for m in result["mismatches"]
    }


# A plan made by another rule is never compared as if it were the simulator's.
def test_another_policy_is_a_mismatch(reader, monkeypatch):  # noqa: F811
    record, report = _ordinary_record(
        reader, monkeypatch, (3, 2, -1, 0, 0), {"AAA": 3}, 2000.0
    )
    record["paper"]["policy"] = "grade-led-learned-sizing/1"
    result = plan_parity.compare(record, report)
    assert result["verdict"] == PlanParity.MISMATCH
    assert [m["kind"] for m in result["mismatches"]] == [PlanParityKind.POLICY]


# The FOMC cut the live event planner sends is the simulator's cycle cut,
# share for share; one share more is a mismatch.
def test_the_fomc_cut_matches_the_cycle_arithmetic(reader, monkeypatch):  # noqa: F811
    report = leader_report(reader, (3, 2, -1, 0, 0))
    day = str(report.panel.dates[-1])[:10]
    held = {"AAA": 11.0, "BBB": 5.0}
    prices = {"AAA": 100.0, "BBB": 50.0}
    decision = "2099-01-01"
    orders, state, what = event_execution.plan(
        day,
        paper.PaperState(),
        held,
        prices,
        100.0,
        {
            "factor": event_risk.REDUCED,
            "calendar_known": True,
            "decision_date": decision,
        },
    )
    assert what == "FOMC reduction"
    assert orders
    record = {
        "session": day,
        "paper": {
            "session": day,
            "policy": leader.POLICY,
            "positions": _positions(held, prices),
            "orders": [
                {"symbol": o.symbol, "side": o.side, "qty": o.qty} for o in orders
            ],
            "joint_funded": {"policy": leader.POLICY, "status": "event_priority"},
            "cash": 100.0,
            "equity": 1450.0,
            "actions": [],
            "event_risk": {"cycle": state.event_cycle},
        },
    }
    result = plan_parity.compare(record, report)
    assert result["verdict"] == PlanParity.OK, result["mismatches"]
    assert (result["path"], result["stage"]) == (PlanPath.EVENT, "cut")
    record["paper"]["orders"][0]["qty"] += 1
    bad = plan_parity.compare(record, report)
    assert bad["verdict"] == PlanParity.MISMATCH
    assert bad["mismatches"][0]["ticker"] == record["paper"]["orders"][0]["symbol"]


# On the eve of the decision with the cut done, the restoration held for the
# balancer (an action row, not a sent order) brings every name back to the
# snapshot; the simulator restores at the decision close too.
def test_the_eve_restoration_matches_the_snapshot(reader, monkeypatch):  # noqa: F811
    from backend.agents.trading.desk import intraday_orders

    report = leader_report(reader, (3, 2, -1, 0, 0))
    day = str(report.panel.dates[-1])[:10]
    following = intraday_orders.next_session(date.fromisoformat(day))
    if following is None:
        pytest.skip("the synthetic calendar is outside the reviewed sessions")
    base = {"AAA": 11.0, "BBB": 5.0}
    held = {"AAA": 6.0, "BBB": 3.0}
    record = {
        "session": day,
        "paper": {
            "session": day,
            "policy": leader.POLICY,
            "positions": _positions(held, {"AAA": 100.0, "BBB": 50.0}),
            "orders": [],
            "joint_funded": {"policy": leader.POLICY, "status": "event_priority"},
            "cash": 10000.0,
            "actions": [
                {"ticker": "AAA", "action": "add", "order_quantity": 5},
                {"ticker": "BBB", "action": "add", "order_quantity": 2},
            ],
            "event_risk": {
                "cycle": {"decision_date": following.isoformat(), "baseline": base}
            },
        },
    }
    result = plan_parity.compare(record, report)
    assert result["verdict"] == PlanParity.OK, result["mismatches"]
    assert result["stage"] == "restore"
    record["paper"]["actions"][1]["order_quantity"] = 1
    assert plan_parity.compare(record, report)["verdict"] == PlanParity.MISMATCH


# The verdict file keeps one row per session, and a check that cannot run is
# written as unavailable rather than lost.
def test_rows_are_written_per_session_and_failures_are_kept(
    tmp_path, reader, monkeypatch  # noqa: F811
):
    record, report = _ordinary_record(
        reader, monkeypatch, (3, 2, -1, 0, 0), {"AAA": 3, "BBB": 40}, 2000.0
    )
    first = plan_parity.run(tmp_path, report=report, record=record)
    assert first["verdict"] == PlanParity.OK
    again = plan_parity.run(tmp_path, report=report, record=record)
    rows = plan_parity.load(tmp_path)["rows"]
    assert [r["date"] for r in rows] == [record["session"]]
    assert plan_parity.for_session(tmp_path, record["session"])["checked_at"] == (
        again["checked_at"]
    )
    earlier = str(date.fromisoformat(record["session"]) - timedelta(days=1))
    moved = {**record, "session": earlier}
    failed = plan_parity.run(tmp_path, report=report, record=moved)
    assert failed["verdict"] == PlanParity.UNAVAILABLE
    assert f"not the record's {earlier}" in failed["note"]
    stored = json.loads(plan_parity.path(tmp_path).read_text())["rows"]
    assert [r["date"] for r in stored] == [earlier, record["session"]]


# The check plans through the simulator's own functions, not a copy of them.
def test_the_simulator_plans_through_the_shared_functions(monkeypatch):
    calls = []
    real = policy_book.plan_orders

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(policy_book, "plan_orders", spy)
    from backend.tests.test_policy_book import TICKERS, _run

    grades = np.full((160, len(TICKERS)), 2, dtype=int)
    grades[:, 3] = 0
    _run(grades)
    assert calls


# The command re-runs one session's check: no record is a check that could not
# run (exit 2); --no-write leaves the verdict file alone, and without it the
# dated failure is written so the board shows the check did not run.
def test_the_command_reports_a_missing_record(tmp_path, capsys):
    from backend.cli import market_plan_parity

    root = str(tmp_path)
    assert market_plan_parity.main(["--root", root, "--no-write"]) == 2
    assert "UNAVAILABLE" in capsys.readouterr().out
    assert not plan_parity.path(tmp_path).exists()
    assert market_plan_parity.main(["--root", root, "--date", "2026-10-21"]) == 2
    rows = plan_parity.load(tmp_path)["rows"]
    assert [(r["date"], r["verdict"]) for r in rows] == [("2026-10-21", "unavailable")]
