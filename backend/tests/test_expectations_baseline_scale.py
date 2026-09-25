"""Exercise research baseline units through the real CLI without fitting models.

All observations and prices are synthetic. The expected vector is the known
target, not a fitted forecast; these checks establish arithmetic and dispatch,
not predictive quality, historical availability or investment performance.
"""

import sys
from datetime import UTC, date, datetime, timedelta
from unittest.mock import Mock

import numpy as np
import pytest

from backend.cli import market_expectations as mx
from backend.market import calendar, edgar, valuation
from backend.market.panel import Panel

GROWTH = (-0.95, -0.5, 0.0, 0.1, 1.0, 3.0, 6.0)


# Refuse model training outside this deterministic reporting check.
@pytest.fixture(autouse=True)
def forbid_fits(monkeypatch):
    refusal = Mock(side_effect=AssertionError("Model fitting is outside this test"))
    monkeypatch.setattr(mx, "_fit_predict", refusal)


# Build dated synthetic facts and preserve the real source-to-dataset calculation.
@pytest.fixture
def growth_dataset():
    _, sessions = calendar.reviewed_sessions()
    dates = np.arange("2022-01-01", "2024-07-01", dtype="datetime64[D]")
    dates = dates[np.is_busday(dates, busdaycal=sessions)]
    tickers = tuple(f"SYNTH{i}" for i in range(len(GROWTH))) + ("SPY",)
    prices = np.full((len(dates), len(tickers)), 100.0)
    panel = Panel(
        dates, tickers, prices, prices, prices, prices, prices, prices, {}, "SPY"
    )
    source_time = datetime(2024, 6, 30, tzinfo=UTC)
    accepted = datetime(2024, 5, 15, 12, tzinfo=UTC)
    event = edgar.EarningsEvent(
        accepted, date(2024, 5, 15), "synthetic-release", "2.02"
    )
    records, quarters = {}, {}
    for symbol, growth in zip(tickers[:-1], GROWTH, strict=True):
        facts = []
        for year in (2022, 2023):
            for start_month, end_month, end_day in (
                (1, 3, 31),
                (4, 6, 30),
                (7, 9, 30),
                (10, 12, 31),
            ):
                end = date(year, end_month, end_day)
                facts.append(
                    edgar.QuarterFact(
                        "revenue",
                        date(year, start_month, 1),
                        end,
                        100 * (1 + growth) ** (year - 2022),
                        end + timedelta(days=45),
                    )
                )
        facts.append(
            edgar.QuarterFact(
                "revenue",
                date(2024, 1, 1),
                date(2024, 3, 31),
                100 * (1 + growth) ** 2,
                date(2024, 5, 15),
            )
        )
        records[symbol] = edgar.CompanyRecord(
            symbol, 1, (event,), tuple(facts), source_time
        )
        quarters[symbol] = [(fact.end, fact.value, fact.filed) for fact in facts]
    fund = edgar.edgar_features(panel, records, strict_publication=True)
    fidx = {name: index for index, name in enumerate(edgar.FEATURE_NAMES)}
    zero = np.zeros_like(prices)
    multiples = valuation.Multiples(zero, zero, zero, zero, np.ones_like(prices))
    feature_args = (
        fund,
        fidx,
        None,
        {},
        zero,
        {20: zero, 60: zero, 120: zero},
        multiples,
    )
    sector = {ticker: "synthetic" for ticker in tickers}
    feats, _ = mx._block(
        panel, sector, fund, fidx, None, {}, feature_args[5], multiples
    )
    days = dates.astype(object).tolist()
    reactions = {
        symbol: mx._release_windows(days, record) for symbol, record in records.items()
    }
    x, y, meta = mx._dataset(panel, days, quarters, reactions, feats)
    assert len(y) == len(GROWTH)
    np.testing.assert_allclose(y, np.clip(GROWTH, -0.9, 5.0), atol=1e-14)
    return panel, sector, records, quarters, reactions, feature_args, x, y, meta


# Run the actual CLI baseline assignment while replacing only unrelated boundaries.
def exercise_main(monkeypatch, tmp_path, dataset, *, overlay=False, leg=False):
    (
        panel,
        sector,
        records,
        quarters,
        reactions,
        feature_args,
        source_x,
        source_y,
        source_meta,
    ) = dataset
    # Repetition only crosses the CLI's 500-row guard; it is not new training data.
    x = np.tile(source_x, (72, 1))
    y = np.tile(source_y, 72)
    meta = source_meta * 72
    before_x, before_y = x.copy(), y.copy()
    expected = y.copy()
    before_expected = expected.copy()
    cheap = np.zeros_like(panel.adj_close, dtype=bool)
    flags = (["--overlay"] if overlay else []) + (["--leg"] if leg else [])
    monkeypatch.setattr(
        sys, "argv", ["market_expectations", "--root", str(tmp_path), *flags]
    )
    monkeypatch.setattr(mx, "_universe_panel", Mock(return_value=(panel, sector)))
    monkeypatch.setattr(
        mx, "_records", Mock(return_value=(records, quarters, reactions))
    )
    monkeypatch.setattr(mx, "_features", Mock(return_value=feature_args))
    monkeypatch.setattr(mx, "_dataset", Mock(return_value=(x, y, meta)))
    forecast = Mock(return_value=(expected, None))
    after = Mock()
    before = Mock(return_value=cheap)
    overlay_call, leg_call = Mock(), Mock()
    monkeypatch.setattr(mx, "_expected", forecast)
    monkeypatch.setattr(mx, "_after", after)
    monkeypatch.setattr(mx, "_before", before)
    monkeypatch.setattr(mx, "_overlay", overlay_call)
    monkeypatch.setattr(mx, "_leg", leg_call)
    mx.main()
    assert forecast.call_count == after.call_count == before.call_count == 1
    assert forecast.call_args.args[0] is x
    assert forecast.call_args.args[1] is y
    assert before.call_args.args[2] is x
    assert before.call_args.args[3] is y
    assert after.call_args.args[1] is expected
    assert after.call_args.args[3] is y
    assert overlay_call.call_count == int(overlay)
    assert leg_call.call_count == int(leg)
    if overlay:
        assert overlay_call.call_args.args[3] is cheap
    if leg:
        assert leg_call.call_args.args[3] is x
        assert leg_call.call_args.args[4] is y
    np.testing.assert_array_equal(x, before_x)
    np.testing.assert_array_equal(y, before_y)
    np.testing.assert_array_equal(expected, before_expected)
    return x, y, after.call_args.args[2]


# A repeated annual growth rate must reach the surprise report on the target scale.
def test_cli_baseline_repeats_prior_growth_in_target_units(
    monkeypatch, tmp_path, growth_dataset
):
    x, y, naive = exercise_main(monkeypatch, tmp_path, growth_dataset)
    np.testing.assert_allclose(naive, y, atol=1e-6, rtol=0)
    assert not np.shares_memory(x, naive)


# The real accuracy formatter must not penalize a matching repeated-growth baseline.
def test_cli_accuracy_scores_repeated_growth_correctly(
    monkeypatch, tmp_path, growth_dataset, capsys
):
    exercise_main(monkeypatch, tmp_path, growth_dataset)
    report = capsys.readouterr().out
    line = next(line for line in report.splitlines() if "naive (last growth)" in line)
    assert "MAE 0.000" in line, line
    assert "corr +1.000" in line, line


# Preserve model input arrays and optional-study dispatch during baseline conversion.
@pytest.mark.parametrize(
    ("overlay", "leg"), [(False, False), (True, False), (False, True), (True, True)]
)
def test_baseline_does_not_change_model_or_optional_study_inputs(
    monkeypatch, tmp_path, growth_dataset, overlay, leg
):
    exercise_main(monkeypatch, tmp_path, growth_dataset, overlay=overlay, leg=leg)


# Preserve an unknown value while mapping negative, zero and capped growth correctly.
def test_baseline_preserves_nan_and_does_not_invent_a_validity_mask(
    monkeypatch, tmp_path, growth_dataset
):
    x_source = growth_dataset[6]
    x_source[0, mx.NAMES.index("revenue_yoy")] = np.nan
    x, _, naive = exercise_main(monkeypatch, tmp_path, growth_dataset)
    assert np.isnan(naive[:: len(GROWTH)]).all()
    assert naive[2] == 0.0
    assert naive[6] == 5.0
    assert not np.shares_memory(x, naive)


# The baseline passed by main must preserve true surprise ordering and trailing fifths.
def test_cli_baseline_surprises_use_matching_units(
    monkeypatch, tmp_path, growth_dataset
):
    prior = np.r_[np.full(24, 0.1), 1.0, 0.1]
    actual = prior + np.r_[np.linspace(-0.2, 0.2, 24), 0.1, 0.2]
    dataset = list(growth_dataset)
    source_x = np.zeros((26, len(mx.NAMES)))
    source_x[:, mx.NAMES.index("revenue_yoy")] = np.log1p(prior)
    dataset[6], dataset[7], dataset[8] = source_x, actual, [dataset[8][0]] * 26
    _, _, baseline = exercise_main(monkeypatch, tmp_path, dataset)
    surprise = actual - baseline[:26]
    np.testing.assert_allclose(surprise, actual - prior, atol=1e-14)
    assert surprise[-2] < surprise[-1]
    meta = [(0, index, 2024) for index in range(26)]
    fifths = mx._fifths(
        surprise, np.ones(26, dtype=bool), meta, np.full(26, 2024), [2024], (27, 1), 1
    )
    assert not fifths[:25].any()
    assert fifths[25, 0, 3]
    assert not fifths[25, 0, 4]
