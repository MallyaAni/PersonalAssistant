"""Exercise real dataset and yearly selection without fitting any model."""

from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from backend.cli import market_expectations as mx
from backend.market import challenger


# Build a causal feature panel containing a December earnings reaction.
def _inputs(end="2024-01-03"):
    dates = np.arange("2022-01-01", end, dtype="datetime64[D]")
    dates = dates[np.is_busday(dates)].astype(object).tolist()
    panel = SimpleNamespace(tickers=("SYNTH",), adj_close=np.ones((len(dates), 1)))
    feats = np.ones((len(dates), 1, len(mx.NAMES)))
    reaction = dates.index(date(2023, 12, 20))
    quarters = {
        "SYNTH": [
            (date(2022, 11, 30), 100.0, date(2022, 12, 22)),
            (date(2023, 11, 30), 120.0, date(2024, 2, 1)),
        ]
    }
    return panel, dates, quarters, {"SYNTH": [reaction]}, feats


# Keep the row even without a post-reaction return horizon, retaining filing time.
def test_dataset_retains_publication_and_has_no_future_return_requirement():
    short = _inputs()
    long = _inputs("2024-04-01")
    xs, ys, ms = mx._dataset(*short)
    xl, yl, ml = mx._dataset(*long)
    assert len(ys) == 1
    np.testing.assert_array_equal(xs, xl)
    np.testing.assert_array_equal(ys, yl)
    assert ms == ml
    assert ms[0][3] == date(2024, 2, 1)


# Later amendments cannot overwrite a denominator or duplicate the first label.
def test_dataset_ignores_later_amendments_and_keeps_first_report():
    args = _inputs("2024-04-01")
    original = mx._dataset(*args)
    args[2]["SYNTH"].extend(
        [
            (date(2022, 11, 30), 200.0, date(2024, 3, 1)),
            (date(2023, 11, 30), 400.0, date(2024, 3, 1)),
        ]
    )
    changed = mx._dataset(*args)
    assert len(changed[1]) == 1
    np.testing.assert_array_equal(changed[1], original[1])
    assert changed[1][0] == pytest.approx(0.2)


# An unavailable prior-year denominator cannot form an earlier training label.
def test_dataset_rejects_unpublished_denominator():
    args = _inputs("2024-04-01")
    args[2]["SYNTH"][0] = (date(2022, 11, 30), 100.0, date(2024, 3, 1))
    assert len(mx._dataset(*args)[1]) == 0


# Missing publication evidence and contradictory first filings stay unavailable.
@pytest.mark.parametrize(("filed", "value"), [(None, 120.0), (date(2024, 2, 1), 140.0)])
def test_dataset_does_not_guess_missing_or_ambiguous_labels(filed, value):
    args = _inputs("2024-04-01")
    if filed is None:
        args[2]["SYNTH"][1] = (date(2023, 11, 30), value, filed)
    else:
        args[2]["SYNTH"].append((date(2023, 11, 30), value, filed))
    assert len(mx._dataset(*args)[1]) == 0


# Exact annual cutoffs exclude New Year's Day filings and count publication years.
def test_training_cutoff_is_strict_and_year_coverage_is_local():
    available = [date(2021, 12, 1)] * 200 + [date(2022, 12, 1)] * 200
    available += [date(2023, 12, 31)] * 100 + [date(2024, 1, 1)]
    mask = mx._training_mask(np.ones(501), available, 2024, 3)
    assert mask.sum() == 500
    assert not mask[-1]
    assert not mx._training_mask(np.ones(501), available, 2023, 3).any()


# Capture exact model inputs with a deterministic stand-in, never a learner fit.
def _capture_fits(monkeypatch):
    calls = []

    # Return a training-label checksum so future training changes alter predictions.
    def capture(x, y, score, names):
        calls.append((x.copy(), y.copy()))
        return np.full(len(score), y.sum()), None

    monkeypatch.setattr(mx, "_fit_predict", capture)
    return calls


# February publication is excluded from the January fit despite December reaction.
def test_carried_uses_publication_not_reaction_year(monkeypatch):
    calls = _capture_fits(monkeypatch)
    x = np.ones((501, len(mx.NAMES)))
    y = np.r_[np.ones(500), 999.0]
    years = np.full(501, 2023)
    available = [date(2023, 12, 1)] * 500 + [date(2024, 2, 1)]
    out = mx._carried(
        [date(2024, 1, 2)],
        x,
        y,
        years,
        [2024],
        x[:1, None],
        1,
        available_dates=available,
    )
    assert out[0, 0] == 500
    assert len(calls[0][1]) == 500


# Adding future labels cannot turn an under-populated earlier annual fit on.
def test_carried_minimum_is_per_fit_and_future_prefix_invariant(monkeypatch):
    calls = _capture_fits(monkeypatch)
    x = np.ones((510, len(mx.NAMES)))
    available = [date(2023, 12, 1)] * 499 + [date(2024, 2, 1)] * 11
    out = mx._carried(
        [date(2024, 1, 2), date(2025, 1, 2)],
        x,
        np.ones(510),
        np.full(510, 2023),
        [2024, 2025],
        np.ones((2, 1, len(mx.NAMES))),
        1,
        available_dates=available,
    )
    assert np.isnan(out[0, 0])
    assert out[1, 0] == 510
    assert len(calls) == 1


# Appending dates, labels and extreme future values preserves every earlier score.
def test_carried_predictions_are_identical_under_future_extension(monkeypatch):
    _capture_fits(monkeypatch)
    x = np.ones((501, len(mx.NAMES)))
    short = mx._carried(
        [date(2024, 1, 2)],
        x[:500],
        np.ones(500),
        np.full(500, 2023),
        [2024],
        x[:1, None],
        1,
        available_dates=[date(2023, 12, 1)] * 500,
    )
    long = mx._carried(
        [date(2024, 1, 2), date(2025, 1, 2)],
        x,
        np.r_[np.ones(500), 1e9],
        np.full(501, 2023),
        [2024, 2025],
        x[:2, None],
        1,
        available_dates=[date(2023, 12, 1)] * 500 + [date(2024, 2, 1)],
    )
    np.testing.assert_array_equal(short, long[:1])
    assert long[1, 0] != short[0, 0]


# Trailing labels remain valid training rows without writing beyond a return panel.
def test_fifths_keeps_missing_future_outcome_off_panel():
    meta = [(0, i, 2024, date(2024, 1, 1)) for i in range(30)]
    out = mx._fifths(
        np.arange(30),
        np.ones(30, dtype=bool),
        meta,
        np.full(30, 2024),
        [2024],
        (30, 1),
        1,
    )
    assert out[29].any()


# A result filed after the reaction cannot be traded as a known earnings surprise.
def test_after_excludes_surprise_not_published_at_entry(monkeypatch):
    dates = np.arange("2024-01-01", "2024-02-01", dtype="datetime64[D]")
    panel = SimpleNamespace(dates=dates, adj_close=np.ones((31, 1)))

    # Provide already-computed return labels without fetching prices or fitting.
    def forward_residual(horizon):
        return np.ones((31, 1))

    panel.forward_residual = forward_residual
    masks = []

    # Record the measured opportunity masks without performing a study.
    def spread(labels, chosen, rest, horizon):
        masks.append(chosen)
        return 0.0, 0.0, 0

    monkeypatch.setattr(mx, "_spread", spread)
    meta = [(0, i, 2024, date(2024, 2, 1)) for i in range(30)]
    mx._after(
        panel, np.zeros(30), np.zeros(30), np.ones(30), meta, np.full(30, 2024), [2024]
    )
    assert masks
    assert not any(mask.any() for mask in masks)


# A report scored before New Year must use the earlier year's fit cutoff.
def test_expected_uses_actual_score_date_at_year_boundary(monkeypatch):
    calls = _capture_fits(monkeypatch)
    x = np.ones((502, len(mx.NAMES)))
    y = np.r_[np.ones(500), 999.0, 2.0]
    meta_year = np.r_[np.full(501, 2023), 2024]
    available = [date(2022, 12, 1)] * 500 + [date(2023, 6, 1), date(2024, 2, 1)]
    score_dates = [date(2022, 1, 3)] * 501 + [date(2023, 12, 29)]
    out, _ = mx._expected(
        x,
        y,
        meta_year,
        [2023, 2024],
        1,
        available_dates=available,
        score_dates=score_dates,
    )
    assert out[-1] == 500
    assert len(calls) == 1


# Callers without publication evidence must never silently fit by reaction year.
def test_missing_publication_dates_fail_closed(monkeypatch):
    calls = _capture_fits(monkeypatch)
    x = np.ones((500, len(mx.NAMES)))
    with pytest.raises(ValueError, match="publication"):
        mx._carried(
            [date(2024, 1, 2)],
            x,
            np.ones(500),
            np.full(500, 2023),
            [2024],
            x[:1, None],
            1,
        )
    assert calls == []


# The production gap forwards publication dates rather than using a global gate.
def test_live_gap_forwards_publication_to_real_carried(monkeypatch):
    panel, dates, quarters, reactions, feats = _inputs("2024-04-01")
    panel.dates = np.array(dates, dtype="datetime64[D]")

    # Map the only synthetic ticker into its sole panel column.
    def index(ticker):
        return 0

    panel.index = index
    monkeypatch.setattr(mx, "_universe_panel", lambda *a, **k: (panel, {}))
    monkeypatch.setattr(mx, "_records", lambda *a, **k: ({}, quarters, reactions))
    monkeypatch.setattr(mx, "_features", lambda *a, **k: (None,) * 7)
    monkeypatch.setattr(mx, "_block", lambda *a: (feats, np.zeros(feats.shape[:2])))
    calls = _capture_fits(monkeypatch)
    out = challenger.expectations_gap(None, panel)
    assert out.shape == panel.adj_close.shape
    assert np.isnan(out).all()
    assert calls == []
