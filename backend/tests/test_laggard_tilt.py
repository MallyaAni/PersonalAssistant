"""The partial laggard rule stays funded, causal, cash-neutral and research-only."""

import gzip
import json

import numpy as np
import pytest

from backend.cli import market_laggard_tilt as cli
from backend.market import laggard_tilt as study
from backend.tests.test_market_pit_scorecard import _report


# Half of one target is distributed within the existing cap, never into cash.
def test_half_target_redistribution_preserves_cash_and_cap():
    base = np.r_[np.full(6, 1 / 6), 0]
    scores = np.arange(7, dtype=float)
    result = study.targets(base, scores)
    assert result[0] == pytest.approx(1 / 12)
    np.testing.assert_allclose(result[1:6], np.full(5, 11 / 60))
    assert result[6] == 0
    assert result.sum() == pytest.approx(base.sum(), abs=1e-14)
    assert result.max() <= 0.2


# A fully capped book cannot fund redistribution, so the baseline is bit-identical.
@pytest.mark.parametrize("n", [1, 2, 3, 4, 5])
def test_no_headroom_means_exact_baseline(n):
    base = np.full(n, 0.2)
    np.testing.assert_array_equal(study.targets(base, np.arange(n)), base)


# Missing forecasts never acquire a model-implied weight adjustment.
def test_missing_and_ineligible_names_keep_their_weights():
    base = np.array([0.1, 0.1, 0.1, 0.1, 0.0])
    scores = np.array([0.0, 1.0, 2.0, np.nan, -999.0])
    result = study.targets(base, scores)
    assert result[3] == base[3]
    assert result[4] == 0
    assert result.sum() == pytest.approx(base.sum())
    np.testing.assert_array_equal(study.targets(base, np.full(5, np.nan)), base)


# The redistribution clips to actual headroom rather than exceeding the cap.
def test_insufficient_room_limits_the_reduction():
    base = np.array([0.2, 0.19, 0.19])
    result = study.targets(base, np.arange(3))
    np.testing.assert_allclose(result, [0.18, 0.2, 0.2])


# Placebo ordering is deterministic and retains the real forecast's availability mask.
def test_placebo_has_no_price_or_outcome_input():
    values = study.placebo_scores(
        "2020-01-01", ("AAA", "BBB", "CCC"), [True, False, True]
    )
    np.testing.assert_array_equal(
        values,
        study.placebo_scores("2020-01-01", ("AAA", "BBB", "CCC"), [True, False, True]),
    )
    assert np.isnan(values[1])
    assert values[0] != values[2]


# Changing all later forecasts cannot alter a target already decided on this date.
def test_allocator_never_reads_a_future_score():
    report = _report()
    panel = report.panel
    mask = np.ones_like(panel.close, dtype=bool)
    mask[:, -1] = False
    grid = np.tile(np.arange(len(panel.tickers)), (len(panel.dates), 1)).astype(float)
    allocator = study.Allocator(mask, grid)
    original = allocator(report, panel, None, 10)
    grid[11:] = np.nan
    np.testing.assert_array_equal(original, allocator(report, panel, None, 10))


# Actual funded execution and journal replay match `/4` when every forecast is missing.
def test_real_account_fallback_and_nonzero_tilt_reconcile(tmp_path):
    report = _report()
    panel = report.panel
    mask = np.ones_like(panel.close, dtype=bool)
    mask[:, -1] = False
    bundle = {"report": report, "membership": mask}
    missing = np.full(panel.close.shape, np.nan)
    dates, baseline, _ = cli.stock_account(
        bundle, missing, "v4", 0, 25, tmp_path, "test"
    )
    other_dates, unchanged, metadata = cli.stock_account(
        bundle, missing, "sequence", 0, 25, tmp_path, "test"
    )
    np.testing.assert_array_equal(dates, other_dates)
    np.testing.assert_array_equal(baseline, unchanged)
    assert metadata["allocator"]["changed"] == 0
    grid = np.tile(np.arange(len(panel.tickers)), (len(panel.dates), 1)).astype(float)
    _, changed, metadata = cli.stock_account(
        bundle, grid, "sequence", 1, 25, tmp_path, "test"
    )
    _, same_start_baseline, _ = cli.stock_account(
        bundle, grid, "v4", 1, 25, tmp_path, "test"
    )
    assert not np.array_equal(changed[1:], same_start_baseline[1:])
    assert metadata["allocator"]["changed"] > 0
    assert metadata["allocator"]["max_target_cash_difference"] < 1e-14
    assert np.isfinite(changed[1:]).all()
    with gzip.open(tmp_path / "journal-sequence-1-25.json.gz", "rb") as handle:
        journal = json.load(handle)
    assert journal["manifest"]["status"] == "complete"
    assert metadata["reconciled_marks"] == len(panel.dates) - 1


# Price changes at or after today's session cannot relabel today's market regime.
def test_regimes_are_prior_close_only():
    spy = np.linspace(100, 200, 300)
    before = study.regimes(spy)
    spy[250:] *= 0.01
    after = study.regimes(spy)
    np.testing.assert_array_equal(before[:251], after[:251])


# Unregistered cache bytes are rejected before any pickle class can be loaded.
def test_untrusted_cache_is_refused(tmp_path):
    path = tmp_path / "not-a-pickle"
    path.write_bytes(b"not approved")
    with pytest.raises(ValueError, match="hash mismatch"):
        cli.load_cache(path)


# A tie uses ticker-column order rather than an outcome-dependent tiebreaker.
def test_tie_uses_the_first_eligible_column():
    result = study.targets(np.full(6, 1 / 6), np.zeros(6))
    assert result[0] == pytest.approx(1 / 12)
    np.testing.assert_allclose(result[1:], np.full(5, 11 / 60))


# A full synthetic comparison fixes the aggregation and every advancement gate.
def test_summary_and_each_registered_gate():
    import copy

    dates = np.arange("2018-01-01", "2026-01-01", dtype="datetime64[D]")[::2]
    accounts = []
    for cost in (10, 25):
        for offset in range(20):
            for label in ("v4", "sequence", "placebo", "SPY", "QQQ"):
                values = np.full(len(dates), 0.001)
                if label == "sequence":
                    values += 0.0001
                values[0] = np.nan
                accounts.append(
                    {
                        "cost_bps": cost,
                        "label": label,
                        "offset": offset,
                        "dates": [str(day) for day in dates],
                        "returns": values.tolist(),
                    }
                )
    rows = cli.summarize(accounts)
    assert len(rows) == 30
    result = cli.verdict(rows, accounts)
    assert result["label"] == "RESEARCH_PROMISING_NOT_PROMOTION"
    assert result["live_promotion_authorized"] is False
    assert all(result["checks"].values())
    failures = [
        ("2018-2023", "median_cagr", 0.0, "cagr_gain_at_least_one_point"),
        ("2018-2023", "offsets_above_v4", 15, "at_least_16_offsets"),
        ("2024-2026", "median_paired_daily_bp", -0.01, "recent_nonnegative"),
        ("2018-2023", "median_drawdown", -0.02, "2018-2023_drawdown"),
        ("2024-2026", "median_drawdown", -0.02, "2024-2026_drawdown"),
        ("2018-2023", "median_cagr", 0.0, "2018-2023_beats_placebo"),
        ("2024-2026", "median_cagr", 0.0, "2024-2026_beats_placebo"),
    ]
    for window, metric, value, check in failures:
        mutated = copy.deepcopy(rows)
        row = next(
            row
            for row in mutated
            if row["window"] == window
            and row["label"] == "sequence"
            and row["cost_bps"] == 25
        )
        row[metric] = value
        result = cli.verdict(mutated, accounts)
        assert result["checks"][check] is False
        assert result["label"] == "DO_NOT_ADVANCE"
    representative = next(
        row
        for row in accounts
        if row["label"] == "sequence" and row["offset"] == 10 and row["cost_bps"] == 25
    )
    representative["returns"] = (np.full(len(dates), 0.0009)).tolist()
    result = cli.verdict(rows, accounts)
    assert result["checks"]["positive_bootstrap_lower"] is False
    assert result["label"] == "DO_NOT_ADVANCE"
