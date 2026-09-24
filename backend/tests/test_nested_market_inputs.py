"""Independent synthetic acceptance of frozen market research input assembly.

The real desk target calculation is exercised without replacing its scores,
grades, regime or sizing. Algebraic checks establish feature/label meaning, not
the provenance or investment value of any historical research observation.
"""

import copy
import json
import pickle
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import grading, risk, simulate
from backend.market import nested_market_inputs as inputs
from backend.market.panel import Panel


# Provide enough ordered synthetic business dates for every trailing feature.
def _panel(rows=240, *, tickers=("AAA", "BBB", "SPY", "QQQ")):
    calendar = np.arange("2024-01-02", "2026-01-01", dtype="datetime64[D]")
    dates = calendar[np.is_busday(calendar)][:rows]
    step = np.arange(rows, dtype=float)
    rates = np.column_stack(
        [
            0.001 * (column + 1) + 0.005 * np.sin(step / (column + 2))
            for column in range(len(tickers))
        ]
    )
    prices = 100 * np.exp(np.cumsum(rates, axis=0))
    return Panel(
        dates=dates,
        tickers=tickers,
        open=prices * 0.998,
        high=prices * 1.01,
        low=prices * 0.99,
        close=prices.copy(),
        adj_close=prices.copy(),
        volume=np.full(prices.shape, 1000.0),
        themes={ticker: () for ticker in tickers},
        benchmark="SPY",
    )


# Reorder or subset a real Panel while keeping every source field symbol aligned.
def _columns(panel, symbols):
    selected = [panel.index(symbol) for symbol in symbols]
    return replace(
        panel,
        tickers=tuple(symbols),
        **{
            name: getattr(panel, name)[:, selected].copy()
            for name in ("open", "high", "low", "close", "adj_close", "volume")
        },
        themes={symbol: panel.themes.get(symbol, ()) for symbol in symbols},
    )


# Supply the real target caller with nontrivial scores, holdable grades and regimes.
def _report(panel):
    rows, columns = panel.close.shape
    scores = np.tile(np.linspace(2, 1, columns), (rows, 1))
    scores[:, panel.index("SPY")] = -1
    scores[140:, panel.index("BBB")] = 5
    grades = np.full((rows, columns), grading.ORDINAL["A"], dtype=float)
    grades[:, panel.index("SPY")] = grading.ORDINAL["C"]
    states = [
        SimpleNamespace(exposure=1.0 if t < 120 else 0.5, tightening=False)
        for t in range(rows)
    ]
    return SimpleNamespace(
        panel=panel,
        sides={symbol: "ai" for symbol in panel.tickers if symbol != "SPY"},
        scores=scores,
        graded=SimpleNamespace(grades=grades),
        regime=SimpleNamespace(states=states),
    )


# Keep the incumbent report separate from the expanded execution-panel columns.
def _case(rows=240):
    panel = _panel(rows)
    report = _report(_columns(panel, ("AAA", "BBB", "SPY")))
    return report, panel


# Define an explicitly underinvested basket with no index weights.
def _weights(panel, *, aaa=0.2, bbb=0.3):
    weights = np.zeros_like(panel.close)
    weights[:, panel.index("AAA")] = aaa
    weights[:, panel.index("BBB")] = bbb
    return weights


# Independently calculate the full ordered feature vector from its stated algebra.
def _expected_features(panel, weights, t):
    values = []
    for symbol in ("SPY", "QQQ"):
        closes = panel.adj_close[:, panel.index(symbol)]
        values.extend(
            np.log(closes[t] / closes[t - lag]) for lag in (1, 5, 20, 63, 126)
        )
        values.append(
            np.std(np.log(closes[t - 19 : t + 1] / closes[t - 20 : t]), ddof=0)
        )
        values.append(np.log(closes[t] / np.mean(closes[t - 199 : t + 1])))
        values.append(np.log(closes[t] / np.max(closes[t - 62 : t + 1])))
    selected = weights[t] > 0
    allocation = weights[t, selected]
    cash = 1 - allocation.sum()
    closes = panel.adj_close[:, selected]
    values.extend(
        np.log(cash + np.sum(allocation * closes[t] / closes[t - lag]))
        for lag in (1, 5, 20, 63)
    )
    daily = np.log(
        cash + np.sum(allocation * closes[t - 19 : t + 1] / closes[t - 20 : t], axis=1)
    )
    values.extend((np.std(daily, ddof=0), allocation.sum()))
    return values


# All twenty-two columns must implement the declared price and current-basket meaning.
def test_all_price_features_match_independent_cash_inclusive_math():
    panel = _panel()
    weights = _weights(panel)
    values, names = inputs.price_features(panel, weights)
    assert values.shape == (240, 22)
    assert isinstance(names, tuple)
    assert len(names) == len(set(names)) == 22
    expected_names = []
    for symbol in ("SPY", "QQQ"):
        expected_names.extend(
            f"{symbol}_log_return_{lag}" for lag in (1, 5, 20, 63, 126)
        )
        expected_names.extend(
            (
                f"{symbol}_log_volatility_20",
                f"{symbol}_log_close_sma_200",
                f"{symbol}_log_drawdown_63",
            )
        )
    expected_names.extend(f"stock_log_return_{lag}" for lag in (1, 5, 20, 63))
    expected_names.extend(("stock_log_volatility_20", "stock_invested_fraction"))
    assert names == tuple(expected_names)
    for t in (199, 200, 220, 239):
        np.testing.assert_allclose(
            values[t], _expected_features(panel, weights, t), rtol=1e-12, atol=1e-12
        )
    np.testing.assert_array_equal(values[:, 21], np.full(240, 0.5))


# Trailing features become defined only after the full specified observation window.
@pytest.mark.parametrize(
    ("column", "first"),
    [
        (0, 1),
        (1, 5),
        (2, 20),
        (3, 63),
        (4, 126),
        (5, 20),
        (6, 199),
        (7, 62),
        (8, 1),
        (9, 5),
        (10, 20),
        (11, 63),
        (12, 126),
        (13, 20),
        (14, 199),
        (15, 62),
        (16, 1),
        (17, 5),
        (18, 20),
        (19, 63),
        (20, 20),
    ],
)
def test_feature_windows_have_the_declared_first_available_session(column, first):
    panel = _panel()
    values, _ = inputs.price_features(panel, _weights(panel))
    assert np.isnan(values[:first, column]).all()
    assert np.isfinite(values[first:, column]).all()


# Portfolio log wealth includes cash instead of averaging stock log returns.
def test_basket_features_preserve_residual_cash_and_do_not_average_log_returns():
    panel = _panel()
    panel.adj_close[:] = 100
    panel.adj_close[220, :2] = [200, 50]
    weights = _weights(panel, aaa=0.25, bbb=0.25)
    values, _ = inputs.price_features(panel, weights)
    expected = np.log(0.5 + 0.25 * 2 + 0.25 * 0.5)
    assert values[220, 16] == pytest.approx(expected)
    assert values[220, 16] != pytest.approx(0.25 * np.log(2) + 0.25 * np.log(0.5))


# The current composition defines all trailing basket counterfactuals, not old holdings.
def test_trailing_basket_features_use_current_weights_for_the_whole_window():
    panel = _panel()
    weights = _weights(panel, aaa=1, bbb=0)
    weights[220:, :2] = [0, 0.4]
    values, _ = inputs.price_features(panel, weights)
    np.testing.assert_allclose(
        values[220], _expected_features(panel, weights, 220), atol=1e-12
    )
    all_current = np.broadcast_to(weights[220], weights.shape).copy()
    fixed, _ = inputs.price_features(panel, all_current)
    np.testing.assert_array_equal(values[220], fixed[220])


# A missing held-member endpoint invalidates its basket feature without renormalization.
def test_missing_basket_members_are_not_dropped_or_renormalized():
    panel = _panel()
    panel.adj_close[205, panel.index("BBB")] = np.nan
    values, _ = inputs.price_features(panel, _weights(panel))
    assert np.isnan(values[206, 16])
    assert np.isnan(values[210, 17])
    assert np.isnan(values[225, 18])
    assert np.isnan(values[210, 20])
    assert np.isfinite(values[210, 16])
    assert np.isfinite(values[210, 18])
    assert np.isfinite(values[210, :16]).all()
    unused, _ = inputs.price_features(panel, _weights(panel, aaa=0.2, bbb=0))
    assert np.isfinite(unused[210]).all()


# An index window with a missing required observation is missing, never shortened.
def test_index_windows_do_not_skip_missing_prices():
    panel = _panel()
    panel.adj_close[205, panel.index("SPY")] = np.nan
    values, _ = inputs.price_features(panel, _weights(panel))
    assert np.isnan(values[206, 0])
    assert np.isnan(values[210, 1])
    assert np.isnan(values[225, 2])
    assert np.isnan(values[210, 5:8]).all()
    assert np.isfinite(values[210, 0])
    assert np.isfinite(values[210, 8:]).all()


# Empty stock exposure means a zero-return cash counterfactual, even with missing names.
def test_cash_basket_has_zero_trailing_returns_and_volatility():
    panel = _panel()
    panel.adj_close[:, :2] = np.nan
    values, _ = inputs.price_features(panel, _weights(panel, aaa=0, bbb=0))
    np.testing.assert_array_equal(values[200:, 16:], np.zeros((40, 6)))


# Labels use adjusted next-open entry, five open-to-open intervals and residual cash.
def test_forward_labels_use_adjusted_open_endpoints_and_cash_inclusive_wealth():
    panel = _panel(15)
    panel.open[:] = panel.close[:] = panel.adj_close[:] = 100
    panel.open[4] = [100, 100, 100, 200]
    panel.close[4] = [100, 100, 100, 200]
    panel.adj_close[4] = [50, 100, 100, 200]
    panel.open[9] = [60, 80, 120, 100]
    panel.close[9] = [90, 80, 120, 100]
    panel.adj_close[9] = [90, 80, 120, 100]
    labels, ends, available = inputs.forward_labels(panel, _weights(panel))
    assert labels.shape == ends.shape == available.shape == (15, 3)
    np.testing.assert_allclose(
        labels[3], [np.log(0.5 + 0.2 * 1.2 + 0.3 * 0.8), np.log(1.2), np.log(0.5)]
    )
    np.testing.assert_array_equal(ends[3], np.full(3, panel.dates[9]))
    np.testing.assert_array_equal(available[3], ends[3])
    assert np.isnan(labels[-6:]).all()
    assert np.isnat(ends[-6:]).all()
    assert np.isnat(available[-6:]).all()
    panel.close[3] *= 10
    panel.adj_close[3] *= 10
    repeated, _, _ = inputs.forward_labels(panel, _weights(panel))
    np.testing.assert_array_equal(repeated[3], labels[3])


# Each needed endpoint is mandatory for its target, without affecting other targets.
@pytest.mark.parametrize("endpoint", [4, 9])
@pytest.mark.parametrize("field", ["open", "close", "adj_close"])
def test_forward_labels_require_each_selected_members_adjusted_open(field, endpoint):
    panel = _panel(15)
    getattr(panel, field)[endpoint, panel.index("BBB")] = np.nan
    labels, _, _ = inputs.forward_labels(panel, _weights(panel))
    assert np.isnan(labels[3, 0])
    assert np.isfinite(labels[3, 1:]).all()
    unused, _, _ = inputs.forward_labels(panel, _weights(panel, aaa=0.2, bbb=0))
    assert np.isfinite(unused[3]).all()


# A known cash allocation has a zero gross label despite unavailable stock prices.
def test_forward_cash_labels_need_no_prices_for_unused_names():
    panel = _panel(15)
    for name in ("open", "close", "adj_close"):
        getattr(panel, name)[:, :2] = np.nan
    labels, ends, available = inputs.forward_labels(
        panel, _weights(panel, aaa=0, bbb=0)
    )
    np.testing.assert_array_equal(labels[:-6, 0], np.zeros(9))
    np.testing.assert_array_equal(ends[:-6, 0], panel.dates[6:])
    np.testing.assert_array_equal(available[:-6, 0], panel.dates[6:])


# A future basket refresh cannot rewrite today's fixed-basket counterfactual label.
def test_forward_labels_hold_the_decision_basket_through_a_later_cadence_change():
    panel = _panel(30)
    weights = _weights(panel, aaa=0.25, bbb=0)
    original, _, _ = inputs.forward_labels(panel, weights)
    weights[20:, :2] = [0, 1]
    changed, _, _ = inputs.forward_labels(panel, weights)
    np.testing.assert_array_equal(changed[:20], original[:20])
    assert changed[20, 0] != original[20, 0]


# Map the real incumbent's targets without changing its original report columns.
def test_stock_compositions_call_the_real_incumbent_on_the_absolute_cadence():
    report, panel = _case()
    original = pickle.dumps(report)
    reordered = _columns(panel, ("QQQ", "BBB", "SPY", "AAA"))
    observed = inputs.stock_compositions(report, reordered)
    assert observed.shape == reordered.close.shape
    for t in range(0, len(panel.dates), 20):
        target = simulate._targets(report, report.panel, risk.BOOK_CONFIG, t)
        expected = np.zeros(4)
        for column, symbol in enumerate(report.panel.tickers):
            expected[reordered.index(symbol)] = target[column]
        np.testing.assert_array_equal(
            observed[t : t + 20], np.broadcast_to(expected, observed[t : t + 20].shape)
        )
    assert observed[100, reordered.index("AAA")] > 0
    assert observed[140, reordered.index("AAA")] == 0
    assert observed[140, reordered.index("BBB")] > 0
    assert np.all(observed[:, [reordered.index("SPY"), reordered.index("QQQ")]] == 0)
    assert pickle.dumps(report) == original


# Assembly retains unmasked outcomes while making the training warmup structural.
def test_assembly_masks_training_warmup_and_dates_each_feature_and_outcome():
    report, panel = _case()
    unchanged = pickle.dumps(report)
    assembled = inputs.assemble(report, panel)
    assert assembled.regression.features.shape == (240, 22)
    raw, ends, available = inputs.forward_labels(panel, assembled.stock_weights)
    np.testing.assert_array_equal(assembled.raw_labels, raw)
    np.testing.assert_array_equal(assembled.label_end_on, ends)
    assert np.isnan(assembled.regression.labels[:200]).all()
    np.testing.assert_array_equal(assembled.regression.labels[200:], raw[200:])
    np.testing.assert_array_equal(assembled.regression.label_end_on, ends)
    np.testing.assert_array_equal(assembled.regression.label_available_on, available)
    np.testing.assert_array_equal(assembled.regression.dates, panel.dates)
    finite = np.isfinite(assembled.regression.features)
    dates = np.broadcast_to(panel.dates[:, None], finite.shape)
    np.testing.assert_array_equal(
        assembled.regression.feature_available_on[finite], dates[finite]
    )
    assert np.isnat(assembled.regression.feature_available_on[~finite]).all()
    np.testing.assert_array_equal(
        assembled.stock_weights, inputs.stock_compositions(report, panel)
    )
    assert pickle.dumps(report) == unchanged


# Admit newly priced names at the next refresh without demanding common history.
def test_equal_weight_uses_current_non_index_eligibility_and_keeps_ragged_history():
    report, panel = _case()
    for source in (report.panel, panel):
        for name in ("open", "high", "low", "close", "adj_close", "volume"):
            getattr(source, name)[:103, source.index("BBB")] = np.nan
    assembled = inputs.assemble(report, panel)
    np.testing.assert_array_equal(assembled.regression.dates, panel.dates)
    assert len(assembled.regression.dates) == 240
    np.testing.assert_array_equal(
        assembled.equal_weights[:120], np.broadcast_to([1, 0, 0, 0], (120, 4))
    )
    np.testing.assert_array_equal(
        assembled.equal_weights[120:], np.broadcast_to([0.5, 0.5, 0, 0], (120, 4))
    )
    assert np.isfinite(assembled.regression.features[200:]).all()


# With no eligible stocks, hold cash until the next scheduled eligibility check.
def test_equal_weight_empty_universe_is_cash_and_does_not_refresh_daily():
    report, panel = _case()
    for source in (report.panel, panel):
        for name in ("open", "high", "low", "close", "adj_close", "volume"):
            getattr(source, name)[0, :2] = np.nan
    assembled = inputs.assemble(report, panel)
    np.testing.assert_array_equal(assembled.equal_weights[:20], np.zeros((20, 4)))
    np.testing.assert_array_equal(
        assembled.equal_weights[20:], np.broadcast_to([0.5, 0.5, 0, 0], (220, 4))
    )


# Keep earlier observations and matured outcomes independent of later sources.
def test_future_prices_scores_grades_and_regimes_preserve_the_input_prefix():
    report, panel = _case()
    original = inputs.assemble(report, panel)
    for source in (report.panel, panel):
        for name in ("open", "high", "low", "close", "adj_close"):
            getattr(source, name)[201:] *= 1.8
    report.scores[201:, :2] = [100, -100]
    report.graded.grades[201:, 1] = grading.ORDINAL["C"]
    for state in report.regime.states[201:]:
        state.exposure = 0.1
        state.tightening = True
    changed = inputs.assemble(report, panel)
    np.testing.assert_array_equal(
        original.stock_weights[:201], changed.stock_weights[:201]
    )
    np.testing.assert_array_equal(
        original.equal_weights[:201], changed.equal_weights[:201]
    )
    np.testing.assert_array_equal(
        original.regression.features[:201], changed.regression.features[:201]
    )
    np.testing.assert_array_equal(
        original.regression.feature_available_on[:201],
        changed.regression.feature_available_on[:201],
    )
    np.testing.assert_array_equal(original.raw_labels[:195], changed.raw_labels[:195])
    assert not np.array_equal(
        original.regression.features[201:], changed.regression.features[201:]
    )


# A missing QQQ sleeve cannot be silently substituted by SPY or by cash.
def test_assembly_refuses_an_execution_panel_without_both_index_sleeves():
    report, panel = _case()
    with pytest.raises(ValueError, match="QQQ|index|symbols"):
        inputs.assemble(report, _columns(panel, ("AAA", "BBB", "SPY")))


# Every original source field must remain identical in the expanded execution panel.
@pytest.mark.parametrize(
    "field", ["open", "high", "low", "close", "adj_close", "volume"]
)
def test_assembly_rejects_changes_to_any_original_price_or_volume_field(field):
    report, panel = _case(15)
    getattr(panel, field)[7, panel.index("AAA")] *= 1.01
    with pytest.raises(ValueError, match=f"differs from original {field}"):
        inputs.assemble(report, panel)


# Calendar identity is exact, with no sorting, deduplication or subday truncation.
@pytest.mark.parametrize(
    "kind", ["shifted", "reversed", "duplicate", "timestamp", "nat"]
)
def test_assembly_rejects_changed_or_invalid_execution_calendars(kind):
    report, panel = _case(15)
    dates = panel.dates.copy()
    if kind == "shifted":
        dates += np.timedelta64(1, "D")
    elif kind == "reversed":
        dates = dates[::-1]
    elif kind == "duplicate":
        dates[2] = dates[1]
    elif kind == "timestamp":
        dates = dates.astype("datetime64[ns]")
    else:
        dates[2] = np.datetime64("NaT", "D")
    with pytest.raises(ValueError, match="dates"):
        inputs.assemble(report, replace(panel, dates=dates))


# Do not infer real prices from text, booleans, objects or complex observations.
@pytest.mark.parametrize(
    "field", ["open", "high", "low", "close", "adj_close", "volume"]
)
@pytest.mark.parametrize("dtype", [str, bool, object, complex])
def test_public_feature_boundary_rejects_non_real_source_matrices(field, dtype):
    panel = _panel(15)
    changed = replace(panel, **{field: getattr(panel, field).astype(dtype)})
    with pytest.raises(ValueError, match="real session by ticker matrix"):
        inputs.price_features(changed, _weights(panel))


# Each numeric source matrix needs the complete declared two-dimensional shape.
@pytest.mark.parametrize(
    "field", ["open", "high", "low", "close", "adj_close", "volume"]
)
@pytest.mark.parametrize("shape", [(15,), (14, 4), (15, 3), (15, 4, 1)])
def test_public_label_boundary_rejects_misaligned_source_matrices(field, shape):
    panel = _panel(15)
    changed = replace(panel, **{field: np.full(shape, 100.0)})
    with pytest.raises(ValueError, match="real session by ticker matrix"):
        inputs.forward_labels(changed, _weights(panel))


# Supplied stock baskets require finite, nonnegative, cash-bounded real weights.
@pytest.mark.parametrize("helper", ["price_features", "forward_labels"])
@pytest.mark.parametrize(
    "kind",
    [
        "short_rows",
        "short_columns",
        "flat",
        "bool",
        "str",
        "object",
        "complex",
        "nan",
        "inf",
        "negative",
        "overweight",
        "SPY",
        "QQQ",
    ],
)
def test_pure_helpers_reject_invalid_or_index_contaminated_stock_weights(helper, kind):
    panel = _panel(15)
    weights = _weights(panel)
    if kind == "short_rows":
        weights = weights[:-1]
    elif kind == "short_columns":
        weights = weights[:, :-1]
    elif kind == "flat":
        weights = weights.ravel()
    elif kind in ("bool", "str", "object", "complex"):
        weights = weights.astype(
            {"bool": bool, "str": str, "object": object, "complex": complex}[kind]
        )
    elif kind in ("SPY", "QQQ"):
        weights[:, panel.index(kind)] = 0.1
    else:
        weights[7, panel.index("AAA")] = {
            "nan": np.nan,
            "inf": np.inf,
            "negative": -0.1,
            "overweight": 1.1,
        }[kind]
    with pytest.raises(ValueError, match="stock weights"):
        getattr(inputs, helper)(panel, weights)


# Keep the original report columns and row counts explicit for every decision input.
@pytest.mark.parametrize("field", ["scores", "grades", "regimes"])
def test_assembly_rejects_report_judgements_with_misaligned_rows(field):
    report, panel = _case(15)
    if field == "scores":
        report.scores = report.scores[:-1]
    elif field == "grades":
        report.graded.grades = report.graded.grades[:, :-1]
    else:
        report.regime.states = report.regime.states[:-1]
    with pytest.raises(ValueError, match="align with its original panel"):
        inputs.assemble(report, panel)


# Invalid observed prices cannot masquerade as legitimate missing observations.
@pytest.mark.parametrize("helper", ["price_features", "forward_labels"])
@pytest.mark.parametrize("value", [0.0, -1.0, np.inf, -np.inf])
def test_public_helpers_refuse_nonpositive_or_infinite_prices(helper, value):
    panel = _panel(15)
    panel.adj_close[7, panel.index("BBB")] = value
    with pytest.raises(ValueError, match="invalid observed|infinity|overflow"):
        getattr(inputs, helper)(panel, _weights(panel))


# Source identity is ordered and unique rather than inferred from a set or mapping.
@pytest.mark.parametrize(
    "symbols",
    [
        ("AAA", "AAA", "SPY", "QQQ"),
        ("AAA", " BBB", "SPY", "QQQ"),
        ("AAA", "", "SPY", "QQQ"),
        ["AAA", "BBB", "SPY", "QQQ"],
        {"AAA", "BBB", "SPY", "QQQ"},
    ],
)
def test_public_helpers_refuse_ambiguous_symbol_identity(symbols):
    panel = _panel(15)
    with pytest.raises(ValueError, match="ordered unique ticker tuple"):
        inputs.price_features(replace(panel, tickers=symbols), _weights(panel))


# Owned output evidence cannot change when the caller later edits its input arrays.
def test_assembly_seals_derived_evidence_and_execution_source_copies():
    report, panel = _case()
    assembled = inputs.assemble(report, panel)
    assert assembled.report is report
    assert assembled.panel is not panel
    original_close = assembled.panel.adj_close.copy()
    original_features = assembled.regression.features.copy()
    original_labels = assembled.raw_labels.copy()
    for source in (report.panel, panel):
        source.adj_close[:] *= 2
    report.scores[:] = 0
    np.testing.assert_array_equal(assembled.panel.adj_close, original_close)
    np.testing.assert_array_equal(assembled.regression.features, original_features)
    np.testing.assert_array_equal(assembled.raw_labels, original_labels)
    for values in (
        assembled.panel.dates,
        assembled.panel.open,
        assembled.panel.high,
        assembled.panel.low,
        assembled.panel.close,
        assembled.panel.adj_close,
        assembled.panel.volume,
        assembled.stock_weights,
        assembled.equal_weights,
        assembled.raw_labels,
        assembled.label_end_on,
        assembled.regression.features,
        assembled.regression.labels,
    ):
        assert not values.flags.writeable
        with pytest.raises(ValueError, match="WRITEABLE|writable|writeable"):
            values.setflags(write=True)


# Pure helper outputs remain immutable and independent of caller-owned buffers.
def test_public_math_helpers_return_owned_immutable_evidence():
    panel = _panel()
    weights = _weights(panel)
    features, _ = inputs.price_features(panel, weights)
    labels, ends, available = inputs.forward_labels(panel, weights)
    original_features, original_labels = features.copy(), labels.copy()
    weights[:] = 0
    panel.adj_close[:] *= 3
    np.testing.assert_array_equal(features, original_features)
    np.testing.assert_array_equal(labels, original_labels)
    for values in (features, labels, ends, available):
        assert not values.flags.writeable
        with pytest.raises(ValueError, match="WRITEABLE|writable|writeable"):
            values.setflags(write=True)


# Record the exact proxy definition without overstating data or strategy quality.
def test_audit_is_json_safe_and_preserves_explicit_research_limitations():
    report, panel = _case()
    assembled = inputs.assemble(report, panel)
    audit = assembled.audit
    json.dumps(audit, allow_nan=False)
    assert audit["training_warmup_rows"] == 200
    assert audit["label_entry_offset"] == 1
    assert audit["label_exit_offset"] == 6
    assert audit["stock_cadence"] == 20
    assert audit["stock_cadence_anchor"] == "global source row zero"
    assert "not funded account" in audit["label_basis"]
    for key in (
        "historical_availability_verified",
        "historical_membership_verified",
        "quality_features_complete",
        "adoption_eligible",
    ):
        assert audit[key] is False
    assert (
        audit["finite_features"]
        == np.isfinite(assembled.regression.features).sum(axis=0).tolist()
    )
    assert (
        audit["finite_raw_labels"]
        == np.isfinite(assembled.raw_labels).sum(axis=0).tolist()
    )
    assert (
        audit["finite_training_labels"]
        == np.isfinite(assembled.regression.labels).sum(axis=0).tolist()
    )


# Change exactly one report input that the incumbent or basket calculation consumes.
def _change_consumed_field(report, field):
    if field in ("open", "high", "low", "close", "adj_close", "volume"):
        getattr(report.panel, field)[7, 0] *= 1.01
    elif field == "scores":
        report.scores[7, 0] += 0.25
    elif field == "grades":
        report.graded.grades[7, 0] = grading.ORDINAL["C"]
    elif field == "dates":
        report.panel = replace(
            report.panel, dates=report.panel.dates + np.timedelta64(1, "D")
        )
    elif field == "tickers":
        report.panel = replace(
            report.panel, tickers=tuple(reversed(report.panel.tickers))
        )
    elif field == "benchmark":
        report.panel = replace(report.panel, benchmark="AAA")
    elif field == "themes":
        report.panel.themes["AAA"] = ("synthetic-theme",)
    elif field == "sides":
        report.sides["AAA"] = "other"
    elif field in ("exposure", "tightening"):
        setattr(
            report.regime.states[7],
            field,
            {"exposure": 0.37, "tightening": True}[field],
        )
    else:
        raise AssertionError(f"Unexpected synthetic mutation: {field}")


# Isolate source-file drift in temporary files without editing repository code.
def _temporary_binding_sources(tmp_path, monkeypatch):
    paths = (
        tmp_path / "backend/market/assembly.py",
        tmp_path / "backend/agents/trading/desk/policy.py",
    )
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("version = 1\n", encoding="utf-8")
    monkeypatch.setattr(inputs, "ROOT", tmp_path)
    return paths


# Any consumed value or identity change must alter the recorded report-state hash.
@pytest.mark.parametrize(
    "field",
    [
        "scores",
        "grades",
        "dates",
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
        "tickers",
        "benchmark",
        "themes",
        "sides",
        "exposure",
        "tightening",
    ],
)
def test_binding_changes_for_every_consumed_report_field(field):
    report, _ = _case(40)
    before = inputs.binding(report)
    _change_consumed_field(report, field)
    after = inputs.binding(report)
    assert (
        before["report_consumed_state_sha256"] != after["report_consumed_state_sha256"]
    )
    assert before["assembly_source_hashes"] == after["assembly_source_hashes"]
    assert before["book_config"] == after["book_config"]


# Identical numeric observations bind identically regardless of memory or mapping order.
def test_binding_is_stable_for_equivalent_copies_and_mapping_order():
    report, _ = _case(40)
    equivalent = copy.deepcopy(report)
    equivalent.sides = dict(reversed(list(equivalent.sides.items())))
    equivalent.panel = replace(
        equivalent.panel,
        themes=dict(reversed(list(equivalent.panel.themes.items()))),
        close=np.asfortranarray(equivalent.panel.close),
    )
    equivalent.scores = np.asfortranarray(equivalent.scores)
    before = inputs.binding(report)
    assert before == inputs.binding(equivalent)
    assert before == inputs.binding(report)
    json.dumps(before, allow_nan=False)


# The binding captures actual sizing configuration separately from data and code bytes.
def test_binding_changes_when_the_consumed_book_configuration_changes(monkeypatch):
    report, _ = _case(40)
    before = inputs.binding(report)
    monkeypatch.setattr(risk, "BOOK_CONFIG", replace(risk.BOOK_CONFIG, name_cap=0.1))
    after = inputs.binding(report)
    assert (
        before["report_consumed_state_sha256"] == after["report_consumed_state_sha256"]
    )
    assert before["assembly_source_hashes"] == after["assembly_source_hashes"]
    assert before["book_config"] != after["book_config"]
    assert after["book_config"]["name_cap"] == 0.1


# Added, edited or removed source files invalidate the assembly-code inventory.
@pytest.mark.parametrize("change", ["edit_market", "edit_desk", "add", "remove"])
def test_binding_changes_for_python_source_inventory_drift(
    tmp_path, monkeypatch, change
):
    market, desk = _temporary_binding_sources(tmp_path, monkeypatch)
    report, _ = _case(40)
    before = inputs.binding(report)
    assert set(before["assembly_source_hashes"]) == {
        "backend/market/assembly.py",
        "backend/agents/trading/desk/policy.py",
    }
    if change == "edit_market":
        market.write_text("version = 2\n", encoding="utf-8")
    elif change == "edit_desk":
        desk.write_text("version = 2\n", encoding="utf-8")
    elif change == "add":
        (market.parent / "new_logic.py").write_text("version = 1\n", encoding="utf-8")
    else:
        market.unlink()
    after = inputs.binding(report)
    assert before["assembly_source_hashes"] != after["assembly_source_hashes"]
    assert (
        before["report_consumed_state_sha256"] == after["report_consumed_state_sha256"]
    )
    assert before["book_config"] == after["book_config"]


# Retain the checked report and configuration binding in every assembly receipt.
def test_assembly_receipt_retains_the_exact_consumed_state_binding():
    report, panel = _case()
    before = inputs.binding(report)
    assembled = inputs.assemble(report, panel)
    assert assembled.audit["assembly_binding"] == before
    assert assembled.audit["assembly_binding"] == inputs.binding(report)
    assert (
        assembled.audit["assembly_binding"]["schema"]
        == "nested-market-assembly-binding/1"
    )
    assert assembled.report is report


# Refuse report drift during real feature or label arithmetic.
@pytest.mark.parametrize("phase", ["_features", "_labels"])
@pytest.mark.parametrize(
    "field", ["grades", "scores", "sides", "themes", "exposure", "tightening", "close"]
)
def test_assembly_refuses_report_mutation_during_real_derivation(
    monkeypatch, phase, field
):
    report, panel = _case()
    original = getattr(inputs, phase)

    # Preserve the real calculation and then introduce concurrent report drift.
    def derive_then_mutate(execution, weights):
        result = original(execution, weights)
        _change_consumed_field(report, field)
        return result

    monkeypatch.setattr(inputs, phase, derive_then_mutate)
    with pytest.raises(
        ValueError, match="report or source changed during input assembly"
    ):
        inputs.assemble(report, panel)


# Refuse configuration drift during real derivation instead of issuing a receipt.
@pytest.mark.parametrize("phase", ["_features", "_labels"])
def test_assembly_refuses_configuration_mutation_during_derivation(monkeypatch, phase):
    report, panel = _case()
    original = getattr(inputs, phase)

    # Keep actual arithmetic and change the risk configuration only after it returns.
    def derive_then_reconfigure(execution, weights):
        result = original(execution, weights)
        monkeypatch.setattr(
            risk, "BOOK_CONFIG", replace(risk.BOOK_CONFIG, name_cap=0.1)
        )
        return result

    monkeypatch.setattr(inputs, phase, derive_then_reconfigure)
    with pytest.raises(
        ValueError, match="report or source changed during input assembly"
    ):
        inputs.assemble(report, panel)


# Refuse source-byte changes during real feature or label calculation.
@pytest.mark.parametrize("phase", ["_features", "_labels"])
def test_assembly_refuses_code_mutation_during_derivation(tmp_path, monkeypatch, phase):
    market, _ = _temporary_binding_sources(tmp_path, monkeypatch)
    report, panel = _case()
    original = getattr(inputs, phase)

    # Run real math before changing only a temporary bound source file.
    def derive_then_change_source(execution, weights):
        result = original(execution, weights)
        market.write_text("version = 2\n", encoding="utf-8")
        return result

    monkeypatch.setattr(inputs, phase, derive_then_change_source)
    with pytest.raises(
        ValueError, match="report or source changed during input assembly"
    ):
        inputs.assemble(report, panel)
