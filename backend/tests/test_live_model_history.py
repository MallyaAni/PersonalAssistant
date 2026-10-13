"""Current-model history must match live numerics and admit only a private ledger."""

from dataclasses import replace
from datetime import datetime, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import paper
from backend.market import calendar, forward_arithmetic, learned_retention_models
from backend.market.joint_funded_policy import GradeLedFundedPolicy
from backend.market.live_model_history import (
    FrozenCurrentGradePolicy,
    FrozenCurrentMarketReader,
    FrozenCurrentRiskReader,
)
from backend.market.market_conditioned_holding import (
    ForwardMarketConditionedHoldingReader,
)
from backend.market.replay_broker import ReplayBroker
from backend.tests.test_forward_holding import example_factory, observation, report
from backend.tests.test_grade_led_policy import chosen
from backend.tests.test_joint_funded_policy import reader as reader
from backend.tests.test_joint_funded_policy import report as graded_report


# Prepare real synthetic published numeric heads without changing production artifacts.
@pytest.fixture(scope="module")
def example(tmp_path_factory):
    return example_factory(tmp_path_factory, with_market=True)


# Bind the same original model and inputs used by the live forward-policy tests.
def frozen(example):
    original, folder, digest, panel, grades, eligible, _, now = example
    head, model = forward_arithmetic.load_publication(
        folder, receipt_sha256=digest, observed_at=now
    )
    return FrozenCurrentMarketReader(
        FrozenCurrentRiskReader(original, panel, grades, eligible, head, model, now)
    )


# Current observations give exactly the same live targets, shares and timing tags.
def test_history_and_live_models_produce_identical_current_sizing(example):
    original, _, _, panel, grades, _, _, _ = example
    current = observation(example)
    live = GradeLedFundedPolicy(
        ForwardMarketConditionedHoldingReader(
            forward_arithmetic.ForwardVolatilityHoldingReader(original, current)
        ),
        10,
    )
    history_reader = frozen(example)
    history_reader.select(len(panel.dates) - 1)
    history = FrozenCurrentGradePolicy(history_reader, 10)
    shown = report(panel, grades)
    values = (
        str(panel.dates[-1]),
        paper.PaperState(),
        10000,
        {},
        {
            name: float(panel.close[-1, index])
            for index, name in enumerate(panel.tickers)
        },
        shown,
        10000,
        set(),
    )
    original_orders, original_state, _ = live.plan(*values)
    new_orders, new_state, _ = history.plan(*values)
    assert (
        new_state.allocation_state["targets"]
        == original_state.allocation_state["targets"]
    )
    assert [(o.symbol, o.side, o.qty, o.execution_timing) for o in new_orders] == [
        (o.symbol, o.side, o.qty, o.execution_timing) for o in original_orders
    ]
    a = live.reader.distribution(len(panel.dates) - 1, ("AAA",))
    b = history_reader.distribution(len(panel.dates) - 1, ("AAA",))
    assert a.receipt["status"] == b.receipt["status"] == "available"
    np.testing.assert_array_equal(a.scenarios, b.scenarios)
    np.testing.assert_array_equal(a.probabilities, b.probabilities)


# Earlier observations use only their feature prefix while keeping the current risk fit.
def test_past_rows_preserve_prefix_features_and_current_calibration(example):
    _, _, _, panel, grades, eligible, provenance, _ = example
    history = frozen(example)
    current_sample = history.distribution(len(panel.dates) - 1, ("AAA",))
    selected = current_sample.receipt["decision_indices"]
    for day in (len(panel.dates) // 2, len(panel.dates) - 20):
        history.select(day)
        past = replace(
            panel,
            **{
                name: getattr(panel, name)[: day + 1]
                for name in (
                    "dates",
                    "open",
                    "high",
                    "low",
                    "close",
                    "adj_close",
                    "volume",
                )
            },
        )
        exact = learned_retention_models.completed_features(
            past, grades[: day + 1], eligible[: day + 1], past.dates, provenance
        )
        np.testing.assert_array_equal(history.current.features, exact["X"][-1])
        sample = history.distribution(day, ("AAA",))
        assert sample.receipt["decision_date"] == str(panel.dates[day])
        assert sample.receipt["decision_indices"] == selected
        assert sample.receipt["fit_date"] == current_sample.receipt["fit_date"]
        assert (
            sample.receipt["original_model_published_at"]
            == history._parent.identity["model_published_at"]
        )
        with pytest.raises(ValueError, match="Selected historical"):
            history.distribution(day + 1, ("AAA",))


# A retrospective reader cannot be admitted through any production broker or clock.
def test_historical_policy_refuses_real_brokers_and_wrong_close(example):
    history = frozen(example)
    day = len(history.dates) - 20
    history.select(day)
    policy = FrozenCurrentGradePolicy(history, 10)
    session = history.dates[-1].astype(object)
    at = datetime.combine(
        session, calendar.session_close(session), calendar.NEW_YORK
    ) + timedelta(minutes=1)
    policy.admit_broker(ReplayBroker(10000, 10), at)
    with pytest.raises(ValueError, match="real broker"):
        policy.admit_broker(object(), at)
    with pytest.raises(ValueError, match="historical close"):
        policy.admit_broker(ReplayBroker(10000, 10), at + timedelta(minutes=1))


# An eligible drop may add shares when its funded target warrants it.
def test_aplus_drop_can_add_but_cash_and_negative_model_edge_do_not(
    monkeypatch, reader
):
    shown = graded_report(reader, grades=(3, -1))
    session = str(shown.panel.dates[-1])
    positive = chosen(monkeypatch, reader, {"AAA": [0.04, 0.06]})
    first, _, _ = positive.plan(
        session,
        paper.PaperState(),
        10000,
        {"AAA": 10},
        {"AAA": 100},
        shown,
        9000,
        set(),
    )
    dropped, _, _ = positive.plan(
        session, paper.PaperState(), 9800, {"AAA": 10}, {"AAA": 80}, shown, 9000, set()
    )
    first_qty = sum(o.qty for o in first if o.side == "buy")
    dropped_qty = sum(o.qty for o in dropped if o.side == "buy")
    assert dropped_qty > first_qty > 0
    cashless, _, _ = positive.plan(
        session, paper.PaperState(), 800, {"AAA": 10}, {"AAA": 80}, shown, 0, set()
    )
    assert not any(o.side == "buy" for o in cashless)
    negative = chosen(monkeypatch, reader, {"AAA": [-0.04, -0.02]})
    weak, _, _ = negative.plan(
        session, paper.PaperState(), 9800, {"AAA": 10}, {"AAA": 80}, shown, 9000, set()
    )
    assert not weak
