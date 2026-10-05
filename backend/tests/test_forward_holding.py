"""Current close, original joint errors and real funded shadow policy acceptance."""

import builtins
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import grading, paper
from backend.cli import market_daily
from backend.market import calendar as exchange
from backend.market import direct_error_band as errors
from backend.market import forward_arithmetic as forward
from backend.market import learned_entry_data
from backend.market import learned_retention_models as context
from backend.market.joint_funded_policy import JointFundedPolicy, MaturityFundedPolicy
from backend.market.panel import Panel
from backend.market.replay_broker import ReplayBroker
from backend.tests.test_direct_feature_arithmetic import risk_example_factory


# Fit original synthetic evidence once and append one actual reviewed session.
@pytest.fixture(scope="module")
def example(tmp_path_factory):
    prepared, bridge, parent, _, risk = risk_example_factory(
        tmp_path_factory, with_volatility=True
    )
    original = errors.VolatilityHoldingReader(risk, bridge)
    month = prepared["dates"][-1].astype("datetime64[M]")
    _, calendar = exchange.reviewed_sessions()
    fit = np.busday_offset(
        month.astype("datetime64[D]"), 0, roll="forward", busdaycal=calendar
    )
    at = datetime.combine(
        prepared["dates"][-1].astype(object),
        exchange.session_close(prepared["dates"][-1].astype(object)),
        exchange.NEW_YORK,
    ) + timedelta(minutes=1)
    values = np.full(risk.prices.shape, 2)
    values[:, 1] = -1
    eligible = values >= 0
    publication = forward.fit_month(
        prepared,
        bridge,
        values,
        eligible,
        fit_session=str(fit),
        published_at=at,
        source_revision="a" * 40,
        input_identity={"original": "b" * 64},
    )
    folder = tmp_path_factory.mktemp("forward-publisher") / "model"
    digest = forward.write_publication(folder, publication, clock=lambda: at)
    last = np.busday_offset(prepared["dates"][-1], 1, busdaycal=calendar)
    dates = np.append(prepared["dates"], last)
    index = np.arange(len(dates))[:, None]
    prices = 100 * np.exp(
        index * [0.0003, 0.0001, 0.0002, 0.0002] + 0.02 * np.sin(index / [5, 7, 9, 11])
    )
    panel = Panel(
        dates,
        risk.symbols,
        prices.copy(),
        prices + 1,
        prices - 1,
        prices.copy(),
        prices.copy(),
        np.ones(prices.shape),
        {},
        "SPY",
    )
    grades = np.vstack((values, [3, 0, 0, 0]))
    membership = np.vstack((eligible, [True, True, True, True]))
    now = datetime.combine(
        last.astype(object),
        exchange.session_close(last.astype(object)),
        exchange.NEW_YORK,
    ) + timedelta(minutes=1)
    provenance = {"data_as_of": now.isoformat(), "basis": "synthetic_adjusted"}
    return original, folder, digest, panel, grades, membership, provenance, now


# Generate current inference by the real completed-prefix feature and numeric paths.
def observation(example, *, panel=None, at=None):
    _, folder, digest, source, grades, membership, provenance, now = example
    return forward.observe_close(
        panel or source,
        grades,
        membership,
        provenance,
        folder,
        model_receipt_sha256=digest,
        observed_at=at or now,
    )


# Adapt the same current grades and exact panel to the real funding planner.
def report(panel, grades):
    return SimpleNamespace(
        panel=panel, graded=grading.Graded(grades, grades.astype(float), {})
    )


# Extracted features preserve the original sentinel and benchmark support.
def test_completed_feature_extraction_preserves_exact_original_context(example):
    _, _, _, panel, grades, membership, provenance, _ = example
    result = context.completed_features(
        panel, grades, membership, panel.dates, provenance
    )
    stock = np.array([name not in ("SPY", "QQQ") for name in panel.tickers])
    expected, available = learned_entry_data._daily_context(
        np.vstack((panel.adj_close, np.full(4, np.nan))),
        np.vstack((grades, [-1] * 4)),
        np.vstack((membership & stock, np.zeros(4, dtype=bool))),
        2,
    )
    np.testing.assert_array_equal(result["X"], expected[1:])
    np.testing.assert_array_equal(result["available"], available[1:])
    legacy = context.prepare(panel, grades, membership, panel.dates, provenance)
    np.testing.assert_array_equal(legacy["spy_valid"], available[1:, 2])
    assert legacy["spy_valid"][-1]


# Current stock distributions use the exact original simultaneous bank and transform.
def test_current_joint_risk_matches_independent_bank_arithmetic(example):
    original = example[0]
    current = observation(example)
    reader = forward.ForwardVolatilityHoldingReader(original, current)
    sample = reader.distribution(len(reader.dates) - 1, ("AAA", "BBB"))
    assert sample.receipt["status"] == "available"
    chosen = np.asarray(sample.receipt["decision_indices"])
    expected = errors.scale_holding_volatility(
        current.forecasts[:2],
        original.forecasts[chosen, :2],
        original.labels[chosen, :2],
        current.features[:2, 4],
        original.volatility[chosen, :2],
    )
    np.testing.assert_array_equal(sample.scenarios, expected)
    np.testing.assert_array_equal(
        sample.probabilities, np.full(len(chosen), 1 / len(chosen))
    )
    assert len(chosen) >= 252
    assert not sample.scenarios.flags.writeable
    assert reader.identity["adoption_eligible"] is False


# Inference and saved loading never call a training producer or restore pickle.
def test_close_reload_preserves_predictions_without_refitting(
    example, tmp_path, monkeypatch
):
    current = observation(example)

    # Reload may traverse numeric trees but cannot invoke the estimator fitting path.
    def forbidden(*args, **kwargs):
        pytest.fail("Current observation attempted training")

    monkeypatch.setattr(forward.direct, "_fit", forbidden)
    output = tmp_path / "close"
    digest = forward.write_close(output, current, clock=lambda: example[-1])
    reopened = forward.load_close(
        output, example[1], receipt_sha256=digest, observed_at=example[-1]
    )
    np.testing.assert_array_equal(reopened.forecasts, current.forecasts)
    assert not reopened.features.flags.writeable
    assert reopened.receipt["identity"]["model_publication_sha256"] == example[2]


# A current read cannot use an unfinished close or an already passed next-open target.
@pytest.mark.parametrize("offset", [timedelta(minutes=-2), timedelta(days=5)])
def test_unfinished_or_expired_close_refused(example, offset):
    with pytest.raises(ValueError, match="publication|Completed close|Current causal"):
        observation(example, at=example[-1] + offset)


# Unknown history remains unavailable rather than silently dropping a required holding.
@pytest.mark.parametrize("symbol", ["UNSEEN", "SPY"])
def test_required_stock_missing_is_explicit(example, symbol):
    current = observation(example)
    reader = forward.ForwardVolatilityHoldingReader(example[0], current)
    result = reader.distribution(len(reader.dates) - 1, ("AAA", symbol))
    assert result.scenarios is None
    assert result.receipt["reason"] == "uncovered_required_stock"


# Caller changes after admission cannot revise the dated bank or current means.
def test_forward_reader_freezes_current_and_original_inputs(example):
    original, current = deepcopy(example[0]), observation(example)
    reader = forward.ForwardVolatilityHoldingReader(original, current)
    first = reader.distribution(len(reader.dates) - 1, ("AAA",))
    original.forecasts = np.zeros_like(original.forecasts)
    current.forecasts[:] = np.nan
    second = reader.distribution(len(reader.dates) - 1, ("AAA",))
    np.testing.assert_array_equal(first.scenarios, second.scenarios)


# Changed grades or prices cannot reach funding through stale inference.
@pytest.mark.parametrize("field", ["grades", "prices"])
def test_funded_report_must_match_current_forecast(example, field):
    current = observation(example)
    reader = forward.ForwardVolatilityHoldingReader(example[0], current)
    panel, grades = deepcopy(example[3]), example[4].copy()
    if field == "grades":
        grades[-1, 0] = 1
    else:
        panel.adj_close[-1, 0] *= 1.01
    with pytest.raises(ValueError, match="Funded report differs"):
        JointFundedPolicy(reader, 10).decide(
            str(panel.dates[-1]),
            report(panel, grades),
            10000,
            {},
            {"AAA": 100},
            10000,
            set(),
        )


# Learned current risk reaches the existing whole-share and actual-cash planner.
def test_current_forecast_drives_funded_shadow_plan(example):
    current = observation(example)
    reader = forward.ForwardVolatilityHoldingReader(example[0], current)
    panel, grades = example[3:5]
    orders, state, _ = JointFundedPolicy(reader, 0).plan(
        str(panel.dates[-1]),
        paper.PaperState(),
        10000,
        {},
        {"AAA": float(panel.adj_close[-1, 0])},
        report(panel, grades),
        10000,
        set(),
    )
    receipt = state.allocation_state["receipt"]
    assert receipt["scenario"]["policy"] == "forward-joint-holding-volatility/1-shadow"
    assert receipt["optimizer"]["certificate"]["certified"]
    assert (
        sum(
            order.qty * panel.adj_close[-1, panel.index(order.symbol)]
            for order in orders
            if order.side == "buy"
        )
        <= 10000
    )
    assert all(
        order.execution_timing == "next_open" and order.qty % 1 == 0 for order in orders
    )


# A declared share conversion and eligible subset preserve the actual nightly report.
def test_filtered_raw_share_report_is_explicitly_compatible(example):
    current = observation(example)
    reader = forward.ForwardVolatilityHoldingReader(example[0], current)
    source = example[3]
    columns, factors = [0, 2], np.array([10.0, 1.0])
    panel = Panel(
        source.dates,
        ("AAA", "SPY"),
        *(
            getattr(source, key)[:, columns] * factors
            for key in ("open", "high", "low", "close", "adj_close", "volume")
        ),
        {},
        "SPY",
    )
    item = report(panel, example[4][:, columns].copy())
    item.provenance = {
        "price_basis": "entire_prefix_in_current_session_raw_share_dollars",
        "split_factors": {"AAA": 10.0, "SPY": 1.0},
        "raw_source_arrays": {
            "adj_close": current.receipt["identity"]["prefix_sha256"]["prices"]
        },
    }
    reader.validate_report(item)
    item.provenance["split_factors"]["AAA"] = 9.0
    with pytest.raises(ValueError, match="published current close: prices"):
        reader.validate_report(item)


# Cached current inference cannot be submitted after its target opening has passed.
def test_forward_clock_expires_at_next_open(example):
    current = observation(example)
    reader = forward.ForwardVolatilityHoldingReader(example[0], current)
    deadline = datetime.fromisoformat(current.receipt["identity"]["expires_at"])
    reader.validate_clock(deadline - timedelta(microseconds=1))
    with pytest.raises(ValueError, match="Completed close"):
        reader.validate_clock(deadline)


# An altered old input cannot impersonate the authenticated frozen risk bank.
def test_changed_original_bank_refused_before_decisions(example):
    original = deepcopy(example[0])
    original.forecasts = np.zeros_like(original.forecasts)
    with pytest.raises(ValueError, match="Original reader numeric"):
        forward.ForwardVolatilityHoldingReader(original, observation(example))


# A negative learned holding forecast can sell an A+ position through the real planner.
def test_learned_exit_does_not_need_a_grade_downgrade(example):
    panel = deepcopy(example[3])
    for key in ("open", "close", "adj_close", "high", "low"):
        getattr(panel, key)[-1, 0] *= 0.5
    current = observation(example, panel=panel)
    reader = forward.ForwardVolatilityHoldingReader(example[0], current)
    price = float(panel.adj_close[-1, 0])
    orders, state, _ = JointFundedPolicy(reader, 0).plan(
        str(panel.dates[-1]),
        paper.PaperState(),
        500 * price,
        {"AAA": 100},
        {"AAA": price},
        report(panel, example[4]),
        400 * price,
        set(),
    )
    receipt = state.allocation_state["receipt"]
    assert example[4][-1, 0] == 3
    assert receipt["company_exits"] == []
    assert receipt["optimizer"]["certificate"]["certified"]
    assert current.forecasts[0] < 0
    assert receipt["targets"]["AAA"] == 0.0
    assert any(order.symbol == "AAA" and order.side == "sell" for order in orders)


# Month-end inference lasts until next open, never for the new month's close.
def test_model_month_follows_decision_session_not_midnight(tmp_path):
    from backend.tests.test_forward_arithmetic import inputs, publish, save

    original = publish(inputs())
    output = tmp_path / "model"
    digest = save(output, original)
    head, _ = forward.load_publication(
        output,
        receipt_sha256=digest,
        observed_at="2025-05-01T09:29:59-04:00",
        decision_session="2025-04-30",
    )
    assert head is not None
    with pytest.raises(ValueError, match="Completed close"):
        forward.load_publication(
            output,
            receipt_sha256=digest,
            observed_at="2025-05-01T09:30:00-04:00",
            decision_session="2025-04-30",
        )


# Reviewed early closes and holidays define the real signal availability window.
def test_close_window_honors_early_close_and_holiday():
    day = np.datetime64("2017-07-03", "D")
    close, opening = forward._close_window(day, "2017-07-03T13:00:00-04:00")
    assert close.hour == 13
    assert opening.isoformat() == "2017-07-05T09:30:00-04:00"
    with pytest.raises(ValueError, match="Completed close"):
        forward._close_window(day, "2017-07-03T12:59:59-04:00")


# A valid current forecast can persist a private decision after midnight before open.
@pytest.mark.parametrize("learned_exit", [False, True])
@pytest.mark.parametrize("policy_type", [JointFundedPolicy, MaturityFundedPolicy])
def test_actual_private_forward_decision_survives_midnight(
    example, tmp_path, learned_exit, policy_type
):
    panel = deepcopy(example[3])
    if learned_exit:
        for key in ("open", "close", "adj_close", "high", "low"):
            getattr(panel, key)[-1, 0] *= 0.5
    current = observation(example, panel=panel)
    reader = forward.ForwardVolatilityHoldingReader(example[0], current)
    grades = example[4]
    shown = report(panel, grades)
    shown.sides = {"AAA": "long", "BBB": "long"}
    shown.scores = grades.astype(float)
    deadline = datetime.fromisoformat(current.receipt["identity"]["expires_at"])
    now = deadline.replace(hour=1, minute=0)
    assert now.date() > panel.dates[-1].astype(object)
    reader.validate_clock(now)
    broker = ReplayBroker(
        100000.0,
        10,
        initial_holdings={"AAA": 100} if learned_exit else {},
        initial_average_prices={"AAA": float(panel.close[-1, 0]) * 0.8},
    )
    prices = {s: float(panel.close[-1, i]) for i, s in enumerate(panel.tickers)}
    broker.observe(now, prices, False)

    # Reuse the ordinary private event and price-permission input contract.
    def features(kind, ignored):
        return (
            {"calendar_known": True, "factor": 1.0}
            if kind == "event"
            else (set(), {})
            if kind == "blocked"
            else {}
        )

    args = dict(
        client_factory=lambda: broker,
        decision_at=now,
        feature_reader=features,
        holding_policy=policy_type(reader, 10),
    )
    session = str(panel.dates[-1])
    entry = market_daily.paper_trade(shown, tmp_path, session, True, **args)
    saved = paper.load_state(tmp_path)
    assert entry["policy"] == args["holding_policy"].version
    assert saved.policy_version == entry["policy"]
    assert saved.allocation_state["receipt"]["scenario"]["status"] == "available"
    assert session in saved.sessions_seen
    attempts = broker.attempt_history
    repeated = market_daily.paper_trade(shown, tmp_path, session, True, **args)
    assert broker.attempt_history == attempts
    assert paper.load_state(tmp_path).pending == saved.pending
    assert broker.account().cash == 100000.0
    for row in repeated["actions"]:
        assert row["decision_source"] == (
            "settlement_or_event_priority" if saved.pending else policy_type.version
        )
        assert row["action"] == "hold"
        assert row["action_status"] == "no_new_order"
        if saved.pending:
            assert row["model_target_weight"] is None
    assert entry["until_rebalance"] is None
    for row in entry["actions"]:
        assert row["until_rebalance"] is None
        assert row["stops"] == {}
        assert row["leaves_if"] == "Company exit or risk-adjusted allocation"
        assert row["action_status"] in {"planned", "no_new_order"}
        assert row["is_fill"] is False
    if learned_exit:
        receipt = saved.allocation_state["receipt"]
        assert grades[-1, 0] == 3
        assert current.forecasts[0] < 0
        assert receipt["company_exits"] == []
        assert receipt["targets"]["AAA"] == 0
        assert any(
            row["symbol"] == "AAA" and row["side"] == "sell" for row in entry["orders"]
        )
        action = next(row for row in entry["actions"] if row["ticker"] == "AAA")
        assert action["action"] == "sell"
        assert action["order_quantity"] == 100
        assert action["delta_weight"] == -action["current_weight"]
        assert broker.positions()[0].qty == 100
        broker.observe(deadline, prices, True)
        broker.flush(deadline, prices, phase="open")
        reconciled, settled = market_daily._reconcile(broker, saved, tmp_path, True)
        assert settled
        assert not reconciled.pending
        assert not broker.positions()
        assert broker.account().cash == pytest.approx(
            100000.0 + 100 * prices["AAA"] * 0.999
        )
        assert paper.load_state(tmp_path).journal == reconciled.journal


# A forward takeover preserves an unsent future plan through real private persistence.
def test_forward_takeover_preserves_future_unsent_intent(example, tmp_path):
    current = observation(example)
    reader = forward.ForwardVolatilityHoldingReader(example[0], current)
    panel, grades = example[3], example[4]
    shown = report(panel, grades)
    shown.sides = {"AAA": "long", "BBB": "long"}
    shown.scores = grades.astype(float)
    deadline = datetime.fromisoformat(current.receipt["identity"]["expires_at"])
    now = deadline.replace(hour=1, minute=0)
    session = str(panel.dates[-1])
    row = {
        "client_order_id": "existing-future-intent",
        "symbol": "AAA",
        "side": "buy",
        "qty": 2,
        "session": session,
        "execute_on": deadline.date().isoformat(),
        "execution_timing": "dip_or_close",
    }
    paper.save_state(tmp_path, paper.PaperState(pending=[row]))
    broker = ReplayBroker(100000.0, 10)
    broker.observe(
        now, {s: float(panel.close[-1, i]) for i, s in enumerate(panel.tickers)}, False
    )

    # Keep the current event and entry permissions without bypassing real dispatch.
    def features(kind, ignored):
        return (
            {"calendar_known": True, "factor": 1.0}
            if kind == "event"
            else (set(), {})
            if kind == "blocked"
            else {}
        )

    args = dict(
        client_factory=lambda: broker,
        decision_at=now,
        feature_reader=features,
        holding_policy=MaturityFundedPolicy(reader, 10),
    )
    for _ in range(2):
        entry = market_daily.paper_trade(shown, tmp_path, session, True, **args)
        saved = paper.load_state(tmp_path)
        assert saved.pending == [row]
        assert not saved.journal
        assert entry["orders"] == []
        assert not broker.attempt_history
        assert broker.account().cash == 100000.0
        assert all(action["model_target_weight"] is None for action in entry["actions"])


# Expired forward rows fail before any private account persistence or order attempt.
def test_actual_private_forward_expiry_has_no_side_effect(example, tmp_path):
    current = observation(example)
    reader = forward.ForwardVolatilityHoldingReader(example[0], current)
    deadline = datetime.fromisoformat(current.receipt["identity"]["expires_at"])
    broker = ReplayBroker(100000.0, 10)
    broker.observe(deadline, {"AAA": 100.0}, True)
    with pytest.raises(ValueError, match="Completed close|Nightly decision"):
        market_daily.paper_trade(
            report(example[3], example[4]),
            tmp_path,
            str(example[3].dates[-1]),
            True,
            client_factory=lambda: broker,
            decision_at=deadline,
            holding_policy=JointFundedPolicy(reader, 10),
        )
    assert not broker.attempt_history
    assert not list(tmp_path.iterdir())


# An ordinary decision cannot depend on the optional learned forecasting imports.
def test_default_close_window_does_not_import_research(monkeypatch):
    original = builtins.__import__

    # Reproduce an installation that does not provide the optional research stack.
    def without_research(name, *args, **kwargs):
        if name == "backend.market.forward_arithmetic":
            raise ModuleNotFoundError("Optional research is unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_research)
    assert market_daily._forward_close_window(None, None, None) is False


# Small funded orders remain actions and unfunded targets remain holds.
def test_candidate_action_rows_follow_actual_whole_share_orders():
    from backend.agents.trading.desk import actions

    rows = [
        {
            "ticker": name,
            "action": "hold",
            "target_weight": target,
            "current_weight": held,
            "delta_weight": target - held,
            "last_close": 100,
            "reason": "Company evidence",
        }
        for name, target, held in (
            ("AAA", 0.1001, 0.1),
            ("BBB", 0.05, 0.1),
            ("CCC", 0.09, 0),
        )
    ]
    original = deepcopy(rows)
    holdings = {name: actions.Holding(0.1) for name in ("AAA", "BBB")}
    orders = [
        paper.PaperOrder("AAA", "buy", 1, "joint net-growth allocation"),
        paper.PaperOrder("BBB", "sell", 1, "joint net-growth allocation"),
    ]
    result = market_daily._holding_actions(
        SimpleNamespace(version="private-candidate"),
        rows,
        orders,
        holdings,
        {"AAA": 100, "BBB": 100},
        {"AAA": 100, "BBB": 100},
        100000,
        False,
    )
    by_name = {row["ticker"]: row for row in result}
    assert by_name["AAA"]["action"] == "add"
    assert by_name["AAA"]["delta_weight"] == 0.001
    assert by_name["AAA"]["target_weight"] == 0.101
    assert by_name["BBB"]["action"] == "trim"
    assert by_name["BBB"]["delta_weight"] == -0.001
    assert by_name["CCC"]["action"] == "hold"
    assert by_name["CCC"]["target_weight"] == 0
    assert by_name["CCC"]["model_target_weight"] == 0.09
    assert rows == original
    assert (
        market_daily._holding_actions(
            None, rows, orders, holdings, {}, {}, 100000, False
        )
        is rows
    )


# A mismatched price report is refused before ledger effects or durable planning.
def test_actual_private_forward_report_mismatch_has_no_side_effect(example, tmp_path):
    current = observation(example)
    reader = forward.ForwardVolatilityHoldingReader(example[0], current)
    now = example[-1]
    broker = ReplayBroker(100000.0, 10)
    broker.observe(now, {"AAA": 100.0}, False)
    panel = deepcopy(example[3])
    panel.adj_close[-1, 0] += 1
    with pytest.raises(ValueError, match="published current close: prices"):
        market_daily.paper_trade(
            report(panel, example[4]),
            tmp_path,
            str(panel.dates[-1]),
            True,
            client_factory=lambda: broker,
            decision_at=now,
            holding_policy=JointFundedPolicy(reader, 10),
        )
    assert not broker.attempt_history
    assert not list(tmp_path.iterdir())
