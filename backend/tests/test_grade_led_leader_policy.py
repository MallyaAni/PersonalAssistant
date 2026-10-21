"""Leader-weight sizing: the arithmetic, the funded plan, unit capital, selection."""

import json
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import grading, paper
from backend.market import adaptive_growth_policy as growth
from backend.market import grade_led_leader_policy as leader
from backend.market import grade_led_policy as grade
from backend.market import strategy_model_allocation, strategy_publication
from backend.market.panel import Panel
from backend.tests.test_joint_funded_policy import reader as reader  # noqa: F401
from backend.tests.test_learned_live_holding import example as example  # noqa: F401

# CCC is outside the bound reader's cohort, so it is only ever ungraded here.
NAMES = ("AAA", "BBB", "CCC", "SPY", "QQQ")
DRIFT = np.array([0.004, 0.001, 0.002, 0.0, 0.0])


# Geometric closes with a seeded wobble, so AAA leads BBB over any long window.
def closes(sessions, drift=DRIFT, wobble=0.01, seed=7):
    steps = np.random.default_rng(seed).normal(0.0, wobble, (sessions, len(drift)))
    return 100.0 * np.exp(np.cumsum(steps + drift, axis=0))


# A completed report on the reader's calendar with explicit final and prior grades.
def leader_report(reader, grades, prior=None, sessions=None):
    day = len(reader.dates) - 1 if sessions is None else sessions - 1
    prices = closes(day + 1)
    panel = Panel(
        reader.dates[: day + 1].copy(), NAMES, prices, prices + 1, prices - 1,
        prices, prices, np.ones_like(prices), {}, "SPY",
    )
    values = np.tile(grades, (day + 1, 1)).astype(np.int16)
    if prior is not None:
        values[-2] = prior
    return SimpleNamespace(
        panel=panel,
        graded=grading.Graded(values, np.zeros_like(prices), {}),
        sides={"AAA": "long", "BBB": "long", "CCC": "long"},
        scores=values.astype(float),
    )


# Install the leader selector over the grade-led synthetic release without refitting.
def install_leader(root, fixture, monkeypatch):
    from backend.market import learned_live_holding as runtime
    from backend.tests.test_grade_led_policy import install_grade_led

    _, shown, now = install_grade_led(root, fixture, monkeypatch)
    config_path = root / runtime.CONFIG
    config = json.loads(config_path.read_bytes())
    release_path = config_path.with_name("release.json")
    release = json.loads(release_path.read_bytes())
    config["policy"] = release["policy"] = leader.POLICY
    raw = json.dumps(release).encode()
    release_path.write_bytes(raw)
    config["release_receipt_sha256"] = sha256(raw).hexdigest()
    config_path.write_text(json.dumps(config))
    return runtime.prepare(root, shown, clock=lambda: now), shown, now


# A funded leader policy whose risk reader is never allowed to be sampled.
def chosen(reader, monkeypatch):
    policy = leader.GradeLedLeaderFundedPolicy(reader, 10)

    # The optimiser's scenario model must not be read at all by this policy.
    def forbidden(*args, **kwargs):
        pytest.fail("Leader sizing read the scenario distribution")

    monkeypatch.setattr(policy.reader, "distribution", forbidden)
    return policy


# Strength zero is plain equal weight; strength 0.5 orders the slots by trailing return.
def test_equal_slots_and_leader_tilt_ordering():
    window = closes(leader.WINDOW + 1, wobble=0.0)
    sized = np.array([True, True, True, False, False])
    equal, certificate = leader.leader_weights(window, sized, strength=0.0)
    assert np.allclose(equal[sized], equal[sized][0])
    assert certificate["optimizer_ran"] is False
    tilted, certificate = leader.leader_weights(window, sized, cap=1.0)
    assert tilted[0] > tilted[2] > tilted[1] > 0
    assert np.isclose(tilted[0] / tilted[1], 1.5 / 0.5)
    assert certificate["multipliers"] == [1.5, 0.5, 1.0]
    assert np.isclose(tilted.sum(), certificate["gross"])
    assert tilted[3] == tilted[4] == 0


# A calm basket is fully invested; a wild one is scaled down and never levered.
@pytest.mark.parametrize("wobble", [0.0, 0.002, 0.05, 0.2])
def test_volatility_scale_never_exceeds_one(wobble):
    window = closes(leader.WINDOW + 1, wobble=wobble, seed=3)
    sized = np.array([True, True, True, True, True])
    weights, certificate = leader.leader_weights(window, sized, cap=1.0)
    assert 0 < certificate["scale"] <= 1
    assert np.isclose(weights.sum(), certificate["scale"])
    assert weights.sum() <= 1 + 1e-12
    basket = np.diff(np.log(window), axis=0).mean(axis=1)
    realised = leader.forecast_volatility(basket)
    alpha = 2 / (leader.EWMA_SPAN + 1)
    weights = (1 - alpha) ** np.arange(len(basket))[::-1]
    expected_vol = np.sqrt(np.sum(weights * basket**2) / weights.sum() * 252)
    assert np.isclose(realised, expected_vol)
    assert np.isclose(certificate["realised_volatility"], realised)
    assert certificate["volatility_estimator"] == f"ewma_span_{leader.EWMA_SPAN}"
    expected = min(1.0, 0.25 / realised) if realised else 1.0
    assert np.isclose(certificate["scale"], expected)


# The per-name cap trims a slot and leaves the excess in cash rather than elsewhere.
def test_cap_leaves_excess_in_cash():
    window = closes(leader.WINDOW + 1, wobble=0.0)
    sized = np.array([True, True, False, False, False])
    weights, _ = leader.leader_weights(window, sized)
    assert weights[0] == growth.CAP
    assert weights[1] == growth.CAP
    assert weights.sum() <= 1


# No name is sized by anything but its own finite window, and the input is checked.
def test_requires_exact_window_and_finite_closes():
    window = closes(leader.WINDOW + 1, wobble=0.0)
    with pytest.raises(ValueError, match="window"):
        leader.leader_weights(window[1:], np.ones(5, dtype=bool))
    broken = window.copy()
    broken[10, 1] = np.nan
    with pytest.raises(ValueError, match="Finite"):
        leader.leader_weights(broken, np.ones(5, dtype=bool))
    weights, certificate = leader.leader_weights(
        broken, np.array([True, False, True, False, False])
    )
    assert weights[1] == 0
    assert weights[0] > 0
    none, certificate = leader.leader_weights(window, np.zeros(5, dtype=bool))
    assert not none.any()
    assert certificate["status"] == "no_sized_names"


# Only the trailing window ending on the decision session is read from a report.
def test_size_report_reads_nothing_outside_the_trailing_window(reader):
    shown = leader_report(reader, (3, 3, 3, 0, 0))
    names = ("AAA", "BBB", "CCC")
    sizes, certificate = leader.size_report(shown, names, set(), {})
    earlier = leader_report(reader, (3, 3, 3, 0, 0))
    earlier.panel.adj_close[: -(leader.WINDOW + 1)] *= 3.0
    earlier.panel.adj_close[: -(leader.WINDOW + 1), 1] = np.nan
    assert leader.size_report(earlier, names, set(), {})[0] == sizes
    assert certificate["dates"] == [
        str(shown.panel.dates[-(leader.WINDOW + 1)]), str(shown.panel.dates[-1])
    ]
    assert certificate["unsized"] == []
    short = leader_report(reader, (3, 3, 3, 0, 0), sessions=40)
    with pytest.raises(ValueError, match="longer than the report"):
        leader.size_report(short, names, set(), {})


# A grade exit is sold, an ungraded holding is kept whole, and the rest is leader-sized.
def test_funded_decision_with_held_exit_and_protected_names(reader, monkeypatch):
    policy = chosen(reader, monkeypatch)
    shown = leader_report(reader, (3, 1, -1, 0, 0), prior=(3, 3, -1, 0, 0))
    day = str(shown.panel.dates[-1])
    held = {"AAA": 10, "BBB": 10, "CCC": 10}
    prices = {"AAA": 100.0, "BBB": 100.0, "CCC": 100.0}
    targets, receipt = policy.decide(day, shown, 10000, held, prices, 7000, set())
    assert receipt["status"] == "available"
    assert receipt["reason"] == receipt["target_basis"] == leader.BASIS
    assert receipt["policy"] == leader.POLICY == policy.version
    assert receipt["company_exits"] == ["BBB"]
    assert receipt["protected_holdings"] == ["CCC"]
    assert targets["BBB"] == 0
    assert targets["CCC"] == pytest.approx(0.1)
    assert 0 < targets["AAA"] <= growth.CAP
    assert sum(targets.values()) <= 1 + 1e-10
    assert receipt["leader_sizing"]["status"] == "sized"
    assert receipt["sizing_model_targets"]["AAA"] == targets["AAA"]
    assert receipt["grade_signals"]["BBB"]["action"] == "sell"
    assert receipt["grade_signals"]["CCC"]["action"] == "unavailable"
    assert receipt["entry_qualification"]["joint_risk_still_required"] is False
    for claim in ("optimizer", "sizing_optimizer", "scenario"):
        assert claim not in receipt
    assert receipt["transition"]["retained_weights"] == {"CCC": pytest.approx(0.1)}
    # The modeled book is sized on the capital the protected holding does not use.
    assert targets["AAA"] == pytest.approx(
        receipt["modeled_decision"]["targets"]["AAA"] * 0.9
    )
    assert receipt["sizing_source_sha256"] == sha256(
        Path(leader.__file__).read_bytes()
    ).hexdigest()


# Without protected names the funded sizes are exactly the unit-capital leader weights.
def test_funded_sizes_match_the_pure_function(reader, monkeypatch):
    policy = chosen(reader, monkeypatch)
    shown = leader_report(reader, (3, 2, -1, 0, 0))
    day = str(shown.panel.dates[-1])
    targets, receipt = policy.decide(day, shown, 10000, {}, {}, 10000, set())
    sizes, certificate = leader.size_report(shown, ("AAA", "BBB"), set(), {})
    assert {name: targets[name] for name in sizes} == sizes
    assert targets["CCC"] == 0
    assert receipt["leader_sizing"] == certificate
    assert receipt["entry_qualification"]["admitted_entrants"] == ["AAA", "BBB"]


# A buy-blocked holding keeps its size but may not grow; a blocked entrant is excluded.
def test_blocked_names_cannot_grow(reader, monkeypatch):
    policy = chosen(reader, monkeypatch)
    shown = leader_report(reader, (3, 3, -1, 0, 0))
    day = str(shown.panel.dates[-1])
    targets, receipt = policy.decide(
        day, shown, 10000, {"AAA": 2}, {"AAA": 100.0}, 9800, {"AAA", "BBB"}
    )
    assert targets["AAA"] == pytest.approx(0.02)
    assert targets["BBB"] == 0
    assert receipt["status"] == "available"
    assert receipt["entry_qualification"]["excluded_entries"] == {
        "BBB": {"reason": "buy_permission_blocked"}
    }
    assert receipt["grade_signals"]["BBB"]["action"] == "buy"


# A held name without a full trailing window refuses the night's sizing, not the exit.
def test_short_window_refuses_sizing_but_keeps_grade_exit(reader, monkeypatch):
    policy = chosen(reader, monkeypatch)
    shown = leader_report(reader, (3, 1, -1, 0, 0), prior=(3, 3, -1, 0, 0))
    shown.panel.adj_close[-5, 0] = np.nan
    day = str(shown.panel.dates[-1])
    held = {"AAA": 10, "BBB": 10}
    prices = {"AAA": 100.0, "BBB": 100.0}
    targets, receipt = policy.decide(day, shown, 10000, held, prices, 8000, set())
    assert receipt["status"] == "unavailable"
    assert receipt["reason"] == "leader_window_unavailable"
    assert receipt["leader_sizing"]["symbols"] == ["AAA"]
    assert targets["BBB"] == 0
    assert targets["AAA"] == pytest.approx(0.1)
    unheld = leader_report(reader, (3, 3, -1, 0, 0))
    unheld.panel.adj_close[-5, 0] = np.nan
    targets, receipt = policy.decide(day, unheld, 10000, {}, {}, 10000, set())
    assert receipt["status"] == "available"
    assert targets["AAA"] == 0
    assert targets["BBB"] > 0
    assert receipt["entry_qualification"]["excluded_entries"]["AAA"] == {
        "reason": "trailing_window_unavailable"
    }
    assert receipt["entry_qualification"]["admitted_entrants"] == ["BBB"]


# Orders say what sized them, and a grade exit keeps the parent's exit wording.
def test_plan_labels_orders_by_leader_sizing(reader, monkeypatch):
    policy = chosen(reader, monkeypatch)
    shown = leader_report(reader, (3, 1, -1, 0, 0), prior=(3, 3, -1, 0, 0))
    day = str(shown.panel.dates[-1])
    orders, state, note = policy.plan(
        day, paper.PaperState(), 10000, {"BBB": 10}, {"AAA": 100.0, "BBB": 100.0},
        shown, 9000, set(),
    )
    assert note == "joint-funded"
    reasons = {order.symbol: order.reason for order in orders}
    assert reasons == {
        "AAA": "Grade-led leader-weight sizing adjustment",
        "BBB": "Grade below A; exit",
    }
    assert state.policy_version == leader.POLICY
    assert state.allocation_state["receipt"]["target_basis"] == leader.BASIS
    # Every leg goes to the opening auction; nothing waits on the learned timing.
    timing = state.allocation_state["receipt"]["execution_timing"]
    assert timing["company_exit"] == "next_open"
    assert timing["ordinary"] == "next_open"
    assert {order.execution_timing for order in orders} == {"next_open"}
    assert all(
        timing["orders"][order.client_order_id] == "next_open" for order in orders
    )


# Unit-capital targets use the funded plan's arithmetic and claim no optimiser.
def test_unit_capital_targets_share_the_sizing(reader):
    shown = leader_report(reader, (3, 3, -1, 0, 0))
    targets, signals, receipt = strategy_model_allocation.targets_from_model(
        shown, reader, 10, {"BBB"}, leader.POLICY
    )
    sizes, certificate = leader.size_report(shown, ("AAA",), {"BBB"}, {})
    assert targets == {**sizes, "BBB": 0.0, "CCC": 0.0}
    assert receipt["leader_sizing"] == certificate
    assert "optimizer" not in receipt
    assert receipt["scenario"] is None
    qualification = receipt["entry_qualification"]["entry_qualification"]
    assert qualification["policy"] == leader.POLICY
    assert qualification["excluded_entries"] == {
        "BBB": {"reason": "buy_permission_blocked"}
    }
    assert signals == grade.signals(shown, {})
    with pytest.raises(ValueError, match="grade-led model required"):
        strategy_model_allocation.targets_from_model(shown, reader, 10, set(), "x")


# The installed selector accepts the leader id and prepares the leader holding policy.
def test_configuration_selects_leader_holding_policy(example, tmp_path, monkeypatch):
    from backend.market import learned_live_holding as runtime

    selected, shown, now = install_leader(tmp_path, example, monkeypatch)
    assert type(selected) is runtime.GradeLedLeaderHoldingPolicy
    assert selected.version == leader.POLICY
    assert selected.identity["sizing_basis"] == leader.BASIS
    assert "backend/market/grade_led_leader_policy.py" in runtime.source_identity()
    assert leader.PROTOCOL in runtime.source_identity()
    _, read = runtime.read_configuration(tmp_path, now)
    assert read["policy"] == leader.POLICY
    published = strategy_publication.read(tmp_path, now)
    assert published["policy"] == leader.POLICY
    assert published["calculation_receipt"]["leader_sizing"]["basis"] == leader.BASIS
    assert "optimizer" not in published["calculation_receipt"]
