"""Pin shared-date reporting through real residual-return spread arithmetic.

Returns and fifth memberships are synthetic. These tests exercise the actual
spread calculation and its CLI dispatch, not fitting, price collection, causal
fifth construction, investment performance, or funded portfolio accounting.
"""

import math
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from backend.cli import market_expectations as mx


# Refuse accidental model fitting in deterministic reporting-only acceptance.
@pytest.fixture(autouse=True)
def forbid_fits(monkeypatch):
    monkeypatch.setattr(
        mx, "_fit_predict", Mock(side_effect=AssertionError("No fitting permitted"))
    )


# Supply unequal date coverage with partial and wholly missing outcome groups.
def unequal_contrasts():
    day = np.arange(22, dtype=float)
    label = np.column_stack(
        (
            0.005 + 0.001 * day,
            0.011 + 0.001 * day,
            0.001 + 0.0001 * day,
            0.009 - 0.0002 * day,
            0.0005 + 0.00015 * day,
            0.0035 + 0.00015 * day,
        )
    )
    a, b, c, d = (np.zeros_like(label, dtype=bool) for _ in range(4))
    a[:18, :2] = True
    b[:18, 2] = True
    c[4:, 3] = True
    d[4:, 4:] = True
    label[6, 0] = np.nan  # One usable observation still supports this group.
    label[8, 2] = np.nan  # The learner has no comparison mean on this date.
    label[10, 3] = np.inf  # The naive model has no selected mean on this date.
    label[11, 4] = np.nan  # Its other comparison observation remains usable.
    return label, a, b, c, d


# Derive group means without reusing the production vectorized support helper.
def observed_values(label, mask, day):
    return [
        float(value)
        for value, selected in zip(label[day], mask[day], strict=True)
        if selected and math.isfinite(value)
    ]


# Define paired dates by independently requiring a mean for all four groups.
def common_days(label, masks):
    return [
        day
        for day in range(len(label))
        if all(observed_values(label, mask, day) for mask in masks)
    ]


# Calculate equal-session spread, Bartlett HAC statistic and selected count.
def expected_contrast(label, selected, comparison, days, lag):
    if len(days) < 10:
        return math.nan, math.nan, 0
    differences = []
    count = 0
    for day in days:
        first = observed_values(label, selected, day)
        second = observed_values(label, comparison, day)
        differences.append(
            math.fsum(first) / len(first) - math.fsum(second) / len(second)
        )
        count += len(first)
    size = len(differences)
    mean = math.fsum(differences) / size
    centered = [value - mean for value in differences]
    variance = math.fsum(value * value for value in centered) / size
    for offset in range(1, min(lag, size - 1) + 1):
        covariance = (
            math.fsum(
                centered[index] * centered[index - offset]
                for index in range(offset, size)
            )
            / size
        )
        variance += 2 * (1 - offset / (lag + 1)) * covariance
    statistic = mean / math.sqrt(max(variance, 1e-12) / size)
    return mean, statistic, count


# Compare each reported statistic on the same dates, not its own surviving dates.
def test_paired_spread_uses_common_finite_session_support_without_mutation():
    label, a, b, c, d = unequal_contrasts()
    originals = [item.copy() for item in (label, a, b, c, d)]
    days = common_days(label, (a, b, c, d))
    assert days == [4, 5, 6, 7, 9, 11, 12, 13, 14, 15, 16, 17]
    expected_learner = expected_contrast(label, a, b, days, 3)
    expected_naive = expected_contrast(label, c, d, days, 3)
    assert expected_learner[2] == 23
    assert expected_naive[2] == 12
    assert not math.isclose(mx._spread(label, a, b, 3)[0], expected_learner[0])
    assert not math.isclose(mx._spread(label, c, d, 3)[0], expected_naive[0])
    learner, naive, sessions = mx._paired_spread(label, a, b, c, d, 3)
    assert sessions == len(days)
    np.testing.assert_allclose(learner, expected_learner, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(naive, expected_naive, rtol=1e-12, atol=1e-12)
    for actual, original in zip((label, a, b, c, d), originals, strict=True):
        np.testing.assert_array_equal(actual, original)


# Retain equal-support means while counting only observations on contributing dates.
def test_paired_spread_retains_equal_support_control():
    label, a, b, _, _ = unequal_contrasts()
    expected = mx._spread(label, a, b, 3)
    learner, naive, sessions = mx._paired_spread(label, a, b, a, b, 3)
    assert sessions == 17
    np.testing.assert_allclose(learner[:2], expected[:2], rtol=0, atol=0)
    np.testing.assert_allclose(naive[:2], expected[:2], rtol=0, atol=0)
    # Legacy _spread also counts selected names on its excluded comparison date.
    assert expected[2] == 35
    days = common_days(label, (a, b, a, b))
    count = sum(len(observed_values(label, a, day)) for day in days)
    assert count == learner[2] == naive[2] == 33


# Individually ample coverage must not hide too few mutually comparable dates.
@pytest.mark.parametrize(("start", "expected_sessions"), [(6, 9), (15, 0)])
def test_paired_spread_withholds_results_without_ten_common_sessions(
    start, expected_sessions
):
    label = np.tile([0.02, 0.01, 0.03, 0.005], (30, 1))
    a, b, c, d = (np.zeros_like(label, dtype=bool) for _ in range(4))
    a[:15, 0] = True
    b[:15, 1] = True
    c[start : start + 15, 2] = True
    d[start : start + 15, 3] = True
    assert math.isfinite(mx._spread(label, a, b, 3)[0])
    assert math.isfinite(mx._spread(label, c, d, 3)[0])
    learner, naive, sessions = mx._paired_spread(label, a, b, c, d, 3)
    assert sessions == expected_sessions
    for mean, statistic, count in (learner, naive):
        assert math.isnan(mean)
        assert math.isnan(statistic)
        assert count == 0


# Route every printed after-report contrast through the actual paired calculator.
def test_after_prints_paired_contrasts_on_controlled_fifths(monkeypatch, capsys):
    label, a, b, c, d = unequal_contrasts()
    learner_fifths = np.zeros((*label.shape, 5), dtype=bool)
    naive_fifths = np.zeros_like(learner_fifths)
    learner_fifths[:, :, 4], learner_fifths[:, :, 0] = a, b
    naive_fifths[:, :, 4], naive_fifths[:, :, 0] = c, d
    fifths = Mock(side_effect=[learner_fifths, naive_fifths])
    monkeypatch.setattr(mx, "_fifths", fifths)
    dates = np.arange("2026-01-01", "2026-01-23", dtype="datetime64[D]")
    panel = SimpleNamespace(
        dates=dates,
        adj_close=np.ones_like(label),
        forward_residual=Mock(return_value=label),
    )
    size = len(dates) - 1
    meta = [(0, index, 2026, dates[index].astype(object)) for index in range(size)]
    expected = np.zeros(size)
    naive = np.zeros(size)
    targets = np.zeros(size)
    paired = getattr(mx, "_paired_spread", None)
    calls = []

    # Record dispatch while leaving the candidate's real spread arithmetic active.
    def paired_spy(labels, first, second, third, fourth, lag):
        calls.append(
            (labels, first.copy(), second.copy(), third.copy(), fourth.copy(), lag)
        )
        assert paired is not None, "The production paired calculator must exist"
        return paired(labels, first, second, third, fourth, lag)

    monkeypatch.setattr(mx, "_paired_spread", paired_spy, raising=False)
    mx._after(panel, expected, naive, targets, meta, np.full(size, 2026), [2026])
    panel.forward_residual.assert_called_once_with(20)
    assert fifths.call_count == 2
    assert len(calls) == 6
    for call in calls:
        assert call[0] is label
        assert call[-1] == 20
    for actual, original in zip(calls[-1][1:5], (a, b, c, d), strict=True):
        np.testing.assert_array_equal(actual, original)
    days = common_days(label, (a, b, c, d))
    learner_result = expected_contrast(label, a, b, days, 20)
    naive_result = expected_contrast(label, c, d, days, 20)
    line = next(
        line
        for line in capsys.readouterr().out.splitlines()
        if "top fifth less bottom fifth" in line
    )
    assert f"{learner_result[0]:+8.2%}" in line
    assert f"{naive_result[0]:+8.2%}" in line
