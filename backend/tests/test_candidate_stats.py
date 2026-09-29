"""The gate's statistics behave as their papers say on series whose truth is known.

Each test builds returns whose true Sharpe, skill or overfitting is chosen,
so the assertion is about a property the formula must have - not about a
number copied from a previous run.
"""

import math

import numpy as np
import pytest

from backend.market import candidate_stats as cs


# Φ and Φ⁻¹ invert each other across the range p-values live in.
def test_normal_quantile_inverts_the_cdf():
    for p in (1e-9, 0.001, 0.02, 0.05, 0.5, 0.9, 0.975, 0.999, 1 - 1e-9):
        assert cs.normal_cdf(cs.normal_ppf(p)) == pytest.approx(p, rel=1e-9, abs=1e-12)
    assert cs.normal_ppf(0.975) == pytest.approx(1.959963984540054, abs=1e-9)
    assert cs.normal_cdf(0.0) == 0.5
    assert cs.normal_ppf(0.0) == -math.inf and cs.normal_ppf(1.0) == math.inf


# A constant series has a t of NaN, a positive-mean iid series a large t, and
# a 20-session moving window shrinks the naive t by about sqrt(20).
def test_hac_t_counts_overlap():
    rng = np.random.default_rng(1)
    assert math.isnan(cs.hac_t(np.ones(50), 5))
    strong = cs.hac_t(rng.normal(1.0, 1.0, 2000), 0)
    assert strong > 30
    noise = rng.normal(0.0, 1.0, 5000)
    window = np.convolve(noise, np.ones(20) / 20, mode="valid") + 0.05
    naive = cs.hac_t(window, 0)
    hac = cs.hac_t(window, 19)
    assert naive / hac > 2.5  # sqrt(20) ≈ 4.5, shrunk by the Bartlett taper


# The stationary bootstrap covers the series, keeps consecutive rows inside a
# block, and the block length matches its parameter on average.
def test_stationary_bootstrap_keeps_blocks():
    rng = np.random.default_rng(2)
    idx = cs.stationary_bootstrap_indices(500, 20.0, 200, rng)
    assert idx.shape == (200, 500)
    assert idx.min() >= 0 and idx.max() < 500
    steps = (idx[:, 1:] - idx[:, :-1]) % 500
    continuation = float(np.mean(steps == 1))
    assert 0.90 < continuation < 0.97  # 1 - 1/20 = 0.95


# PSR is 0.5 exactly at the benchmark, rises with Sharpe and with length, and
# a fat left tail (negative skew) lowers it at the same Sharpe.
def test_probabilistic_sharpe_moves_the_right_way():
    assert cs.probabilistic_sharpe(0.0, 250, 0.0, 3.0) == pytest.approx(0.5)
    a = cs.probabilistic_sharpe(0.05, 250, 0.0, 3.0)
    b = cs.probabilistic_sharpe(0.10, 250, 0.0, 3.0)
    c = cs.probabilistic_sharpe(0.10, 1000, 0.0, 3.0)
    d = cs.probabilistic_sharpe(0.10, 250, -1.5, 6.0)
    assert 0.5 < a < b < c
    assert d < b
    # Bailey & López de Prado worked example: SR 0.0458 daily-ish over 1250
    # obs with skew -0.72 and kurtosis 5.78 is not yet significant at 95%.
    assert cs.probabilistic_sharpe(0.0458, 1250, -0.72, 5.78) < 0.95


# The expected maximum of N zero-skill Sharpes grows with N and with their
# spread, and is zero for a single trial.
def test_expected_max_sharpe_is_the_hurdle():
    assert cs.expected_max_sharpe(1, 0.01) == 0.0
    ten = cs.expected_max_sharpe(10, 0.01)
    hundred = cs.expected_max_sharpe(100, 0.01)
    wider = cs.expected_max_sharpe(100, 0.04)
    assert 0 < ten < hundred < wider
    assert wider == pytest.approx(2.0 * hundred)
    # Empirical check: the mean of the max of 100 N(0, 0.01) draws.
    rng = np.random.default_rng(3)
    sample = rng.normal(0.0, 0.1, size=(20000, 100)).max(axis=1).mean()
    assert hundred == pytest.approx(sample, rel=0.03)


# Deflation: the same Sharpe is less credible the more trials found it, and
# with one trial DSR equals PSR.
def test_deflated_sharpe_falls_with_trials():
    one = cs.deflated_sharpe(0.1, 500, 0.0, 3.0, 1, 0.005)
    assert one == pytest.approx(cs.probabilistic_sharpe(0.1, 500, 0.0, 3.0))
    ten = cs.deflated_sharpe(0.1, 500, 0.0, 3.0, 10, 0.005)
    thousand = cs.deflated_sharpe(0.1, 500, 0.0, 3.0, 1000, 0.005)
    assert one > ten > thousand
    assert thousand < 0.5  # 0.1 is below the expected max of 1000 tries


# MinTRL is infinite without an edge, finite with one, and shrinks as the
# edge grows.
def test_min_track_record_length():
    assert cs.min_track_record_length(0.0, 0.0, 3.0) == math.inf
    small = cs.min_track_record_length(0.05, 0.0, 3.0)
    big = cs.min_track_record_length(0.15, 0.0, 3.0)
    assert 1 < big < small
    # SR 0.05 per period at 95% needs on the order of a thousand periods.
    assert 1000 < small < 1200


# PBO sits near one half when no trial has skill and near zero when one trial
# has real skill that persists out of sample.
def test_probability_of_backtest_overfitting_separates_skill_from_noise():
    rng = np.random.default_rng(4)
    t, n = 800, 30
    noise = rng.normal(0.0, 0.01, size=(t, n))
    result = cs.probability_of_backtest_overfitting(noise, blocks=8)
    assert result.splits == math.comb(8, 4)
    assert 0.3 < result.pbo < 0.7
    skilled = noise.copy()
    skilled[:, 7] += 0.004  # a Sharpe of 0.4 per period, unmistakable
    assert cs.probability_of_backtest_overfitting(skilled, blocks=8).pbo < 0.05
    with pytest.raises(ValueError):
        cs.probability_of_backtest_overfitting(noise, blocks=7)
    limited = cs.probability_of_backtest_overfitting(noise, blocks=16, max_splits=200)
    assert limited.splits == 200


# A winner that stays best has the top one-based rank even with only two arms.
@pytest.mark.parametrize("reverse_columns", [False, True])
def test_pbo_two_arm_persistent_winner_has_top_rank(reverse_columns):
    noise = np.tile([-0.01, 0.01], 8)
    returns = np.column_stack([noise + 0.04, noise])
    if reverse_columns:
        returns = returns[:, ::-1]
    result = cs.probability_of_backtest_overfitting(returns, blocks=4)
    assert result.splits == math.comb(4, 2)
    np.testing.assert_allclose(result.logits, math.log(2.0))
    assert result.pbo == 0.0


# Equal arms receive the central midrank; the existing <= 0 convention counts ties.
@pytest.mark.parametrize("arms", [2, 3, 4])
def test_pbo_complete_ties_have_zero_logits(arms):
    noise = np.tile([-0.01, 0.01], 8)
    result = cs.probability_of_backtest_overfitting(
        np.tile(noise[:, None], (1, arms)), blocks=4
    )
    np.testing.assert_array_equal(result.logits, np.zeros(math.comb(4, 2)))
    assert result.pbo == 1.0


# Two tied winners of three arms share ranks two and three, not ranks one and two.
def test_pbo_partial_ties_use_average_one_based_rank():
    noise = np.tile([-0.01, 0.01], 8)
    result = cs.probability_of_backtest_overfitting(
        np.column_stack([noise, noise + 0.04, noise + 0.04]), blocks=4
    )
    np.testing.assert_allclose(result.logits, math.log(5.0 / 3.0))
    assert result.pbo == 0.0


# A train winner that always becomes the test loser has the bottom one-based rank.
def test_pbo_reversing_winners_have_bottom_rank():
    noise = np.tile([-0.01, 0.01], 2)
    first = np.column_stack([noise + 0.04, noise])
    result = cs.probability_of_backtest_overfitting(
        np.vstack([first, first[:, ::-1]]), blocks=2
    )
    np.testing.assert_allclose(result.logits, -math.log(2.0))
    assert result.pbo == 1.0


# SPA: a real edge gives a small p-value; a family of zero-mean arms does not
# reject at anything like the nominal rate, and hopeless arms do not dilute a
# genuine one (Hansen's recentring).
def test_superior_predictive_ability_size_and_power():
    rng = np.random.default_rng(5)
    t, k = 1000, 8
    null = rng.normal(0.0, 0.01, size=(t, k))
    p_null = cs.superior_predictive_ability(null, draws=400, mean_block=10, rng=rng)
    assert p_null.p_value > 0.05
    edge = null.copy()
    edge[:, 2] += 0.0025  # 0.25 Sharpe per period
    p_edge = cs.superior_predictive_ability(edge, draws=400, mean_block=10, rng=rng)
    assert p_edge.p_value < 0.01 and p_edge.best == 2
    # Add many clearly-losing arms: the p-value for the same edge must not rise
    # materially, which is the point of the consistent recentring.
    losers = rng.normal(-0.01, 0.01, size=(t, 40))
    diluted = np.concatenate([edge, losers], axis=1)
    p_diluted = cs.superior_predictive_ability(diluted, draws=400, mean_block=10, rng=rng)
    assert p_diluted.p_value < 0.02 and p_diluted.best == 2
    # Empirical size: over repeated null panels, rejection at 5% stays near 5%.
    rejections = 0
    trials = 40
    for i in range(trials):
        panel = rng.normal(0.0, 0.01, size=(300, 5))
        if cs.superior_predictive_ability(panel, draws=200, mean_block=5, rng=rng).p_value < 0.05:
            rejections += 1
    assert rejections <= 6  # binomial(40, 0.05) upper tail; 7+ would be ~1.5%


# With no positive observed statistic, every truncated bootstrap draw meets it.
@pytest.mark.parametrize("case", ["strictly_negative", "zero_mean", "zero_arm"])
def test_spa_nonpositive_observed_statistic_has_unit_p_value(case):
    if case == "strictly_negative":
        differences = np.random.default_rng(12).uniform(-0.02, -0.001, (80, 3))
    else:
        noise = np.tile([-0.125, 0.125], 40)
        differences = np.column_stack([noise, noise - 0.5])
        if case == "zero_arm":
            differences[:, 0] = 0.0
    result = cs.superior_predictive_ability(
        differences, draws=63, mean_block=5, rng=np.random.default_rng(13)
    )
    assert result.statistic == 0.0
    assert result.p_value == 1.0
    assert result.draws == 63
    assert 0 <= result.best < differences.shape[1]


# The one-call verdict carries every field the gate reads and is consistent
# with its parts.
def test_gate_statistics_reports_every_field():
    rng = np.random.default_rng(6)
    family = rng.normal(0.0, 0.01, size=(600, 12))
    family[:, 0] += 0.003
    out = cs.gate_statistics(family[:, 0], family, family - 0.0002, blocks=6, draws=200)
    assert set(out) == {"psr", "dsr", "pbo", "spa_p", "trials", "min_track_record"}
    assert out["trials"] == 12
    assert 0 <= out["dsr"] <= out["psr"] <= 1
    assert out["pbo"] < 0.2 and out["spa_p"] < 0.05
    assert out["min_track_record"] < 600
