"""Exercise the actual reporting dispatch on synthetic legacy growth evidence.

Repeating six source-built rows only crosses main's 500-row guard; it is not
new independent data or a model fit. No historical performance is measured.
"""

import socket
import sys
import warnings
from unittest.mock import Mock

import numpy as np
import pytest

from backend.cli import market_expectations as mx
from backend.market import edgar, valuation
from backend.market import expectations_reporting as reporting
from backend.tests.test_expectations_growth_evidence import build_dataset


# Prevent this reporting acceptance from invoking a provider or training a learner.
@pytest.fixture(autouse=True)
def no_network_or_fitting(monkeypatch):
    guards = []
    for owner, name in (
        (socket.socket, "connect"),
        (socket, "getaddrinfo"),
        (mx, "_fit_predict"),
        (mx, "_carried"),
    ):
        guard = Mock(side_effect=AssertionError(f"Forbidden boundary: {name}"))
        monkeypatch.setattr(owner, name, guard)
        guards.append(guard)
    yield
    for guard in guards:
        guard.assert_not_called()


# The actual CLI must report paired results without changing any model/study input.
@pytest.mark.parametrize(
    ("overlay", "leg"), [(False, False), (True, False), (False, True), (True, True)]
)
def test_main_masks_only_baseline_and_preserves_optional_dispatch(
    monkeypatch, tmp_path, capsys, overlay, leg
):
    ds = build_dataset()
    zero = np.zeros_like(ds.panel.close)
    fidx = {name: index for index, name in enumerate(edgar.FEATURE_NAMES)}
    multiples = valuation.Multiples(zero, zero, zero, zero, np.ones_like(zero))
    features = (
        ds.fund,
        fidx,
        None,
        {},
        zero,
        {20: zero, 60: zero, 120: zero},
        multiples,
    )
    quarters = {
        ticker: [(fact.end, fact.value, fact.filed) for fact in record.facts]
        for ticker, record in ds.records.items()
    }
    dates = ds.panel.dates.astype(object).tolist()
    reactions = {
        ticker: mx._release_windows(dates, record)
        for ticker, record in ds.records.items()
    }
    captured = {}
    actual_dataset, actual_after = mx._dataset, mx._after

    # Run the real source-to-dataset boundary before the explicit harness repetition.
    def repeated_dataset(*args):
        x, y, meta = actual_dataset(*args)
        np.testing.assert_array_equal(x, ds.x)
        np.testing.assert_array_equal(y, ds.y)
        assert meta == ds.meta
        x, y, meta = np.tile(x, (84, 1)), np.tile(y, 84), meta * 84
        x.flags.writeable = y.flags.writeable = False
        captured.update(x=x, y=y, meta=meta)
        return x, y, meta

    # Supply known errors without fitting; invalid-baseline rows have large errors.
    def forecast(x, y, *args, **kwargs):
        assert x is captured["x"]
        assert y is captured["y"]
        assert kwargs["available_dates"] == [row[3] for row in captured["meta"]]
        assert kwargs["score_dates"] == [dates[row[4]] for row in captured["meta"]]
        expected = np.tile([0.1, 10, 10, 10, 10, 10], 84)
        expected.flags.writeable = False
        captured["expected"] = expected
        return expected, None

    # Retain the actual surprise report and the exact arrays passed into it.
    def after(panel, expected, naive, y, *args):
        assert expected is captured["expected"]
        assert y is captured["y"]
        captured["naive"] = naive.copy()
        assert not np.shares_memory(naive, captured["x"])
        return actual_after(panel, expected, naive, y, *args)

    flags = (["--overlay"] if overlay else []) + (["--leg"] if leg else [])
    monkeypatch.setattr(
        sys, "argv", ["market_expectations", "--root", str(tmp_path), *flags]
    )
    sector = {ticker: "synthetic" for ticker in ds.panel.tickers}
    monkeypatch.setattr(mx, "_universe_panel", Mock(return_value=(ds.panel, sector)))
    monkeypatch.setattr(
        mx, "_records", Mock(return_value=(ds.records, quarters, reactions))
    )
    monkeypatch.setattr(mx, "_features", Mock(return_value=features))
    monkeypatch.setattr(mx, "_dataset", repeated_dataset)
    monkeypatch.setattr(mx, "_expected", forecast)
    monkeypatch.setattr(mx, "_after", after)
    before = Mock(return_value=np.zeros_like(zero, dtype=bool))
    overlay_call, leg_call = Mock(), Mock()
    monkeypatch.setattr(mx, "_before", before)
    monkeypatch.setattr(mx, "_overlay", overlay_call)
    monkeypatch.setattr(mx, "_leg", leg_call)
    mx.main()
    output = capsys.readouterr().out
    assert "paired on 84 rows of 504" in output
    assert "available=84" in output
    assert "missing_prior=84" in output
    assert "nonpositive_current=168" in output
    assert "paired eligible events: 84 of 504" in output
    learner_all = next(
        line for line in output.splitlines() if "learner (all scorable pairs)" in line
    )
    assert "MAE 8.250" in learner_all
    assert "504 rows" in learner_all
    np.testing.assert_array_equal(captured["naive"][::6], np.zeros(84))
    assert np.isnan(captured["naive"].reshape(84, 6)[:, 1:]).all()
    np.testing.assert_array_equal(captured["x"], np.tile(ds.x, (84, 1)))
    np.testing.assert_array_equal(captured["y"], np.tile(ds.y, 84))
    assert before.call_args.args[2] is captured["x"]
    assert before.call_args.args[3] is captured["y"]
    assert overlay_call.call_count == int(overlay)
    assert leg_call.call_count == int(leg)
    if leg:
        assert leg_call.call_args.args[3] is captured["x"]
        assert leg_call.call_args.args[4] is captured["y"]
    assert not list(tmp_path.iterdir())


# Metrics must distinguish undefined correlation from an observed zero coefficient.
@pytest.mark.parametrize(
    ("prediction", "target", "count", "mae", "corr"),
    [
        ([], [], 0, None, None),
        ([2], [3], 1, 1.0, None),
        ([0.1] * 17, [0.1] * 17, 17, 0.0, None),
        ([1, 2, 3], [3, 2, 1], 3, 4 / 3, -1.0),
        ([1e307, 2e307, 3e307], [3e307, 2e307, 1e307], 3, 4e307 / 3, -1.0),
        ([1e308], [-1e308], 1, None, None),
        ([1e308, 0], [-1e308, 0], 2, 1e308, -1.0),
        ([1e308, -1e308], [-1e308, 1e308], 2, None, -1.0),
    ],
)
def test_metrics_keep_undefined_and_large_finite_arithmetic_explicit(
    prediction, target, count, mae, corr
):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        actual = reporting.forecast_metrics(prediction, target)
    assert not caught
    assert actual[0] == count
    assert actual[1] is None if mae is None else actual[1] == pytest.approx(mae)
    assert actual[2] is None if corr is None else actual[2] == pytest.approx(corr)


# Preserve affine correlation when finite variation is only a few floating-point steps.
@pytest.mark.parametrize(
    ("prediction", "target"),
    [
        ([1.5, np.nextafter(1.5, np.inf)], [0.0, 1.0]),
        ([1.0, 1.0 + 2**-52, 1.0 + 2 * 2**-52], [0.0, 1.0, 2.0]),
    ],
)
def test_metrics_preserve_correlation_for_small_finite_variation(prediction, target):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        count, _, corr = reporting.forecast_metrics(prediction, target)
    assert not caught
    assert count == len(target)
    assert corr == pytest.approx(1.0, abs=1e-14)


# Misaligned report vectors must fail rather than broadcast into a false cohort.
@pytest.mark.parametrize(
    ("expected", "naive", "target"),
    [([1], [1, 2], [1]), ([[1]], [[1]], [[1]]), ([1], [1], [])],
)
def test_paired_forecasts_refuse_misaligned_vectors(expected, naive, target):
    with pytest.raises(ValueError, match="aligned one-dimensional"):
        reporting.common_forecast_mask(expected, naive, target)


# A mismatched source identity or invalid feature index cannot silently supply a mask.
@pytest.mark.parametrize(
    "invalid", ["ticker", "negative", "boolean", "outside", "missing"]
)
def test_growth_evidence_refuses_ambiguous_row_alignment(invalid):
    ds = build_dataset()
    row = list(ds.meta[0])
    if invalid == "ticker":
        ds.records[ds.panel.tickers[0]] = ds.records[ds.panel.tickers[1]]
    elif invalid == "negative":
        row[4] = -1
    elif invalid == "boolean":
        row[0] = True
    elif invalid == "outside":
        row[4] = len(ds.panel.dates)
    else:
        row = row[:4]
    with pytest.raises(ValueError, match="growth evidence"):
        reporting.growth_evidence(ds.panel, ds.records, [row])
