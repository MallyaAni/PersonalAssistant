"""Grade direction survives sizing, funding, missingness and whole-share boundaries."""

import json
from hashlib import sha256

from backend.agents.trading.desk import actions, paper
from backend.cli import market_daily
from backend.market import grade_led_policy as grade
from backend.market.joint_funded_policy import GradeLedFundedPolicy, JointFundedPolicy
from backend.tests.test_joint_funded_policy import analytic, report
from backend.tests.test_joint_funded_policy import reader as reader


# Install the new selector over original synthetic heads without refitting.
def install_grade_led(root, fixture, monkeypatch):
    from backend.market import learned_live_holding as runtime
    from backend.tests.test_learned_holding_transition import install_transition

    _, shown, now = install_transition(root, fixture, monkeypatch)
    config_path = root / runtime.CONFIG
    config = json.loads(config_path.read_bytes())
    release_path = config_path.with_name("release.json")
    release = json.loads(release_path.read_bytes())
    config["policy"] = release["policy"] = grade.POLICY
    raw = json.dumps(release).encode()
    release_path.write_bytes(raw)
    config["release_receipt_sha256"] = sha256(raw).hexdigest()
    config_path.write_text(json.dumps(config))
    return runtime.prepare(root, shown, clock=lambda: now), shown, now


# Use the real allocation and execution path with independent analytic return scenarios.
def chosen(monkeypatch, reader, values):
    original = analytic(monkeypatch, reader, values)
    policy = GradeLedFundedPolicy.__new__(GradeLedFundedPolicy)
    policy.reader = reader
    policy.cost_bps = original.cost_bps
    policy.identity = {**original.identity, "policy": grade.POLICY}
    return policy


# A profitable B holding exits under grades; the original policy stays intact.
def test_grade_downgrade_is_primary_exit(monkeypatch, reader):
    policy = chosen(monkeypatch, reader, {"AAA": [0.05, 0.06], "BBB": [0.02, 0.03]})
    shown = report(reader, grades=(1, 3))
    shown.graded.grades[-2, 0] = 3
    day = str(shown.panel.dates[-1])
    old, _ = JointFundedPolicy(reader, 10).decide(
        day, shown, 10000, {"AAA": 10}, {"AAA": 100, "BBB": 100}, 9000, set()
    )
    orders, state, _ = policy.plan(
        day,
        paper.PaperState(),
        10000,
        {"AAA": 10},
        {"AAA": 100, "BBB": 100},
        shown,
        9000,
        set(),
    )
    receipt = state.allocation_state["receipt"]
    assert old["AAA"] > 0
    assert receipt["targets"]["AAA"] == 0
    assert receipt["grade_signals"]["AAA"]["action"] == "sell"
    assert receipt["grade_signals"]["AAA"]["previous_grade"] == "A+"
    assert any(
        order.symbol == "AAA" and order.side == "sell" and order.qty == 10
        for order in orders
    )
    assert not any(order.symbol == "AAA" and order.side == "buy" for order in orders)


# A zero model size cannot erase a BUY signal or liquidate an A holding.
def test_zero_model_size_preserves_signal_and_eligible_holding(monkeypatch, reader):
    policy = chosen(monkeypatch, reader, {"AAA": [-0.05, -0.02], "BBB": [-0.02, -0.03]})
    shown = report(reader, grades=(3, 2))
    day = str(shown.panel.dates[-1])
    orders, state, _ = policy.plan(
        day,
        paper.PaperState(),
        10000,
        {"AAA": 10},
        {"AAA": 100, "BBB": 100},
        shown,
        9000,
        set(),
    )
    receipt = state.allocation_state["receipt"]
    assert receipt["targets"]["AAA"] == 0.1
    assert receipt["sizing_model_targets"]["AAA"] == 0
    assert receipt["grade_signals"]["BBB"]["action"] == "buy"
    assert receipt["targets"].get("BBB", 0) == 0
    assert not orders
    rows = actions.build(shown, receipt["targets"], {"AAA": actions.Holding(0.1)}, 0)
    actual = market_daily._holding_actions(
        policy,
        rows,
        orders,
        {"AAA": actions.Holding(0.1)},
        {"AAA": 10},
        {"AAA": 100, "BBB": 100},
        10000,
        None,
        receipt,
    )
    blocked = next(row for row in actual if row["ticker"] == "BBB")
    assert blocked["grade_signal"] == "buy"
    assert blocked["signal_status"] == "blocked"
    assert blocked["signal_reason"] == "Learned size is zero"
    assert blocked["order_quantity"] == 0
    assert blocked["is_fill"] is False


# A tiny positive target leaves one whole share rather than becoming a full exit.
def test_rounding_does_not_override_grade_exit_rule():
    receipt = {"current_weights": {"AAA": 0.1}}
    readings = {"AAA": {"action": "hold"}, "BBB": {"action": "buy"}}
    targets, receipt = grade.preserve_grade_holdings(
        {"AAA": 0.00001, "BBB": 0.2}, receipt, readings, {"AAA": 100, "BBB": 100}, 10000
    )
    assert targets["AAA"] == 0.01
    assert targets["BBB"] == 0.2


# Missing grades do not become an exit, and a blocked buy never creates a sized order.
def test_missing_grade_and_buy_guard(monkeypatch, reader):
    policy = chosen(monkeypatch, reader, {"AAA": [0.05, 0.06], "BBB": [0.02, 0.03]})
    shown = report(reader, grades=(-1, 3))
    day = str(shown.panel.dates[-1])
    orders, state, _ = policy.plan(
        day,
        paper.PaperState(),
        10000,
        {"AAA": 10},
        {"AAA": 100, "BBB": 100},
        shown,
        9000,
        {"BBB"},
    )
    receipt = state.allocation_state["receipt"]
    assert receipt["targets"]["AAA"] == 0.1
    assert receipt["grade_signals"]["AAA"]["action"] == "unavailable"
    assert receipt["grade_signals"]["BBB"]["action"] == "buy"
    assert not orders


# Invalid equity refuses every order while preserving the visible signal evidence.
def test_account_guard_still_refuses_orders(monkeypatch, reader):
    policy = chosen(monkeypatch, reader, {"AAA": [0.05, 0.06], "BBB": [0.02, 0.03]})
    shown = report(reader, grades=(3, 3))
    orders, state, _ = policy.plan(
        str(shown.panel.dates[-1]),
        paper.PaperState(),
        10000,
        {"AAA": 10},
        {"AAA": 100, "BBB": 100},
        shown,
        10000,
        set(),
    )
    assert not orders
    receipt = state.allocation_state["receipt"]
    assert receipt["reason"] == "inconsistent_account_equity"
    assert receipt["grade_signals"]["BBB"]["action"] == "buy"


# Grade receipt metadata is retained only when supplied and contains no account state.
def test_grade_signal_receipt_preserves_optional_fields():
    from backend.market import personal_history
    from backend.tests.test_personal_history import FIRING, generated

    decisions, record, snapshot, _ = generated()
    fields = {
        "grade_signal": "buy",
        "signal_session": record["session"],
        "signal_basis": "observed_close_grade",
        "signal_status": "blocked",
        "signal_reason": "Learned size is zero",
    }
    decisions["rows"]["S11"].update(fields)
    receipt = personal_history.project(decisions, record, snapshot, FIRING)
    assert {key: receipt["rows"]["S11"][key] for key in fields} == fields
    assert all(
        "grade_signal" not in row
        for name, row in receipt["rows"].items()
        if name != "S11"
    )


# Personal holdings obey the same grade direction without borrowing paper-account cash.
def test_personal_grade_direction_preserves_a_and_exits_b():
    from backend.market.learned_personal_guidance import _personal_targets

    record = {
        "session": "2026-10-13",
        "targets": {"policy": grade.POLICY},
        "grades": {"AAA": {"grade": "A"}, "BBB": {"grade": "B"}},
        "paper": {"joint_funded": {"receipt": {"status": "available"}}},
    }
    desired, _, available, _ = _personal_targets(
        record,
        {"AAA": 0, "BBB": 0.2},
        {"AAA": 3, "BBB": 2},
        {"AAA": 100, "BBB": 100},
        1000,
        500,
    )
    assert available
    assert desired == {"AAA": 0.3, "BBB": 0}
