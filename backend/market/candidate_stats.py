"""Statistics for judging a candidate strategy against the trials that produced it.

Every number in this module exists because a backtest on a universe chosen
with hindsight, tuned across many arms, cannot be read from its Sharpe alone.
The gate in docs/TRADING_VOLATILE_BOOK_ARCHITECTURE.md asks three questions
of a return claim, and this file answers each with one function:

* Is the Sharpe ratio distinguishable from zero once the number of trials
  that were run to find it is counted?  `deflated_sharpe` (Bailey and
  López de Prado, 2014), built on `probabilistic_sharpe` (2012) and the
  expected maximum Sharpe over N trials.
* Would the arm that looked best in sample have been chosen out of sample?
  `probability_of_backtest_overfitting`, the combinatorially symmetric
  cross-validation of Bailey, Borwein, López de Prado and Zhu (2017).
* Does the best of a family beat the benchmark after the search over the
  family?  `superior_predictive_ability`, Hansen (2005), with the stationary
  bootstrap of Politis and Romano (1994).

Plus the two helpers every paired comparison in the repo needs and used to
copy: `hac_t` (Newey-West) and `stationary_bootstrap_indices`.

NumPy only, on purpose: the gate container has no SciPy and no torch. The
normal quantile is Acklam's rational approximation refined by one Newton
step, accurate to about 1e-15, which is more than any p-value here needs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations

import numpy as np

EULER_GAMMA = 0.5772156649015329
_SQRT2 = math.sqrt(2.0)


# The standard normal CDF, elementwise, from the error function.
def normal_cdf(x):
    """Return Φ(x) for a float or array."""
    arr = np.asarray(x, dtype=float)
    out = 0.5 * (1.0 + np.vectorize(math.erf)(arr / _SQRT2))
    return float(out) if np.ndim(x) == 0 else out


# The standard normal quantile: Acklam's approximation plus one Newton step.
def normal_ppf(p: float) -> float:
    """Return Φ⁻¹(p) for 0 < p < 1; ±inf at the ends."""
    if not 0.0 < p < 1.0:
        if p == 0.0:
            return -math.inf
        if p == 1.0:
            return math.inf
        raise ValueError("p must lie in [0, 1]")
    a = (
        -3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
        1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
        6.680131188771972e01, -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
        -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
        3.754408661907416e00,
    )
    low, high = 0.02425, 1.0 - 0.02425
    if p < low:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    elif p <= high:
        q = p - 0.5
        r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
            ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0
        )
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    # One Newton step on Φ(x) - p, using the density.
    err = normal_cdf(x) - p
    pdf = math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)
    if pdf > 0:
        x -= err / pdf
    return x


# --- the two helpers every paired test needs ------------------------------


# Newey-West t statistic of the mean of `x` with `lag` autocovariances.
# A reward or return measured over an h-session window shares h-1 sessions
# with its neighbour, so the naive t overstates the evidence by about
# sqrt(h); lag = h-1 is the usual choice.
def hac_t(x, lag: int) -> float:
    """Return the HAC (Bartlett kernel) t statistic of mean(x); NaN when undefined."""
    v = np.asarray(x, dtype=float)
    v = v[np.isfinite(v)]
    n = len(v)
    if n < 2:
        return math.nan
    centred = v - v.mean()
    variance = float(centred @ centred) / n
    for k in range(1, min(int(lag), n - 1) + 1):
        weight = 1.0 - k / (lag + 1.0)
        variance += 2.0 * weight * float(centred[k:] @ centred[:-k]) / n
    if variance <= 0:
        return math.nan
    return float(v.mean() / math.sqrt(variance / n))


# Resampled row indices for the stationary bootstrap (Politis-Romano 1994):
# blocks start at a uniform random row and end with probability 1/mean_block
# after each step, wrapping around, so the resample keeps the serial
# dependence of the original within blocks.
def stationary_bootstrap_indices(
    n: int, mean_block: float, draws: int, rng: np.random.Generator
) -> np.ndarray:
    """Return a (draws, n) integer array of row indices into a length-n series."""
    if n < 1 or draws < 1:
        raise ValueError("n and draws must be positive")
    p = 1.0 / max(float(mean_block), 1.0)
    out = np.empty((draws, n), dtype=np.int64)
    starts = rng.integers(0, n, size=(draws, n))
    breaks = rng.random(size=(draws, n)) < p
    breaks[:, 0] = True
    for d in range(draws):
        idx = 0
        row = out[d]
        for t in range(n):
            idx = starts[d, t] if breaks[d, t] else (idx + 1) % n
            row[t] = idx
    return out


# --- Sharpe deflation --------------------------------------------------------


# Sample moments the deflation formulas need, from a return series.
@dataclass(frozen=True)
class Moments:
    """Per-period Sharpe and the third and fourth standardised moments."""

    sharpe: float
    skew: float
    kurtosis: float  # raw (non-excess) kurtosis; 3 for a normal
    length: int


# Per-period Sharpe, skewness and kurtosis of a return series (NaNs dropped).
def moments(returns) -> Moments:
    """Return the Moments of `returns`; Sharpe is per period, not annualised."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 3:
        return Moments(math.nan, math.nan, math.nan, n)
    sd = float(r.std(ddof=1))
    if sd <= 0:
        return Moments(math.nan, 0.0, 3.0, n)
    z = (r - r.mean()) / sd
    return Moments(float(r.mean() / sd), float((z**3).mean()), float((z**4).mean()), n)


# Probabilistic Sharpe ratio (Bailey and López de Prado 2012): the
# probability that the true per-period Sharpe exceeds `benchmark`, given
# the observed Sharpe, sample length and the return distribution's shape.
def probabilistic_sharpe(
    sharpe: float, length: int, skew: float, kurtosis: float, benchmark: float = 0.0
) -> float:
    """Return PSR in [0, 1]; NaN when the inputs cannot support it."""
    if not all(np.isfinite([sharpe, skew, kurtosis])) or length < 2:
        return math.nan
    denominator = 1.0 - skew * sharpe + (kurtosis - 1.0) / 4.0 * sharpe**2
    if denominator <= 0:
        return math.nan
    z = (sharpe - benchmark) * math.sqrt(length - 1.0) / math.sqrt(denominator)
    return float(normal_cdf(z))


# The expected maximum Sharpe among `trials` independent tries whose true
# Sharpe is zero and whose estimates have variance `variance` (Bailey and
# López de Prado 2014, eq. 12). This is the hurdle a "best of N" must clear.
def expected_max_sharpe(trials: int, variance: float) -> float:
    """Return E[max SR] over `trials` zero-skill tries; 0 when trials <= 1."""
    if trials <= 1 or not np.isfinite(variance) or variance <= 0:
        return 0.0
    n = float(trials)
    return math.sqrt(variance) * (
        (1.0 - EULER_GAMMA) * normal_ppf(1.0 - 1.0 / n)
        + EULER_GAMMA * normal_ppf(1.0 - 1.0 / (n * math.e))
    )


# Deflated Sharpe ratio: PSR against the expected maximum Sharpe of the
# trials that were run to find this one. `trial_variance` is the variance
# of the per-period Sharpe estimates across those trials; when the trials
# are unknown, pass the count and the observed spread of their Sharpes.
def deflated_sharpe(
    sharpe: float,
    length: int,
    skew: float,
    kurtosis: float,
    trials: int,
    trial_variance: float,
) -> float:
    """Return DSR in [0, 1]: the PSR with the expected-max-Sharpe benchmark."""
    hurdle = expected_max_sharpe(trials, trial_variance)
    return probabilistic_sharpe(sharpe, length, skew, kurtosis, hurdle)


# The track record length at which PSR against `benchmark` reaches
# `confidence` (Bailey and López de Prado 2012, MinTRL). Infinite when the
# observed Sharpe does not exceed the benchmark.
def min_track_record_length(
    sharpe: float, skew: float, kurtosis: float, benchmark: float = 0.0,
    confidence: float = 0.95,
) -> float:
    """Return the minimum number of periods, in the series' own period."""
    if not np.isfinite(sharpe) or sharpe <= benchmark:
        return math.inf
    z = normal_ppf(confidence)
    shape = 1.0 - skew * sharpe + (kurtosis - 1.0) / 4.0 * sharpe**2
    if shape <= 0:
        return math.nan
    return 1.0 + shape * (z / (sharpe - benchmark)) ** 2


# --- probability of backtest overfitting ------------------------------------


# CSCV (Bailey, Borwein, López de Prado, Zhu 2017). `returns` is (T, N): one
# column per trial. The T rows are cut into `blocks` contiguous blocks; every
# way of choosing half the blocks as "in sample" picks the best trial by
# in-sample Sharpe and records that trial's out-of-sample rank among the N.
# PBO is the share of splits in which the in-sample winner ranked in the
# bottom half out of sample; a family with no skill sits near 0.5, and a
# family whose winner keeps winning sits near 0.
@dataclass(frozen=True)
class OverfitResult:
    """PBO and the per-split logits that produced it."""

    pbo: float
    logits: np.ndarray  # one per split; <= 0 means the winner lost OOS
    splits: int


# Sharpe of every column, NaN where a column has no variance.
def _column_sharpe(block: np.ndarray) -> np.ndarray:
    sd = block.std(axis=0, ddof=1)
    with np.errstate(all="ignore"):
        out = block.mean(axis=0) / sd
    out[~np.isfinite(out)] = -math.inf
    return out


# Run CSCV over every half-and-half split of the blocks (or a random subset
# of `max_splits` of them when the count is large) and summarise.
def probability_of_backtest_overfitting(
    returns, blocks: int = 16, max_splits: int | None = None,
    rng: np.random.Generator | None = None,
) -> OverfitResult:
    """Return the OverfitResult for the (T, N) trial-return matrix."""
    m = np.asarray(returns, dtype=float)
    if m.ndim != 2 or m.shape[1] < 2:
        raise ValueError("returns must be (T, N) with at least two trials")
    if blocks < 2 or blocks % 2:
        raise ValueError("blocks must be an even number >= 2")
    t, n = m.shape
    if t < 2 * blocks:
        raise ValueError("too few rows for the requested number of blocks")
    edges = np.linspace(0, t, blocks + 1).astype(int)
    parts = [m[edges[i] : edges[i + 1]] for i in range(blocks)]
    every = list(combinations(range(blocks), blocks // 2))
    if max_splits is not None and len(every) > max_splits:
        picker = rng or np.random.default_rng(0)
        chosen = picker.choice(len(every), size=max_splits, replace=False)
        every = [every[i] for i in sorted(chosen)]
    logits = np.empty(len(every))
    for s, train in enumerate(every):
        test = tuple(i for i in range(blocks) if i not in train)
        train_block = np.concatenate([parts[i] for i in train])
        test_block = np.concatenate([parts[i] for i in test])
        winner = int(np.argmax(_column_sharpe(train_block)))
        oos = _column_sharpe(test_block)
        # One-based average rank for ties, scaled into (0, 1): 1/(N+1)
        # when uniquely worst, N/(N+1) when uniquely best.
        rank = (
            np.sum(oos < oos[winner]) + 0.5 * np.sum(oos == oos[winner]) + 0.5
        ) / (n + 1.0)
        rank = min(max(rank, 1e-9), 1.0 - 1e-9)
        logits[s] = math.log(rank / (1.0 - rank))
    return OverfitResult(float(np.mean(logits <= 0)), logits, len(every))


# --- superior predictive ability --------------------------------------------


# Hansen's (2005) consistent SPA test. `differences` is (T, K): each column is
# a candidate's per-period return minus the benchmark's on the same period.
# H0: no candidate beats the benchmark in expectation. The statistic is the
# largest studentised mean; the bootstrap recentres each candidate by its own
# mean only when that mean is not clearly negative (Hansen's μ̂_c), which is
# what keeps the test from being dragged toward 1 by hopeless arms.
@dataclass(frozen=True)
class SpaResult:
    """The SPA statistic, its p-value and the arm that drove it."""

    statistic: float
    p_value: float
    best: int
    draws: int


# Run the SPA test with `draws` stationary-bootstrap resamples.
def superior_predictive_ability(
    differences, draws: int = 1000, mean_block: float = 20.0,
    rng: np.random.Generator | None = None,
) -> SpaResult:
    """Return the SpaResult for the (T, K) candidate-minus-benchmark matrix."""
    d = np.asarray(differences, dtype=float)
    if d.ndim == 1:
        d = d[:, None]
    if d.ndim != 2 or d.shape[0] < 3:
        raise ValueError("differences must be (T, K) with T >= 3")
    t, k = d.shape
    picker = rng or np.random.default_rng(0)
    means = d.mean(axis=0)
    # Long-run variance of each column's mean via the same block length the
    # bootstrap uses (Hansen uses the stationary-bootstrap kernel; the
    # Bartlett kernel at lag = mean_block is the standard stand-in).
    omega = np.empty(k)
    for j in range(k):
        centred = d[:, j] - means[j]
        var = float(centred @ centred) / t
        lag = int(min(mean_block, t - 1))
        for h in range(1, lag + 1):
            var += 2.0 * (1.0 - h / (lag + 1.0)) * float(centred[h:] @ centred[:-h]) / t
        omega[j] = math.sqrt(max(var, 1e-300))
    studentised = math.sqrt(t) * means / omega
    statistic = float(max(studentised.max(), 0.0))
    best = int(np.argmax(studentised))
    # μ̂_c: keep a candidate's mean in the null only when it is not clearly
    # worse than the benchmark.
    threshold = -math.sqrt(2.0 * math.log(math.log(max(t, 3))))
    keep = studentised >= threshold
    recentre = np.where(keep, means, 0.0)
    idx = stationary_bootstrap_indices(t, mean_block, draws, picker)
    count = 0
    for b in range(draws):
        sample = d[idx[b]]
        boot = math.sqrt(t) * (sample.mean(axis=0) - recentre) / omega
        # Apply the same nonnegative truncation as the observed statistic.
        if max(float(boot.max()), 0.0) >= statistic:
            count += 1
    return SpaResult(statistic, (count + 1.0) / (draws + 1.0), best, draws)


# --- one convenient verdict ---------------------------------------------------


# The three numbers gate H reads for a return claim, from the candidate's
# per-period return series, the (T, N) matrix of every trial in its family
# (the candidate included) and the (T, K) matrix of each family member minus
# the benchmark. Deflation uses the family's own Sharpe spread as the trial
# variance and the family size as the trial count.
def gate_statistics(
    candidate_returns, family_returns, family_minus_benchmark,
    blocks: int = 16, draws: int = 1000, mean_block: float = 20.0,
    rng: np.random.Generator | None = None,
) -> dict[str, float]:
    """Return {"dsr", "psr", "pbo", "spa_p", "trials", "min_track_record"}."""
    mom = moments(candidate_returns)
    family = np.asarray(family_returns, dtype=float)
    trials = family.shape[1]
    sharpes = _column_sharpe(family)
    finite = sharpes[np.isfinite(sharpes)]
    variance = float(finite.var(ddof=1)) if len(finite) > 1 else 0.0
    return {
        "psr": probabilistic_sharpe(mom.sharpe, mom.length, mom.skew, mom.kurtosis),
        "dsr": deflated_sharpe(
            mom.sharpe, mom.length, mom.skew, mom.kurtosis, trials, variance
        ),
        "pbo": probability_of_backtest_overfitting(family, blocks, rng=rng).pbo,
        "spa_p": superior_predictive_ability(
            family_minus_benchmark, draws, mean_block, rng
        ).p_value,
        "trials": float(trials),
        "min_track_record": min_track_record_length(
            mom.sharpe, mom.skew, mom.kurtosis
        ),
    }
