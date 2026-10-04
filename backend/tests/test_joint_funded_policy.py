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
from backend.market.joint_funded_policy import POLICY, JointFundedPolicy
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
    reader, held, prices, cash, equity, reason
):
    policy = JointFundedPolicy(reader, 10)
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
