"""Actual-account optional policy journeys and independent funded edge cases."""

from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import grading, nightly_plan, paper
from backend.cli import market_daily
from backend.market import calendar
from backend.market import direct_feature_arithmetic as feature
from backend.market.direct_error_band import VolatilityHoldingReader
from backend.market.joint_funded_accounts import candidate_grid
from backend.market.joint_funded_policy import (
    MATURITY_POLICY,
    POLICY,
    JointFundedPolicy,
    MaturityFundedPolicy,
)
from backend.market.live_policy_replay import run_account
from backend.market.panel import Panel
from backend.market.replay_broker import ReplayBroker
from backend.tests.test_direct_feature_arithmetic import risk_example_factory
from backend.tests.test_live_policy_replay import fixture as replay_fixture
from backend.tests.test_nightly_plan import inputs as nightly_inputs


# Bind a real saved-head reader once; synthetic decision scenarios are separate tests.
@pytest.fixture(scope="module")
def reader(tmp_path_factory):
    example = risk_example_factory(tmp_path_factory, with_volatility=True)
    return VolatilityHoldingReader(example[-1], example[1])


# Reuse numeric heads while withholding an ungraded stock's early price history.
@pytest.fixture(scope="module")
def short_history(tmp_path_factory):
    prepared, bridge, parent, heads, risk = risk_example_factory(
        tmp_path_factory, with_volatility=True
    )
    prices = risk.prices.copy()
    prices[:700, 1] = np.nan
    expanded = feature.holding_risk_forecasts(
        parent, bridge, prepared["X"], prepared["valid"], heads, prices=prices
    )
    return (
        VolatilityHoldingReader(expanded, bridge),
        prepared,
        bridge,
        parent,
        heads,
        prices,
    )


# Supply only a complete current prefix, original stock names and observed grades.
def report(reader, *, day=None, grades=(3, 3)):
    day = len(reader.dates) - 1 if day is None else day
    names = ("AAA", "BBB", "SPY", "QQQ")
    prices = np.full((day + 1, 4), 100.0)
    panel = Panel(
        reader.dates[: day + 1].copy(),
        names,
        prices,
        prices + 1,
        prices - 1,
        prices,
        prices,
        np.ones_like(prices),
        {},
        "SPY",
    )
    values = np.tile([*grades, 0, 0], (day + 1, 1)).astype(np.int16)
    return SimpleNamespace(
        panel=panel,
        graded=grading.Graded(values, np.zeros_like(prices), {}),
        sides={"AAA": "long", "BBB": "long"},
        scores=values.astype(float),
    )


# Replace only the decision sample to prove share economics against a known oracle.
def analytic(monkeypatch, reader, values, cost=10):
    policy = JointFundedPolicy(reader, cost)

    # Keep requested symbol order explicit while supplying equal joint date mass.
    def sample(day, symbols):
        columns = np.array([values[name] for name in symbols], dtype=float).T
        return feature.HoldingScenarios(
            columns,
            np.full(len(columns), 1 / len(columns)),
            symbols,
            {"status": "available", "synthetic": True},
        )

    monkeypatch.setattr(reader, "distribution", sample)
    return policy


# A real short-history entrant cannot freeze supported stocks, while v1 stays unchanged.
def test_maturity_qualification_keeps_supported_unheld_entries(short_history):
    reader = short_history[0]
    shown = report(reader, grades=(3, 3))
    session = str(shown.panel.dates[-1])
    original, old = JointFundedPolicy(reader, 10).decide(
        session, shown, 10000.0, {}, {"AAA": 100.0, "BBB": 100.0}, 10000.0, set()
    )
    targets, new = MaturityFundedPolicy(reader, 10).decide(
        session, shown, 10000.0, {}, {"AAA": 100.0, "BBB": 100.0}, 10000.0, set()
    )
    assert original == {}
    assert old["status"] == "unavailable"
    assert "entry_qualification" not in old
    assert new["policy"] == MATURITY_POLICY
    assert new["status"] == "available"
    assert new["grades"] == old["grades"]
    assert new["scenario"]["symbols"] == ["AAA"]
    assert new["scenario"]["joint_dates"] >= 252
    assert new["optimizer"]["certificate"]["certified"]
    assert set(targets) <= {"AAA"}
    qualification = new["entry_qualification"]
    assert qualification["considered_entrants"] == ["AAA", "BBB"]
    assert qualification["admitted_entrants"] == ["AAA"]
    assert qualification["excluded_entries"]["BBB"]["risk"]["joint_dates"] < 252
    assert (
        qualification["excluded_entries"]["BBB"]["risk"]["reason"]
        == "insufficient_joint_history"
    )


# An unavailable held stock must still block additions without any forced liquidation.
@pytest.mark.parametrize(("grade", "blocked"), [(3, set()), (1, {"BBB"}), (3, {"BBB"})])
def test_maturity_qualification_never_removes_retained_risk(
    short_history, grade, blocked
):
    reader = short_history[0]
    shown = report(reader, grades=(3, grade))
    orders, state, _ = MaturityFundedPolicy(reader, 10).plan(
        str(shown.panel.dates[-1]),
        paper.PaperState(),
        10000.0,
        {"BBB": 10},
        {"AAA": 100.0, "BBB": 100.0},
        shown,
        9000.0,
        blocked,
    )
    receipt = state.allocation_state["receipt"]
    assert not orders
    assert receipt["targets"] == {"BBB": 0.1}
    assert receipt["reason"] == "joint_risk_unavailable"
    assert receipt["entry_qualification"]["mandatory_held"] == ["BBB"]
    assert "BBB" not in receipt["entry_qualification"]["excluded_entries"]
    assert receipt["scenario"]["symbols"] == ["AAA", "BBB"]
    assert state.policy_version == MATURITY_POLICY


# A blocked unheld name needs no inferred risk and remains an explicit missed entrant.
def test_maturity_qualification_honors_buy_permission_first(short_history, monkeypatch):
    reader = short_history[0]
    original, calls = reader.distribution, []

    # Observe original requests without substituting forecasts or risk outcomes.
    def inspect(day, symbols):
        calls.append(tuple(symbols))
        return original(day, symbols)

    monkeypatch.setattr(reader, "distribution", inspect)
    shown = report(reader, grades=(3, 3))
    _, receipt = MaturityFundedPolicy(reader, 10).decide(
        str(shown.panel.dates[-1]),
        shown,
        10000.0,
        {},
        {"AAA": 100.0, "BBB": 100.0},
        10000.0,
        {"BBB"},
    )
    assert receipt["status"] == "available"
    assert receipt["entry_qualification"]["excluded_entries"]["BBB"] == {
        "reason": "buy_permission_blocked"
    }
    assert calls == [("AAA",), ("AAA",)]


# Individual qualification cannot replace a simultaneous book or trigger subset search.
def test_maturity_qualification_still_requires_joint_intersection(reader, monkeypatch):
    calls = []

    # Supply a declared synthetic oracle with individually valid but absent joint risk.
    def partial(day, symbols):
        calls.append(tuple(symbols))
        if len(symbols) == 1:
            return feature.HoldingScenarios(
                np.full((252, 1), 0.02),
                np.full(252, 1 / 252),
                tuple(symbols),
                {"status": "available", "synthetic": True},
            )
        return feature.HoldingScenarios(
            None,
            None,
            tuple(symbols),
            {
                "status": "unavailable",
                "reason": "insufficient_joint_history",
                "synthetic": True,
            },
        )

    monkeypatch.setattr(reader, "distribution", partial)
    shown = report(reader, grades=(3, 3))
    targets, receipt = MaturityFundedPolicy(reader, 10).decide(
        str(shown.panel.dates[-1]),
        shown,
        10000.0,
        {},
        {"AAA": 100.0, "BBB": 100.0},
        10000.0,
        set(),
    )
    assert calls == [("AAA",), ("BBB",), ("AAA", "BBB")]
    assert targets == {}
    assert receipt["reason"] == "joint_risk_unavailable"


# Current-month outcomes cannot alter qualification or earlier risk rows.
def test_maturity_qualification_does_not_read_current_month_labels(short_history):
    from copy import deepcopy

    from backend.market import daily_arithmetic_bridge as reference
    from backend.market import learned_entry_models as base

    reader, prepared, bridge, parent, heads, prices = short_history
    parent, bridge = feature._copy_feature(parent), deepcopy(bridge)
    bridge.labels[-3, 1] += 0.4
    bridge.manifest["label_sha256"] = reference._hash(bridge.labels)
    identity = parent.manifest["identity"]
    identity["bridge_manifest_sha256"] = base._json_hash(bridge.manifest)
    identity["input_sha256"]["labels"] = reference._hash(bridge.labels)
    parent.manifest["identity_sha256"] = base._json_hash(identity)
    changed = feature.holding_risk_forecasts(
        parent, bridge, prepared["X"], prepared["valid"], heads, prices=prices
    )
    other = VolatilityHoldingReader(changed, bridge)
    shown = report(reader, grades=(3, 3))
    args = (
        str(shown.panel.dates[-1]),
        shown,
        10000.0,
        {},
        {"AAA": 100.0, "BBB": 100.0},
        10000.0,
        set(),
    )
    targets, original = MaturityFundedPolicy(reader, 10).decide(*args)
    same, receipt = MaturityFundedPolicy(other, 10).decide(*args)
    assert same == targets
    assert (
        receipt["entry_qualification"]["admitted_entrants"]
        == original["entry_qualification"]["admitted_entrants"]
    )
    assert (
        receipt["scenario"]["decision_indices"]
        == original["scenario"]["decision_indices"]
    )
    assert (
        receipt["scenario"]["scenarios_sha256"]
        == original["scenario"]["scenarios_sha256"]
    )


# Distinct candidate IDs preserve the full original twenty-start, three-cost cohort.
def test_maturity_candidate_grid_cannot_replace_original_accounts():
    dates = np.arange(np.datetime64("2018-01-01"), np.datetime64("2026-10-01"))
    first = candidate_grid(dates)
    variant = candidate_grid(dates, policy=MATURITY_POLICY)
    assert len(first) == len(variant) == 60
    assert {row["id"] for row in first}.isdisjoint({row["id"] for row in variant})
    for a, b in zip(first, variant, strict=True):
        assert a["arm"] == POLICY
        assert b["arm"] == MATURITY_POLICY
        assert {k: v for k, v in a.items() if k not in ("arm", "id")} == {
            k: v for k, v in b.items() if k not in ("arm", "id")
        }
    with pytest.raises(ValueError, match="Registered funded"):
        candidate_grid(dates, policy="unregistered")


# Greater stock-specific dispersion lowers the exact mean-preserving growth position.
def test_same_mean_higher_risk_reduces_whole_share_size(reader, monkeypatch):
    sizes = []
    for values in ([0.10, -0.09], [0.20, -0.19]):
        policy = analytic(monkeypatch, reader, {"AAA": values})
        current = report(reader, grades=(3, 0))
        orders, state, what = policy.plan(
            str(current.panel.dates[-1]),
            paper.PaperState(),
            100000.0,
            {},
            {"AAA": 100.0},
            current,
            100000.0,
            set(),
        )
        assert what == "joint-funded"
        assert state.allocation_state["receipt"]["optimizer"]["certificate"][
            "certified"
        ]
        sizes.append(orders[0].qty)
    # Analytic zero-cost optimum is mu/(a*b); positive fees reduce it further.
    assert 0 < sizes[1] < sizes[0] <= 250


# The physical plan spends observed cash only, keeping dividend claims unspendable.
def test_receivable_is_not_cash_and_sales_do_not_fund_buys(reader, monkeypatch):
    policy = analytic(monkeypatch, reader, {"AAA": [0.10, 0.12]})
    current = report(reader, grades=(3, 0))
    orders, state, _ = policy.plan(
        str(current.panel.dates[-1]),
        paper.PaperState(),
        10000.0,
        {"BBB": 20},
        {"AAA": 100.0, "BBB": 100.0},
        current,
        101.0,
        set(),
    )
    assert {(o.symbol, o.side, o.qty) for o in orders} == {
        ("AAA", "buy", 1),
        ("BBB", "sell", 20),
    }
    assert state.allocation_state["receipt"]["reserved_wealth"] == 7899.0
    assert state.allocation_state["receipt"]["optimizer"]["mandatory_exits"] == [
        False,
        True,
    ]
    assert sum(o.qty * 100 * 1.001 for o in orders if o.side == "buy") <= 101.0


# An unavailable inherited holding never becomes a company exit or funding source.
def test_protected_holding_blocks_adds_but_observed_c_exit_survives(
    reader, monkeypatch
):
    policy = analytic(monkeypatch, reader, {"AAA": [0.10, 0.12]})
    current = report(reader, grades=(3, 0))
    orders, state, what = policy.plan(
        str(current.panel.dates[-1]),
        paper.PaperState(),
        10000.0,
        {"CHILD": 10, "BBB": 3},
        {"CHILD": 20.0, "BBB": 100.0, "AAA": 100.0},
        current,
        5000.0,
        set(),
    )
    assert what == "joint-funded-unavailable"
    assert [(o.symbol, o.side, o.qty) for o in orders] == [("BBB", "sell", 3)]
    assert state.allocation_state["receipt"]["protected_holdings"] == ["CHILD"]
    assert state.allocation_state["targets"]["CHILD"] == 0.02


# Unknown marks or inconsistent balances stop discretionary sizing.
@pytest.mark.parametrize("policy_type", [JointFundedPolicy, MaturityFundedPolicy])
@pytest.mark.parametrize(
    ("held", "prices", "cash", "equity", "reason"),
    [
        ({"CHILD": 2}, {"AAA": 100}, 1000.0, 10000.0, "held_mark_unavailable"),
        (
            {"AAA": 2.5},
            {"AAA": 100},
            1000.0,
            10000.0,
            "whole_share_holdings_unavailable",
        ),
        ({"AAA": 20}, {"AAA": 100}, 1000.0, 2000.0, "inconsistent_account_equity"),
        ({}, {}, None, 2000.0, "account_cash_or_equity_unavailable"),
    ],
)
def test_incomplete_actual_account_emits_no_orders(
    reader, held, prices, cash, equity, reason, policy_type
):
    policy = policy_type(reader, 10)
    current = report(reader)
    orders, state, _ = policy.plan(
        str(current.panel.dates[-1]),
        paper.PaperState(),
        equity,
        held,
        prices,
        current,
        cash,
        set(),
    )
    assert not orders
    assert state.allocation_state["receipt"]["reason"] == reason
    if policy_type is MaturityFundedPolicy:
        q = state.allocation_state["receipt"]["entry_qualification"]
        assert q["status"] == "not_evaluated"
        assert q["reason"] == reason


# An entirely unsupported entrant pool reports unavailable without a false growth claim.
def test_maturity_empty_risk_pool_remains_unavailable(reader):
    shown = report(reader, day=300, grades=(3, 3))
    orders, state, _ = MaturityFundedPolicy(reader, 10).plan(
        str(shown.panel.dates[-1]),
        paper.PaperState(),
        10000.0,
        {},
        {"AAA": 100.0, "BBB": 100.0},
        shown,
        10000.0,
        set(),
    )
    receipt = state.allocation_state["receipt"]
    assert not orders
    assert receipt["status"] == "unavailable"
    assert receipt["reason"] == "entry_risk_unavailable"
    assert receipt["entry_qualification"]["admitted_entrants"] == []
    assert set(receipt["entry_qualification"]["excluded_entries"]) == {"AAA", "BBB"}


# Grade B permits existing ownership but cannot create or increase a position.
def test_b_retention_and_band_blocking_never_grant_adds(reader, monkeypatch):
    policy = analytic(monkeypatch, reader, {"AAA": [0.02, 0.03], "BBB": [0.02, 0.03]})
    current = report(reader, grades=(1, 3))
    orders, state, _ = policy.plan(
        str(current.panel.dates[-1]),
        paper.PaperState(),
        10000.0,
        {"AAA": 10},
        {"AAA": 100.0, "BBB": 100.0},
        current,
        9000.0,
        {"BBB"},
    )
    assert not orders
    assert state.allocation_state["targets"]["AAA"] == 0.1
    assert state.allocation_state["targets"]["BBB"] == 0


# Negative remaining utility exits B without a fixed profit percentage.
def test_negative_remaining_utility_exits_b_without_a_percentage_target(
    reader, monkeypatch
):
    policy = analytic(monkeypatch, reader, {"AAA": [-0.02, -0.03]})
    current = report(reader, grades=(1, 0))
    orders, _, _ = policy.plan(
        str(current.panel.dates[-1]),
        paper.PaperState(),
        10000.0,
        {"AAA": 10},
        {"AAA": 100.0},
        current,
        9000.0,
        set(),
    )
    assert [(o.symbol, o.side, o.qty) for o in orders] == [("AAA", "sell", 10)]


# Repeated session observations preserve durable IDs, targets and actual pending orders.
def test_repeat_and_pending_event_boundary_are_idempotent(reader, monkeypatch):
    policy = analytic(monkeypatch, reader, {"AAA": [0.02, 0.03]})
    current = report(reader, grades=(3, 0))
    session = str(current.panel.dates[-1])
    orders, state, _ = policy.plan(
        session,
        paper.PaperState(),
        10000.0,
        {},
        {"AAA": 100.0},
        current,
        10000.0,
        set(),
    )
    assert orders
    repeated, after, what = policy.plan(
        session, state, 10000.0, {}, {"AAA": 100.0}, current, 10000.0, set()
    )
    assert repeated == []
    assert what == "already planned for this session"
    assert after == state
    assert nightly_plan.event_plan_required(
        replace(state, pending=[{"unresolved": True}]),
        {"calendar_known": True, "factor": 1.0},
    )


# Insufficient authentic past support waits without fallback buys or forced liquidation.
def test_real_reader_cold_start_preserves_holdings(reader):
    policy = JointFundedPolicy(reader, 10)
    current = report(reader, day=300, grades=(3, 0))
    orders, state, _ = policy.plan(
        str(current.panel.dates[-1]),
        paper.PaperState(),
        10000.0,
        {"AAA": 10},
        {"AAA": 100.0},
        current,
        9000.0,
        set(),
    )
    assert not orders
    assert state.allocation_state["receipt"]["reason"] == "joint_risk_unavailable"


# Exercise actual submission, MOO fill, reconciliation and account persistence.
@pytest.mark.parametrize("synthetic_buy", [False, True])
def test_actual_private_broker_nightly_and_next_open_journey(
    reader, tmp_path, monkeypatch, synthetic_buy
):
    policy = (
        analytic(monkeypatch, reader, {"AAA": [0.02, 0.03]})
        if synthetic_buy
        else JointFundedPolicy(reader, 10)
    )
    current = report(
        reader, day=len(reader.dates) - 2, grades=(3, 0) if synthetic_buy else (0, 3)
    )
    session = str(current.panel.dates[-1])
    now = datetime.combine(
        current.panel.dates[-1].astype(object),
        calendar.session_close(current.panel.dates[-1].astype(object)),
        calendar.NEW_YORK,
    ) + timedelta(minutes=1)
    broker = ReplayBroker(
        100000.0,
        10,
        initial_holdings={} if synthetic_buy else {"AAA": 10},
        initial_average_prices={"AAA": 90.0},
    )
    broker.observe(now, {"AAA": 100.0, "BBB": 100.0}, False)

    # The real feature dependency preserves the ordinary event and band gates.
    def features(kind, ignored):
        return (
            {"calendar_known": True, "factor": 1.0}
            if kind == "event"
            else (set(), {})
            if kind == "blocked"
            else {}
        )

    entry = market_daily.paper_trade(
        current,
        tmp_path,
        session,
        True,
        client_factory=lambda: broker,
        decision_at=now,
        feature_reader=features,
        holding_policy=policy,
    )
    state = paper.load_state(tmp_path)
    assert state.policy_version == POLICY
    assert entry["policy"] == POLICY
    assert entry["execution_rule"] == "next_open"
    assert entry["joint_funded"]["receipt"]["scenario"]["status"] == "available"
    assert entry["orders"]
    assert state.pending
    attempts = broker.attempt_history
    market_daily.paper_trade(
        current,
        tmp_path,
        session,
        True,
        client_factory=lambda: broker,
        decision_at=now,
        feature_reader=features,
        holding_policy=policy,
    )
    assert broker.attempt_history == attempts
    assert paper.load_state(tmp_path).pending == state.pending
    assert {p.symbol: p.qty for p in broker.positions()} == (
        {} if synthetic_buy else {"AAA": 10}
    )
    upcoming = reader.dates[-1].astype(object)
    opening = datetime.combine(upcoming, calendar.REGULAR_OPEN, calendar.NEW_YORK)
    broker.observe(opening, {"AAA": 100.0, "BBB": 100.0}, True)
    broker.flush(opening, {"AAA": 100.0, "BBB": 100.0}, phase="open")
    reconciled, settled = market_daily._reconcile(broker, state, tmp_path, True)
    assert settled
    assert not reconciled.pending
    assert paper.load_state(tmp_path).journal == reconciled.journal
    if synthetic_buy:
        assert sum(p.qty for p in broker.positions()) > 0
        assert broker.account().cash < 100000.0
    else:
        actual = {p.symbol: p.qty for p in broker.positions()}
        assert "AAA" not in actual
        assert actual["BBB"] == 252
        assert broker.account().cash == pytest.approx(75773.8)
    assert broker.account().cash >= 0


# Research overrides must never gain an environment broker through missing dependencies.
def test_private_candidate_requires_clock_and_broker(reader, tmp_path):
    with pytest.raises(ValueError, match="private broker and clock"):
        market_daily.paper_trade(
            report(reader),
            tmp_path,
            str(reader.dates[-1]),
            True,
            holding_policy=JointFundedPolicy(reader, 10),
        )
    assert not paper.state_path(tmp_path).exists()


# Freeze all starts and fees rather than selecting the best funded outcome later.
def test_fixed_account_grid_retains_twenty_starts_and_three_costs():
    dates = np.arange(np.datetime64("2018-01-01"), np.datetime64("2026-10-01"))
    dates = dates[np.is_busday(dates)]
    grid = candidate_grid(dates)
    assert len(grid) == 60
    assert len({row["id"] for row in grid}) == 60
    for cost in (0, 10, 25):
        rows = [row for row in grid if row["cost_bps"] == cost]
        assert {row["start"] for row in rows} == set(range(20))
        assert rows[0]["first_session"] == "2018-02-01"
        assert all(dates[row["last"]] == np.datetime64("2026-09-30") for row in rows)


# Follow the full chronological account runner with actual source and private storage.
def test_chronological_runner_uses_joint_policy_on_every_ordinary_night(
    reader, tmp_path
):
    panel, raw, cubes = replay_fixture(tuple(map(str, reader.dates)))
    policy = JointFundedPolicy(reader, 10)

    # Reuse genuine nightly shape while explicitly disabling synthetic event dates.
    def features(kind, report):
        return (
            {"calendar_known": True, "factor": 1.0}
            if kind == "event"
            else (set(), {})
            if kind == "blocked"
            else {}
        )

    result = run_account(
        panel,
        raw,
        cubes,
        tmp_path / "account",
        len(reader.dates) - 2,
        len(reader.dates) - 1,
        10,
        holding_policy=policy,
        feature_reader=features,
    )
    assert len(result["sessions"]) == 3
    assert result["policy"] == POLICY
    assert all(
        row["nav"] is not None and row["cash"] >= 0 for row in result["sessions"]
    )
    assert all(row["entry"]["policy"] == POLICY for row in result["nightlies"])
    assert paper.load_state(tmp_path / "account").policy_version == POLICY


# A mismatched execution fee cannot silently change the declared optimized economics.
def test_chronological_runner_refuses_fee_substitution_before_writing(reader, tmp_path):
    panel, raw, cubes = replay_fixture(tuple(map(str, reader.dates)))
    with pytest.raises(ValueError, match="identical account fees"):
        run_account(
            panel,
            raw,
            cubes,
            tmp_path / "account",
            len(reader.dates) - 2,
            len(reader.dates) - 1,
            25,
            holding_policy=JointFundedPolicy(reader, 10),
        )
    assert not (tmp_path / "account").exists()


# Real event reductions and unknown calendars bypass ordinary learned decisions.
@pytest.mark.parametrize("known", [False, True])
def test_joint_policy_cannot_override_event_safety(reader, monkeypatch, known):
    policy = JointFundedPolicy(reader, 10)

    # Fail if event handling ever asks the ordinary growth policy for orders.
    def forbidden(*args, **kwargs):
        pytest.fail("Event safety dispatched to ordinary risk policy")

    monkeypatch.setattr(policy, "plan", forbidden)
    event = {"calendar_known": known, "factor": 0.5, "decision_date": "2026-09-16"}
    args = nightly_inputs(held={"AAA": 100}, cash=0.0, event_policy=event)
    orders, state, what = nightly_plan.plan(**args, holding_policy=policy)
    assert state.policy_version == POLICY
    if known:
        assert [(o.side, o.qty) for o in orders] == [("sell", 50)]
        assert what == "FOMC reduction"
    else:
        assert not orders
        assert "calendar unavailable" in what


# Fresh inherited marks preserve the asset without hiding a known company exit.
def test_actual_nightly_inherited_mark_allows_only_known_company_exit(reader, tmp_path):
    current = report(reader, day=len(reader.dates) - 2, grades=(0, 3))
    session = str(current.panel.dates[-1])
    now = datetime.combine(
        current.panel.dates[-1].astype(object),
        calendar.REGULAR_CLOSE,
        calendar.NEW_YORK,
    ) + timedelta(minutes=1)
    broker = ReplayBroker(
        10000.0,
        10,
        initial_holdings={"AAA": 10, "CHILD": 2},
        initial_average_prices={"AAA": 90.0, "CHILD": 20.0},
    )
    broker.observe(now, {"AAA": 100.0, "BBB": 100.0, "CHILD": 20.0}, False)

    # Reuse a declared ordinary event clock and no synthetic extra stock permission.
    def features(kind, ignored):
        return (
            {"calendar_known": True, "factor": 1.0}
            if kind == "event"
            else (set(), {})
            if kind == "blocked"
            else {}
        )

    entry = market_daily.paper_trade(
        current,
        tmp_path,
        session,
        True,
        client_factory=lambda: broker,
        decision_at=now,
        feature_reader=features,
        holding_policy=JointFundedPolicy(reader, 10),
    )
    assert [(row["symbol"], row["side"], row["qty"]) for row in entry["orders"]] == [
        ("AAA", "sell", 10)
    ]
    assert (
        entry["joint_funded"]["receipt"]["reason"] == "protected_held_risk_unavailable"
    )
    assert entry["joint_funded"]["targets"]["CHILD"] > 0


# A future private mark cannot cause cancellation, state writes or order submission.
def test_joint_nightly_refuses_future_ledger_clock_before_side_effects(
    reader, tmp_path
):
    current = report(reader, day=len(reader.dates) - 2)
    day = current.panel.dates[-1].astype(object)
    now = datetime.combine(day, calendar.REGULAR_CLOSE, calendar.NEW_YORK) + timedelta(
        minutes=1
    )
    broker = ReplayBroker(10000.0, 10)
    broker.observe(now + timedelta(minutes=1), {"AAA": 100.0, "BBB": 100.0}, False)
    before = broker.ledger()
    with pytest.raises(ValueError, match="exact decision clock"):
        market_daily.paper_trade(
            current,
            tmp_path,
            str(day),
            True,
            client_factory=lambda: broker,
            decision_at=now,
            holding_policy=JointFundedPolicy(reader, 10),
        )
    assert broker.ledger() == before
    assert not broker.attempt_history
    assert not paper.state_path(tmp_path).exists()
