"""Inference-row eligibility cannot depend on a later observed outcome.

The archived CNN producers removed the last observed close and a close before a
missing future session. These tests use the real dataset builders and only
synthetic fixtures: the model inputs stay fixed while future evidence disappears.
Unavailable labels must remain missing, not remove a currently scoreable row.
"""

from dataclasses import replace

import numpy as np
import pytest

from backend.market import deep_intraday as stage1
from backend.market import deep_stage2 as stage2
from backend.tests.test_deep_intraday import CAL, _book
from backend.tests.test_deep_stage2 import K, _world

CUBE_FIELDS = (
    "dates",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "prior_close",
    "auction_open",
    "auction_volume",
)


# Build each real dataset from the same small, deterministic synthetic market.
def _fixture(stage):
    if stage == 1:
        cubes, mask = _book("noise", names=1, n=80, seed=2)
        return cubes, mask, None
    cubes, mask, report, _ = _world(names=1, n=80, seed=2)
    return cubes, mask, report


# Exercise the chosen production dataset builder without model fitting.
def _dataset(stage, cubes, mask, report):
    if stage == 1:
        return stage1.dataset(cubes, mask, CAL)
    return stage2.dataset(cubes, mask, report, calendar=CAL, k=K)


# Retain precisely the selected observed sessions without editing the original cube.
def _cube_rows(cube, keep):
    return replace(cube, **{name: getattr(cube, name)[keep] for name in CUBE_FIELDS})


# Remove every later report observation while preserving all prefix feature values.
def _report_prefix(report, count):
    if report is None:
        return None
    panel = replace(
        report.panel,
        **{
            name: getattr(report.panel, name)[:count]
            for name in ("dates", "open", "high", "low", "close", "adj_close", "volume")
        },
    )
    graded = replace(
        report.graded,
        grades=report.graded.grades[:count],
        votes=report.graded.votes[:count],
        conviction=report.graded.conviction[:count],
        stances={
            name: values[:count] for name, values in report.graded.stances.items()
        },
    )
    regime = replace(report.regime, states=report.regime.states[:count])
    return replace(
        report, panel=panel, graded=graded, regime=regime, scores=report.scores[:count]
    )


# Locate a decision row explicitly so disappearing observations fail at that boundary.
def _row(dataset, day):
    rows = np.flatnonzero((dataset.tickers == "N00") & (dataset.dates == day))
    assert len(rows) == 1, (
        f"Decision row {day} must exist independently of its future label"
    )
    return int(rows[0])


# Compare the actual model inputs, not just the row counts or dates.
def _same_inputs(before, before_row, after, after_row):
    np.testing.assert_array_equal(before.x_seq[before_row], after.x_seq[after_row])
    np.testing.assert_array_equal(
        before.x_scalar[before_row], after.x_scalar[after_row]
    )


# A missing next exchange session changes labels but cannot erase today's inputs.
@pytest.mark.parametrize("stage", [1, 2])
def test_deleting_future_session_preserves_decision_row_and_inputs(stage):
    cubes, mask, report = _fixture(stage)
    cube = cubes["N00"]
    day = cube.dates[39]
    before = _dataset(stage, cubes, mask, report)
    keep = np.arange(len(cube)) != 40
    changed = _cube_rows(cube, keep)
    for name in CUBE_FIELDS:
        np.testing.assert_array_equal(
            getattr(cube, name)[:40], getattr(changed, name)[:40]
        )
    after = _dataset(stage, {**cubes, "N00": changed}, mask, report)
    a, b = _row(before, day), _row(after, day)
    _same_inputs(before, a, after, b)
    assert np.isnan(after.y_return[b]), "Do not relabel the next available day as t+1"
    if stage == 1:
        assert np.isnan(after.y_vol[b])
        assert np.isnan(after.y_rank[b])


# A nonfinite future outcome must remain a missing label rather than a selection rule.
@pytest.mark.parametrize("stage", [1, 2])
def test_nonfinite_future_label_preserves_decision_row_and_inputs(stage):
    cubes, mask, report = _fixture(stage)
    cube = cubes["N00"]
    day = cube.dates[39]
    before = _dataset(stage, cubes, mask, report)
    closing = cube.close.copy()
    closing[40, -1] = np.nan
    changed = replace(cube, close=closing)
    after = _dataset(stage, {**cubes, "N00": changed}, mask, report)
    a, b = _row(before, day), _row(after, day)
    _same_inputs(before, a, after, b)
    assert np.isnan(after.y_return[b])
    if stage == 1:
        assert np.isnan(after.y_vol[b])
        assert np.isnan(after.y_rank[b])


# A complete latest close is scoreable even when no later market observation exists.
@pytest.mark.parametrize("stage", [1, 2])
@pytest.mark.parametrize("count", [20, 40])
def test_truncated_latest_close_is_retained_with_unobserved_labels(stage, count):
    cubes, mask, report = _fixture(stage)
    before = _dataset(stage, cubes, mask, report)
    day = cubes["N00"].dates[count - 1]
    truncated = {
        name: _cube_rows(cube, slice(None, count)) for name, cube in cubes.items()
    }
    prefix_mask = {name: days[:count] for name, days in mask.items()}
    after = _dataset(stage, truncated, prefix_mask, _report_prefix(report, count))
    a, b = _row(before, day), _row(after, day)
    _same_inputs(before, a, after, b)
    assert after.dates.max() == day
    labels = (
        ("y_return", "y_rank", "y_vol")
        if stage == 1
        else ("y_return", "y_rank", "y_downgrade20", "y_drawdown20", "y_vol20", "fwd20")
    )
    for name in labels:
        assert np.isnan(getattr(after, name)[b]), (
            f"{name} fabricated an unobserved outcome"
        )


# Keeping unlabeled rows does not authorize scoring genuinely incomplete current inputs.
@pytest.mark.parametrize("stage", [1, 2])
def test_nonfinite_current_inputs_still_exclude_the_decision_row(stage):
    cubes, mask, report = _fixture(stage)
    cube = cubes["N00"]
    day = cube.dates[39]
    closing = cube.close.copy()
    closing[39, -1] = np.nan
    changed = replace(cube, close=closing)
    result = _dataset(stage, {**cubes, "N00": changed}, mask, report)
    assert not np.any((result.tickers == "N00") & (result.dates == day))


# A missing outcome cannot become the best or sole finite training rank.
def test_rank_labels_preserve_missing_outcomes_and_rank_only_finite_values():
    values = np.array([np.nan, 3.0, 1.0, 1.0, np.inf, 7.0, np.nan, np.nan])
    groups = np.array([0, 0, 0, 0, 0, 1, 1, 2])
    np.testing.assert_allclose(
        stage1.rank_within(values, groups),
        [np.nan, 1.0, 0.25, 0.25, np.nan, 0.5, np.nan, np.nan],
        equal_nan=True,
    )
    assert stage1.rank_within(np.zeros(0), np.zeros(0)).size == 0


# Reload either producer's dataset using its public file format.
def _load(stage, path):
    return stage1.load_dataset(path)[0] if stage == 1 else stage2.load_dataset(path)


# New and legacy files keep distinct row-rule declarations through save and readback.
@pytest.mark.parametrize("stage", [1, 2])
def test_dataset_export_preserves_row_rule_and_never_upgrades_legacy(stage, tmp_path):
    cubes, mask, report = _fixture(stage)
    dataset = _dataset(stage, cubes, mask, report)
    assert dataset.row_selection == stage1.ROW_SELECTION
    current_path = tmp_path / "current.npz"
    if stage == 1:
        stage1.save_dataset(current_path, dataset, None)
    else:
        stage2.save_dataset(current_path, dataset)
    current = _load(stage, current_path)
    assert current.row_selection == stage1.ROW_SELECTION
    np.testing.assert_array_equal(current.dates, dataset.dates)
    np.testing.assert_array_equal(current.y_return, dataset.y_return)
    with np.load(current_path, allow_pickle=False) as saved:
        arrays = {name: saved[name] for name in saved.files if name != "row_selection"}
    legacy_path = tmp_path / "legacy.npz"
    np.savez_compressed(legacy_path, **arrays)
    legacy = _load(stage, legacy_path)
    assert legacy.row_selection == stage1.LEGACY_ROW_SELECTION
    rewritten_path = tmp_path / "resaved-legacy.npz"
    if stage == 1:
        stage1.save_dataset(rewritten_path, legacy, None)
    else:
        stage2.save_dataset(rewritten_path, legacy)
    assert _load(stage, rewritten_path).row_selection == stage1.LEGACY_ROW_SELECTION


# Unknown or shaped provenance is refused rather than silently treated as corrected.
@pytest.mark.parametrize(
    "value", [np.asarray([stage1.ROW_SELECTION]), np.asarray(1), np.asarray("unknown")]
)
def test_dataset_row_rule_rejects_malformed_declarations(value):
    with pytest.raises(ValueError, match="row_selection"):
        stage1.load_row_selection({"row_selection": value})


# Actual ridge fitting scores the last input row without needing its future label.
@pytest.mark.parametrize("stage", [1, 2])
def test_real_fit_prediction_at_truncated_close_is_future_independent(
    stage, monkeypatch
):
    module = stage1 if stage == 1 else stage2
    monkeypatch.setattr(module, "MIN_TRAIN", 20)
    monkeypatch.setattr(module, "REFIT", 10)
    cubes, mask, report = _fixture(stage)
    count = 60
    full = _dataset(stage, cubes, mask, report)
    prefix = _dataset(
        stage,
        {name: _cube_rows(cube, slice(None, count)) for name, cube in cubes.items()},
        {name: days[:count] for name, days in mask.items()},
        _report_prefix(report, count),
    )
    if stage == 1:
        full_values = stage1.walk_forward(full, "ridge", "vol").values
        prefix_values = stage1.walk_forward(prefix, "ridge", "vol").values
    else:
        full_values = stage2.walk_forward(full, "ridge", ("rank",))["rank"].values
        prefix_values = stage2.walk_forward(prefix, "ridge", ("rank",))["rank"].values
    day = cubes["N00"].dates[count - 1]
    a, b = _row(full, day), _row(prefix, day)
    assert np.isfinite(prefix_values[b])
    assert prefix_values[b] == pytest.approx(full_values[a], abs=1e-12)
    assert np.isnan(prefix.y_return[b])
