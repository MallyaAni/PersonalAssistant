"""Selective proposals and locks under actual unchanged /4 account execution."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import policy_v4, simulate
from backend.market import profit_taking
from backend.market import selective_action_execution as execution
from backend.market.daily_action_model import build_dataset
from backend.market.simulator_checkpoint import ResearchContext
from backend.tests.funded_simulator_fixtures import _report


# Supply only a current planning boundary, with no future outcomes in scope.
def _context(**changes):
    fields = dict(
        t=5,
        session="2024-01-06",
        symbols=("AAA", "BBB", "SPY"),
        prices=np.array([10.0, 10.0, 10.0]),
        held_units=np.array([1.0, 0.0, 0.0]),
        cash=90.0,
        nav=100.0,
        incumbent_units=np.array([1.0, 0.0, 0.0]),
        buy_allowed=np.array([True, True, False]),
        current_targets=np.array([0.1, 0.1, 0.0]),
        opened=np.array([1, -1, -1]),
        last_rebalance=0,
        next_rebalance=20,
        rebalanced=False,
        cost_bps=25.0,
    )
    fields.update(changes)
    return ResearchContext(**fields)


# Build current synthetic daily features with a known momentum spread.
def _features(names=3, spread=0.1):
    rows = np.zeros((names, 22))
    rows[:, 2] = spread
    return rows


# Wrap synthetic current feature rows in the same daily-data boundary as production.
def _daily(rows=50, names=3, spread=0.1):
    stock = [f"stock_log_return_{value}" for value in (1, 5, 20, 60)]
    other = [f"stock_extra_{value}" for value in range(8)]
    names_ = tuple(
        stock
        + other
        + [
            f"{name}_{suffix}"
            for name in ("spy", "qqq")
            for suffix in (
                "log_return_1",
                "log_return_5",
                "log_return_20",
                "log_return_60",
                "volatility_20",
            )
        ]
    )
    return SimpleNamespace(
        dates=np.arange(
            np.datetime64("2024-01-01"),
            np.datetime64("2024-01-01") + np.timedelta64(rows, "D"),
        ),
        tickers=("AAA", "BBB", "SPY"),
        features=np.broadcast_to(_features(names, spread), (rows, names, 22)).copy(),
        feature_names=names_,
    )


# Count actual held units reconstructed by the independent journal verifier.
def _positions(priced):
    return np.asarray([row["positions"] for row in priced.verification["marks"]])


# Pin lexical ordering, current-state features and the exact registered unit deltas.
def test_candidates_are_sorted_current_and_holdings_aware():
    ctx = _context()
    got = execution.candidates(ctx, _features())
    assert [(row.symbol, row.action) for row in got] == [
        ("AAA", "Add"),
        ("AAA", "Sell"),
        ("AAA", "Trim"),
        ("BBB", "Buy"),
    ]
    add, sell, trim, buy = got
    assert add.units == pytest.approx(1.2)
    assert sell.units == 0
    assert trim.units == 0.5
    assert buy.units == pytest.approx(0.2)
    np.testing.assert_allclose(add.features[22:29], [0.1, 0.9, 0, 4, 15, 0.02, 0.1])
    np.testing.assert_array_equal(add.features[-4:], [0, 1, 0, 0])
    assert not add.features.flags.writeable


# An incumbent buy budget includes its fees and never treats future sells as cash.
def test_add_cash_reservation_includes_every_incumbent_buy_and_fees():
    ctx = _context(incumbent_units=np.array([1.0, 3.0, 0.0]), cash=31.0)
    got = execution.candidates(ctx, _features())
    add = next(row for row in got if row.action == "Add")
    reserved = 3 * 10 * 1.0025
    assert (add.units - 1) * 10 * 1.0025 + reserved == pytest.approx(31.0)
    assert add.incremental_weight < 0.02
    empty = replace(ctx, cash=reserved + 0.1)
    assert all(
        row.action not in ("Add", "Buy")
        for row in execution.candidates(empty, _features())
    )


# Buy blocks and the position ceiling never suppress a currently held risk reduction.
def test_buy_gate_cap_and_incumbent_sell_are_preserved():
    capped = _context(
        incumbent_units=np.array([2.0, 0.0, 0.0]),
        buy_allowed=np.array([True, False, False]),
    )
    assert {row.action for row in execution.candidates(capped, _features())} == {
        "Sell",
        "Trim",
    }
    stronger = _context(
        incumbent_units=np.array([0.4, 0.0, 0.0]), buy_allowed=np.zeros(3, bool)
    )
    assert [row.action for row in execution.candidates(stronger, _features())] == [
        "Sell"
    ]
    closed = replace(stronger, incumbent_units=np.zeros(3))
    assert execution.candidates(closed, _features()) == []


# Future endpoint availability is absent, while missing present prices/features block.
def test_present_missingness_and_trade_floor_do_not_consume_future_information():
    ctx = _context(
        held_units=np.array([0.01, 0, 0]),
        incumbent_units=np.array([0.01, 0, 0]),
        buy_allowed=np.zeros(3, bool),
    )
    assert execution.candidates(ctx, _features()) == []
    feature = _features()
    feature[0, 0] = np.nan
    assert [row.symbol for row in execution.candidates(_context(), feature)] == ["BBB"]
    ctx = _context(
        prices=np.array([10.0, np.nan, 10.0]), incumbent_units=np.array([1.0, 1.0, 0.0])
    )
    assert all(
        row.action not in ("Buy", "Add")
        for row in execution.candidates(ctx, _features())
    )


# Cancelling a larger proposed add cannot disguise a sub-floor sale of tiny holdings.
def test_reduction_floor_applies_to_both_actual_and_incremental_units():
    ctx = _context(
        held_units=np.array([0.01, 0, 0]),
        incumbent_units=np.array([1.0, 0, 0]),
        buy_allowed=np.zeros(3, bool),
    )
    assert execution.candidates(ctx, _features()) == []


# Malformed current state fails rather than becoming a free-cash opportunity.
@pytest.mark.parametrize(
    "change",
    [
        {"cash": np.nan},
        {"nav": 0},
        {"held_units": np.array([-1.0, 0, 0])},
        {"cost_bps": -1},
    ],
)
def test_invalid_current_state_is_refused(change):
    with pytest.raises(ValueError, match="funded"):
        execution.candidates(_context(**change), _features())


# A forced reduction retries its original units and clears only on an actual reset.
def test_forced_action_locks_original_units_and_expires_on_actual_reset():
    ctx = _context()
    trim = next(
        row for row in execution.candidates(ctx, _features()) if row.action == "Trim"
    )
    forced = execution.ForcedAction(ctx.t, trim)
    first = forced(ctx)
    assert first.units[0] == 0.5
    assert first.blocked_deferred_symbols == ("AAA",)
    changed = replace(
        ctx,
        t=10,
        session="2024-01-11",
        incumbent_units=np.array([2.0, 0.0, 0.0]),
        held_units=np.array([0.8, 0.0, 0.0]),
    )
    assert forced(changed).units[0] == 0.5
    stronger = replace(changed, incumbent_units=np.array([0.2, 0.0, 0.0]))
    assert forced(stronger).units[0] == 0.2
    reset = replace(
        changed, t=22, last_rebalance=22, next_rebalance=42, rebalanced=True
    )
    assert forced(reset) is None
    assert forced(replace(reset, t=27)) is None


# Buy/Add is one proposal, never a repeated top-up on later ordinary sessions.
def test_forced_add_is_one_shot_and_wrong_state_is_refused():
    ctx = _context()
    add = next(
        row for row in execution.candidates(ctx, _features()) if row.action == "Add"
    )
    forced = execution.ForcedAction(ctx.t, add)
    assert forced(ctx).units[0] == pytest.approx(1.2)
    assert forced(replace(ctx, t=6)) is None
    with pytest.raises(ValueError, match="incumbent"):
        execution.ForcedAction(ctx.t, add)(
            replace(ctx, incumbent_units=np.array([2.0, 0.0, 0.0]))
        )


# A cancelled reduction keeps its ceiling but does not force a later dust sale.
def test_lock_retry_after_price_collapse_obeys_trade_floor():
    ctx = _context()
    sell = next(
        row for row in execution.candidates(ctx, _features()) if row.action == "Sell"
    )
    forced = execution.ForcedAction(ctx.t, sell)
    assert forced(ctx).units[0] == 0
    dust = replace(ctx, t=6, prices=np.array([0.1, 10.0, 10.0]))
    retry = forced(dust)
    assert retry.units[0] == 1
    assert retry.blocked_deferred_symbols == ("AAA",)
    assert forced(replace(ctx, t=7)).units[0] == 0


# Capping a planned buy cannot create dust, and original tiny /4 exits remain intact.
def test_lock_tiny_buy_and_incumbent_exit_are_not_rewritten():
    ctx = _context()
    trim = next(
        row for row in execution.candidates(ctx, _features()) if row.action == "Trim"
    )
    forced = execution.ForcedAction(ctx.t, trim)
    forced(ctx)
    near = replace(ctx, t=6, held_units=np.array([0.49, 0.0, 0.0]))
    assert forced(near).units[0] == 0.49
    stronger = replace(near, incumbent_units=np.array([0.48, 0.0, 0.0]))
    assert forced(stronger).units[0] == 0.48
    dust_exit = replace(
        ctx,
        t=7,
        prices=np.array([0.1, 10.0, 10.0]),
        incumbent_units=np.array([0.9, 0.0, 0.0]),
    )
    assert forced(dust_exit).units[0] == 0.9
    boundary = replace(ctx, t=8, held_units=np.array([0.45, 0.0, 0.0]))
    assert forced(boundary).units[0] == 0.5


# The same score tie uses lexical order and spends the cycle even without a fill.
def test_controller_ties_schedule_one_per_cycle_and_current_holdings():
    data = _daily()

    # Produce exact score ties to test policy ordering independently of float rounding.
    def tied(family, day, features, actions):
        return np.full(len(features), 0.001)

    controller = execution.Controller(data, "ridge", SimpleNamespace(predict=tied))
    assert controller(replace(_context(), t=4, session="2024-01-05")) is None
    chosen = controller(_context())
    assert chosen.metadata["selected_intervention"]["symbol"] == "AAA"
    assert chosen.metadata["selected_intervention"]["action"] == "Add"
    np.testing.assert_array_equal(
        chosen.metadata["selected_intervention"]["features"],
        execution.candidates(_context(), data.features[5])[0].features,
    )
    assert controller(replace(_context(), t=10, session="2024-01-11")) is None
    reset = replace(
        _context(),
        t=20,
        session="2024-01-21",
        last_rebalance=20,
        next_rebalance=40,
        held_units=np.zeros(3),
        incumbent_units=np.zeros(3),
        rebalanced=True,
    )
    assert controller(reset).metadata["selected_intervention"]["action"] == "Buy"
    assert len(controller.selections) == 2


# Scores exactly at the declared floor preserve /4 rather than selecting a tie.
def test_controller_requires_strict_positive_advantage_floor():
    controller = execution.Controller(_daily(spread=0.0005 / 0.02), "momentum")
    assert controller(_context()) is None
    assert controller.selections == []


# Learned inference receives the candidate account state, not cached teacher features.
def test_model_inference_reads_current_state_and_rejects_bad_predictions():
    seen = []

    # Preserve the exact current candidate rows supplied to the fitted-model interface.
    def predict(family, day, features, actions):
        seen.append((family, day, features.copy(), actions.copy()))
        return np.full(len(features), 0.001)

    controller = execution.Controller(
        _daily(), "ridge", SimpleNamespace(predict=predict)
    )
    ctx = _context(
        cash=70.0,
        held_units=np.array([3.0, 0.0, 0.0]),
        incumbent_units=np.array([3.0, 0.0, 0.0]),
    )
    chosen = controller(ctx)
    assert chosen.metadata["selected_intervention"]["action"] == "Sell"
    assert seen[0][0:2] == ("ridge", ctx.session)
    assert seen[0][2][0, 22] == pytest.approx(0.3)
    assert seen[0][2][0, 23] == pytest.approx(0.7)

    # Invalid model output must not be converted into an implicit best action.
    def invalid(*args):
        return np.array([np.nan])

    with pytest.raises(ValueError, match="predictions"):
        execution.Controller(_daily(), "tree", SimpleNamespace(predict=invalid))(
            _context()
        )


# Feature ownership and current-row use make future edits irrelevant to prior actions.
def test_controller_freezes_data_and_never_reads_future_rows():
    initial = _daily()
    future = _daily()
    future.features[6:] = -100
    left, right = (
        execution.Controller(initial, "momentum"),
        execution.Controller(future, "momentum"),
    )
    initial.features[:] = 0
    assert left(_context()).metadata == right(_context()).metadata


# Construct a quiet /4 account with real ordinary planning and finite daily features.
def _account(rows=45):
    prices = np.full((rows, 7), 100.0)
    grades = np.zeros_like(prices, dtype=int)
    grades[:, :2] = 3
    report = _report(close=prices, grades=grades)
    mask = np.ones_like(prices, dtype=bool)
    data = build_dataset(report.panel, mask, grades, report.panel.adj_close[:, -1])
    data.features[:] = 0
    data.features[:, :, 2] = -0.1
    return report, mask, data


# Missing opportunities preserve the ordinary /4 calendar, fills and funded equity.
def test_priced_no_intervention_matches_direct_v4_and_reconciles():
    report, mask, data = _account()
    data.features[:] = 0
    priced = execution.price(
        report,
        mask,
        data,
        None,
        report.panel.dates[0].astype(object),
        25.0,
        family="momentum",
    )
    direct = simulate.run(
        report,
        allocator=policy_v4.allocator(mask),
        cost_bps=25.0,
        **profit_taking.control_options(report.panel),
    )
    np.testing.assert_array_equal(priced.result.equity, direct.equity)
    assert priced.verification["ok"]
    assert priced.diagnostics["action_counts"]["selected"] == dict.fromkeys(
        execution.ACTIONS, 0
    )
    assert "Hold" not in priced.diagnostics["action_counts"]["executed"]


# Actual cancelled sells remain selected once and retry under the normal executor.
def test_priced_reduction_lock_cancellation_and_reset(monkeypatch):
    report, mask, data = _account()
    opens = report.panel.open.copy()
    opens[6, 0] = 110.0
    report.panel = replace(report.panel, open=opens)
    priced = execution.price(
        report,
        mask,
        data,
        None,
        report.panel.dates[0].astype(object),
        25.0,
        family="momentum",
    )
    positions = _positions(priced)
    selected = priced.diagnostics["selected_interventions"]
    assert selected[0]["session_index"] == 5
    assert selected[0]["action"] == "Sell"
    assert positions[6, 0] > 0
    assert positions[7, 0] == 0
    assert (positions[7:21, 0] == 0).all()
    assert positions[21, 0] > 0
    assert priced.diagnostics["cancelled_sell_intents"] >= 1
    first = priced.diagnostics["selected_symbol_observations"][0]
    assert first["action"] == "Sell"
    assert first["submitted_units"] == 0
    assert first["observed_filled_units"] == 0
    assert first["cancelled_sell"] is True
    assert len(priced.diagnostics["selected_symbol_observations"]) == len(selected)
    assert all(row["cash"] >= 0 for row in priced.diagnostics["daily"])
    assert priced.verification["total_fees"] == pytest.approx(
        priced.result.traded * 0.0025
    )


# Event-owned opportunities are skipped, with no delayed extra intervention date.
def test_event_lifecycle_skips_opportunity_without_rescheduling(monkeypatch):
    report, mask, data = _account(rows=30)
    original = profit_taking.control_options

    # Own only a synthetic event schedule while retaining every other live option.
    def options(panel):
        values = original(panel)
        values["event_exposure"] = np.r_[np.ones(5), [0.5, 0.5], np.ones(23)]
        return values

    monkeypatch.setattr(profit_taking, "control_options", options)
    priced = execution.price(
        report,
        mask,
        data,
        None,
        report.panel.dates[0].astype(object),
        10.0,
        family="momentum",
    )
    assert priced.diagnostics["selected_interventions"][0]["session_index"] == 10
    assert priced.verification["ok"]
