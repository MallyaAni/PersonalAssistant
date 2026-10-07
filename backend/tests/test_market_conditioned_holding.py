"""Causal feature binding, independent scenarios and actual private funded timing."""

from copy import deepcopy
from datetime import datetime, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import paper
from backend.cli import market_daily
from backend.market import calendar, forward_execution, forward_probability_timing
from backend.market import forward_arithmetic as forward
from backend.market import market_conditioned_holding as conditioned
from backend.market.joint_funded_policy import (
    MARKET_TIMED_POLICY,
    MarketConditionedTimedFundedPolicy,
)
from backend.tests import test_joint_probability_timing as journey
from backend.tests.test_forward_holding import example_factory, observation, report
from backend.tests.test_joint_funded_policy import report as historical_report
from backend.tests.test_joint_probability_timing import timing as timing


# Publish numeric timing heads and residuals for the next synthetic session.
@pytest.fixture(scope="module")
def forward_timing(example, tmp_path_factory):
    from backend.market import (
        learned_entry_data,
        probabilistic_execution,
        probabilistic_execution_saved,
    )

    panel, prior_close = example[3], example[-1]
    _, exchange = calendar.reviewed_sessions()
    session = np.busday_offset(panel.dates[-1], 1, busdaycal=exchange)
    first = np.busday_offset(
        session.astype("datetime64[M]").astype("datetime64[D]"),
        0,
        roll="forward",
        busdaycal=exchange,
    )
    requested = datetime.combine(
        session.astype(object), datetime.min.time(), calendar.NEW_YORK
    ).replace(hour=8)
    dates, names = panel.dates.copy(), panel.tickers
    rng = np.random.default_rng(721)
    x = rng.uniform(-1, 1, (len(dates), 25, len(names), 21)).astype(np.float32)
    y = np.full((*x.shape[:3], 3), np.nan, dtype=np.float32)
    y[..., 2] = 0.002 * x[..., 0] + rng.normal(0, 0.0004, x.shape[:3])
    y[-10:, ..., 2] = np.nan
    valid = np.ones(x.shape[:3], dtype=bool)
    for day, value in enumerate(dates):
        close = calendar.session_close(value.astype(object))
        slots = ((close.hour - 9) * 60 + close.minute - 30) // 15
        valid[day, slots:] = False
    publication = forward_execution.fit_month(
        {
            "X": x,
            "y": y,
            "valid": valid,
            "dates": dates,
            "feature_names": list(learned_entry_data.FEATURE_NAMES),
            "training_symbols": np.array([True, True, False, False]),
        },
        fit_session=str(first),
        data_as_of=prior_close,
        published_at=requested,
        source_revision="a" * 40,
        input_identity={"cohort": "c" * 64},
    )
    folder = tmp_path_factory.mktemp("full-forward-timing")
    model_sha = forward_execution.write_publication(
        folder / "models", publication, clock=lambda: requested
    )
    # The residual archive ends before the new fit month, as the real archive does.
    dates = dates[dates < first]
    shape = (len(dates), 2, len(names))
    arguments = {
        "dates": dates,
        "symbols": names,
        "means": np.zeros(shape),
        "second_moments": np.full(shape, 0.01),
        "labels": np.broadcast_to(np.array([-0.1, 0.1])[None, :, None], shape).copy(),
        "valid": np.ones(shape, dtype=bool),
        "outcome_end_dates": dates,
        "data_as_of": prior_close,
        "horizon": probabilistic_execution.HORIZON,
    }
    calibrated = probabilistic_execution.calibrate(**arguments)
    saved = probabilistic_execution_saved.load_saved(
        **arguments,
        manifest=calibrated.manifest,
        saved_probability=calibrated.probability_positive,
        saved_quantiles=calibrated.quantiles,
    )
    residuals = forward_execution.prepare_residuals(
        saved,
        fit_session=str(first),
        published_at=requested,
        archive_identity={"cohort": "c" * 64},
        clock=lambda: requested,
    )
    residual_sha = forward_probability_timing.write_residual_month(
        folder / "residuals",
        residuals,
        clock=lambda: requested,
    )
    return folder, model_sha, residual_sha, session


# Train genuine numeric synthetic artifacts once with explicitly valid market inputs.
@pytest.fixture(scope="module")
def example(tmp_path_factory):
    return example_factory(tmp_path_factory, with_market=True)


# Share the authentic original reader across historical and funded-routing acceptance.
@pytest.fixture(scope="module")
def reader(example):
    return example[0]


# Carry genuine sizing and restored timing through durable buys and sells.
@pytest.mark.parametrize("held", [0, 5000])
def test_full_forward_policy_through_restored_timing_and_reconciliation(
    example, forward_timing, tmp_path, monkeypatch, held
):
    from backend.agents.trading.desk import intraday_orders
    from backend.market.replay_broker import ReplayBroker

    # Runtime inference must consume published heads rather than train replacements.
    def forbidden(*args, **kwargs):
        pytest.fail("Published-head inference attempted a base-model fit")

    from backend.market import direct_daily_arithmetic, learned_entry_models

    monkeypatch.setattr(direct_daily_arithmetic, "_fit", forbidden)
    monkeypatch.setattr(learned_entry_models, "_estimator", forbidden)

    # Controlled histories exercise both learned holding-forecast directions.
    panel = deepcopy(example[3])
    for field in ("open", "close", "adj_close", "high", "low"):
        getattr(panel, field)[-1, 0] *= 0.5 if held else 1.5
    current = observation(example, panel=panel)
    chosen = MarketConditionedTimedFundedPolicy(
        forward.ForwardVolatilityHoldingReader(example[0], current), 10
    )
    shown = report(panel, example[4])
    shown.sides = {"AAA": "long", "BBB": "long"}
    shown.scores = example[4].astype(float)
    closing = example[-1]
    prices = {
        name: float(shown.panel.close[-1, i])
        for i, name in enumerate(shown.panel.tickers)
    }
    broker = ReplayBroker(
        100000,
        10,
        initial_holdings={"AAA": held} if held else {},
        initial_average_prices={"AAA": prices["AAA"] * 0.8},
    )
    broker.observe(closing, prices, False)
    entry = market_daily.paper_trade(
        shown,
        tmp_path / "paper",
        str(shown.panel.dates[-1]),
        True,
        client_factory=lambda: broker,
        decision_at=closing,
        feature_reader=journey.features,
        holding_policy=chosen,
    )
    state = paper.load_state(tmp_path / "paper")
    assert state.policy_version == MARKET_TIMED_POLICY
    assert state.allocation_state["receipt"]["scenario"]["status"] == "available"
    assert state.allocation_state["receipt"]["optimizer"]["certificate"]["certified"]
    assert state.allocation_state["receipt"]["company_exits"] == []
    assert shown.graded.grades[-1, 0] == 3
    assert not entry["orders"]
    assert len(state.pending) == 1
    assert current.forecasts[0] < 0 if held else current.forecasts[0] > 0
    intent = state.pending[0]
    side = "sell" if held else "buy"
    assert intent["symbol"] == "AAA"
    assert intent["side"] == side
    assert intent["execution_timing"] == intraday_orders.INTRADAY_TIMING
    assert not broker.attempt_history

    folder, model_sha, residual_sha, session = forward_timing
    opening = datetime.combine(
        session.astype(object), calendar.REGULAR_OPEN, calendar.NEW_YORK
    )
    completed, now = (
        opening + timedelta(minutes=15),
        opening + timedelta(minutes=15, seconds=6),
    )
    residuals = forward_probability_timing.load_residual_month(
        folder / "residuals",
        receipt_sha256=residual_sha,
        observed_at=completed,
    )
    midpoint = prices["AAA"] * (1.2 if held else 0.8)
    prefixes = {
        name: {
            "open": np.array([prices[name]]),
            "high": np.array(
                [max(prices[name], midpoint if name == "AAA" else prices[name])]
            ),
            "low": np.array(
                [min(prices[name], midpoint if name == "AAA" else prices[name])]
            ),
            "close": np.array([midpoint if name == "AAA" else prices[name]]),
            "volume": np.array([1000]),
            "starts": [opening],
            "prior_close": prices[name],
            "published_at": completed + timedelta(seconds=1),
        }
        for name in shown.panel.tickers
    }
    forecast = forward_probability_timing.prepare_forecast(
        shown.panel,
        example[4],
        example[5],
        prefixes,
        observed_at=completed + timedelta(seconds=1),
        daily_as_of=closing,
        model_folder=folder / "models",
        model_receipt_sha256=model_sha,
        residual_month=residuals,
        clock=lambda: completed + timedelta(seconds=2),
    )
    quotes = {
        "quotes": {
            "AAA": {
                "bid": midpoint * 0.999995,
                "ask": midpoint * 1.000005,
                "bid_size": 100,
                "ask_size": 100,
                "last": midpoint,
                "open": prices["AAA"],
                "bar": opening.isoformat(),
                "as_of": (now - timedelta(seconds=1)).isoformat(),
                "received_at": now.isoformat(),
                "feed": "iex",
                "basis": "raw_current_shares",
                "next_open": prices["AAA"],
                "next_open_at": completed.isoformat(),
                "next_open_published_at": (
                    completed + timedelta(seconds=1)
                ).isoformat(),
            }
        }
    }
    broker.observe(now - timedelta(seconds=1), {"AAA": midpoint}, True)
    account = forward_probability_timing.capture_account(
        broker, completed, clock=lambda: now
    )
    trace = []
    timing_reader = forward_probability_timing.build_forecast_reader(
        forecast,
        now,
        quotes,
        state.pending,
        account,
        10,
        trace,
        evidence_root=tmp_path / "paper",
    )
    broker.observe(now, {"AAA": midpoint}, True)
    submitted = intraday_orders.send_due(
        tmp_path / "paper", quotes, now, lambda: broker, timing_reader=timing_reader
    )
    assert len(submitted) == 1, trace
    acknowledged = paper.load_state(tmp_path / "paper")
    assert acknowledged.pending[0]["sent"]["qty"] == intent["qty"]
    assert (
        acknowledged.pending[0]["sent"]["forward_timing"]["receipt"]["inference"][
            "sha256"
        ]
        == forecast.receipt_sha256
    )
    assert len(broker.attempt_history) == 1
    assert not intraday_orders.send_due(
        tmp_path / "paper", quotes, now, lambda: broker, timing_reader=timing_reader
    )
    assert len(broker.attempt_history) == 1
    broker.flush(now, {"AAA": midpoint})
    reconciled, settled = market_daily._reconcile(
        broker, acknowledged, tmp_path / "paper", True
    )
    assert settled
    assert not reconciled.pending
    direction = -1 if held else 1
    assert broker.ledger()["holdings"].get("AAA", 0) == held + direction * intent["qty"]
    expected_cash = (
        100000 - direction * intent["qty"] * midpoint - intent["qty"] * midpoint * 0.001
    )
    assert broker.ledger()["cash"] == pytest.approx(expected_cash)
    assert expected_cash >= 0
    assert not paper.load_state(tmp_path / "paper").pending
    assert paper.load_state(tmp_path / "paper").policy_version == MARKET_TIMED_POLICY


# Independently solve raw regressions and same-date residuals for either current source.
def oracle(reader, current, features, sample):
    bank = reader._frozen_bank
    rows = np.asarray(sample.receipt["decision_indices"])
    market = bank["features"][:, reader.symbols.index("SPY")][:, [1, 5, 4, 12]]
    query_market = features[reader.symbols.index("SPY"), [1, 5, 4, 12]]
    result = []
    for name, proof in zip(sample.symbols, sample.receipt["calibration"], strict=True):
        stock = reader.symbols.index(name)
        selected = np.asarray(proof["selected_indices"])
        observed = bank["labels"][selected, stock]
        train = selected[observed != -1]
        design = np.c_[
            np.ones(len(train)),
            np.log1p(bank["forecasts"][train, stock]),
            market[train],
        ]
        y = np.log1p(bank["labels"][train, stock])
        coef = np.linalg.lstsq(design, y, rcond=None)[0]
        query = np.r_[1, np.log1p(current[stock]), query_market]
        mean = query @ coef
        multiplier = np.sqrt(
            len(train)
            / (len(train) - 6)
            * (1 + query @ np.linalg.inv(design.T @ design) @ query)
        )
        joint_design = np.c_[
            np.ones(len(rows)), np.log1p(bank["forecasts"][rows, stock]), market[rows]
        ]
        values = np.expm1(
            mean
            + (np.log1p(bank["labels"][rows, stock]) - joint_design @ coef)
            * multiplier
            * features[stock, 4]
            / bank["volatility"][rows, stock]
        )
        result.append(values)
    return np.asarray(result).T


# Historical scenarios retain joint dates and match an independent raw oracle.
def test_historical_market_scenarios_and_peer_independence(reader):
    calibrated = conditioned.MarketConditionedHoldingReader(reader)
    day = len(reader.dates) - 2
    sample = calibrated.distribution(day, ("AAA", "BBB"))
    assert sample.receipt["status"] == "available"
    np.testing.assert_allclose(
        sample.scenarios,
        oracle(calibrated, reader.forecasts[day], reader.features[day], sample),
        atol=2e-12,
    )
    parent = reader.distribution(day, sample.symbols)
    assert sample.receipt["decision_indices"] == parent.receipt["decision_indices"]
    np.testing.assert_array_equal(sample.probabilities, parent.probabilities)
    reverse = calibrated.distribution(day, ("BBB", "AAA"))
    np.testing.assert_array_equal(sample.scenarios, reverse.scenarios[:, ::-1])
    assert len(calibrated._fits) == 2
    assert not sample.scenarios.flags.writeable


# Published forward context follows the identical raw oracle and actual expiry guards.
def test_forward_market_scenarios_publication_and_report(example):
    current = observation(example)
    parent = forward.ForwardVolatilityHoldingReader(example[0], current)
    reader = conditioned.ForwardMarketConditionedHoldingReader(parent)
    reader.validate_clock(example[-1])
    reader.validate_report(report(example[3], example[4]))
    sample = reader.distribution(len(reader.dates) - 1, ("AAA", "BBB"))
    assert sample.receipt["status"] == "available"
    np.testing.assert_allclose(
        sample.scenarios,
        oracle(reader, current.forecasts, current.features, sample),
        atol=2e-12,
    )
    assert (
        sample.receipt["current_context"] == current.features[2, [1, 5, 4, 12]].tolist()
    )
    with pytest.raises(ValueError, match="Completed close"):
        reader.validate_clock(example[-1] + timedelta(days=4))
    wrong = report(deepcopy(example[3]), example[4].copy())
    wrong.panel.adj_close[-1, 0] += 1
    with pytest.raises(ValueError, match="prices"):
        reader.validate_report(wrong)


# A changed original feature buffer cannot masquerade as the admitted source artifact.
@pytest.mark.parametrize("forward_path", [False, True])
def test_tampered_original_context_refused(example, forward_path):
    original = deepcopy(example[0])
    original.features = original.features.copy()
    original.features[-1, 2, 1] += 0.1
    if forward_path:
        with pytest.raises(ValueError, match="binding"):
            forward.ForwardVolatilityHoldingReader(original, observation(example))
    else:
        with pytest.raises(ValueError, match="binding"):
            conditioned.MarketConditionedHoldingReader(original)


# Caller mutations after admission cannot revise coefficients or current scenarios.
def test_reader_detaches_buffers_and_future_outcomes(reader):
    original = deepcopy(reader)
    calibrated = conditioned.MarketConditionedHoldingReader(original)
    day = len(reader.dates) - 50
    first = calibrated.distribution(day, ("AAA",))
    assert first.receipt["status"] == "available"
    original.features = np.full_like(original.features, np.nan)
    original.labels = np.full_like(original.labels, np.nan)
    second = calibrated.distribution(day, ("AAA",))
    np.testing.assert_array_equal(first.scenarios, second.scenarios)
    changed = conditioned.MarketConditionedHoldingReader(reader)
    changed._frozen_bank["labels"] = changed._frozen_bank["labels"].copy()
    changed._frozen_bank["labels"][day:] = -1
    third = changed.distribution(day, ("AAA",))
    np.testing.assert_array_equal(first.scenarios, third.scenarios)
    assert first.receipt["calibration"] == third.receipt["calibration"]


# Unknown holdings stay unavailable rather than being silently removed from the book.
@pytest.mark.parametrize("symbols", [("AAA", "UNSEEN"), ("SPY",)])
def test_missing_required_context_remains_unavailable(reader, symbols):
    sample = conditioned.MarketConditionedHoldingReader(reader).distribution(
        len(reader.dates) - 1, symbols
    )
    assert sample.scenarios is None
    assert sample.receipt["status"] == "unavailable"


# The private policy preserves authentic scenarios and refuses other wrappers.
def test_named_policy_selects_only_authentic_market_reader(reader):
    policy = MarketConditionedTimedFundedPolicy(reader, 10)
    assert policy.version == MARKET_TIMED_POLICY
    assert policy.identity["adoption_eligible"] is False
    assert isinstance(policy.reader, conditioned.MarketConditionedHoldingReader)
    assert (
        policy.reader.distribution(len(reader.dates) - 2, ("AAA",)).receipt["status"]
        == "available"
    )
    from backend.market.conditional_holding_calibration import CalibratedHoldingReader

    with pytest.raises(ValueError, match="authentic"):
        MarketConditionedTimedFundedPolicy(CalibratedHoldingReader(reader), 10)


# Exercise intent persistence, buy/profit timing and cash with a routing oracle.
@pytest.mark.parametrize("positive", [True, False])
def test_private_funded_timing_journey(reader, timing, tmp_path, monkeypatch, positive):
    monkeypatch.setattr(
        journey, "ProbabilityTimedFundedPolicy", MarketConditionedTimedFundedPolicy
    )
    chosen, _, broker, entry, _ = journey.planned(
        tmp_path,
        reader,
        monkeypatch,
        positive=positive,
        held={} if positive else {"AAA": 10},
    )
    pending = paper.load_state(tmp_path).pending
    assert pending[0]["side"] == ("buy" if positive else "sell")
    assert pending[0]["qty"] == (250 if positive else 10)
    assert entry["execution_rule"] == chosen.timing_policy
    if positive:
        _, trace, state, _ = journey.observe(tmp_path, reader, timing, broker)
        assert trace[0]["state"] == "wait"
        assert "sent" not in state.pending[0]
    now, trace, state, _ = journey.observe(
        tmp_path, reader, timing, broker, clock=1 if positive else 0, price=100
    )
    assert trace[0]["state"] == "execute"
    quantity = pending[0]["qty"]
    broker.flush(now, {"AAA": 101.0})
    reconciled, settled = market_daily._reconcile(broker, state, tmp_path, True)
    assert settled
    assert not reconciled.pending
    assert broker.ledger()["cash"] == pytest.approx(
        100000 + (-quantity * 101 * 1.001 if positive else quantity * 101 * 0.999)
    )
    assert paper.load_state(tmp_path).policy_version == MARKET_TIMED_POLICY


# Genuine fitted scenarios reach whole-share planning without borrowing sale proceeds.
def test_actual_learned_plan_preserves_funding_and_repeat_identity(reader):
    policy = MarketConditionedTimedFundedPolicy(reader, 10)
    current = historical_report(reader, grades=(3, 3))
    session = str(current.panel.dates[-1])
    orders, state, _ = policy.plan(
        session,
        paper.PaperState(),
        1100,
        {"BBB": 10},
        {"AAA": 100, "BBB": 100},
        current,
        100,
        set(),
    )
    receipt = state.allocation_state["receipt"]
    assert receipt["scenario"]["status"] == "available"
    assert receipt["scenario"]["policy"] == conditioned.POLICY
    assert (
        sum(order.qty * 100 * 1.001 for order in orders if order.side == "buy") <= 100
    )
    assert all(order.qty <= 10 for order in orders if order.side == "sell")
    again, _, why = policy.plan(
        session, state, 1100, {"BBB": 10}, {"AAA": 100, "BBB": 100}, current, 100, set()
    )
    assert again == []
    assert why == "already planned for this session"


# Mandatory grade exits retain next-open treatment without discretionary delay.
def test_company_exit_retains_immediate_contract(reader):
    policy = MarketConditionedTimedFundedPolicy(reader, 10)
    current = historical_report(reader, grades=(0, 0))
    orders, state, _ = policy.plan(
        str(current.panel.dates[-1]),
        paper.PaperState(),
        1100,
        {"AAA": 10},
        {"AAA": 100},
        current,
        100,
        set(),
    )
    assert len(orders) == 1
    assert orders[0].side == "sell"
    assert orders[0].qty == 10
    assert orders[0].execution_timing == "next_open"
    assert state.allocation_state["receipt"]["company_exits"] == ["AAA"]


# Original numeric arrays cannot be changed independently of their admitted artifact.
@pytest.mark.parametrize(
    "field", ["volatility", "forecasts", "labels", "endpoints", "support"]
)
def test_altered_original_numeric_binding_is_refused(reader, field):
    changed = deepcopy(reader)
    value = getattr(changed, field).copy()
    value.flat[0] = (
        not value.flat[0]
        if field == "support"
        else np.datetime64("2000-01-03", "D")
        if value.dtype.kind == "M"
        else 0
    )
    setattr(changed, field, value)
    with pytest.raises(ValueError, match="binding"):
        conditioned.MarketConditionedHoldingReader(changed)


# Unsupported current market domains remain explicit missing opportunities.
def test_invalid_current_market_context_is_unavailable(reader):
    calibrated = conditioned.MarketConditionedHoldingReader(reader)
    day = len(reader.dates) - 2
    values = calibrated._frozen_bank["features"].copy()
    values[day, 2, 12] = 2
    calibrated._frozen_bank["features"] = values
    sample = calibrated.distribution(day, ("AAA",))
    assert sample.scenarios is None
    assert sample.receipt["reason"] == "unsupported_market_calibration"
    assert "possible declared market context" in sample.receipt["calibration_reason"]


# An explicit synthetic default retains its same-date mass in the scenario transform.
def test_default_row_preserved_in_synthetic_residual_bank(reader):
    calibrated = conditioned.MarketConditionedHoldingReader(reader)
    day = len(reader.dates) - 2
    rows = np.asarray(reader.distribution(day, ("AAA",)).receipt["decision_indices"])
    values = calibrated._frozen_bank["labels"].copy()
    values[rows[7], 0] = -1
    calibrated._frozen_bank["labels"] = values
    sample = calibrated.distribution(day, ("AAA",))
    assert sample.receipt["status"] == "available"
    assert sample.scenarios[7, 0] == -1
    assert np.count_nonzero(sample.scenarios == -1) == 1
    assert sample.receipt["calibration"][0]["defaults"] == 1
