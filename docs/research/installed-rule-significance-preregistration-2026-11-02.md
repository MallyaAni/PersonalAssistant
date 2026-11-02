# Pre-registration: is the installed A hold distinguishable from the B hold?

Written 2026-11-02 before the first run of the paired significance analysis.
This is a secondary analysis of two frozen scorecard payloads that already
exist; it runs no new simulation, changes no live rule, order, grade, prompt or
risk dial, and writes no live file. It is the statistical test the program of
record requires for a "top tier" claim: the installed rule has point estimates
but no paired significance result.

Disclosure: the point estimates are already published in the contract
(`grade-led-leader-weight-contract-2026-10-21.md`, revision 7): the A hold
earned 17.1% a year at worst drawdown -34.7% and Sharpe 1.00 on the honest
S&P 500 PIT universe at 25 bp, against the B hold's 14.4%, -38.3% and 0.87.
This note has not computed the paired A-minus-B daily difference, its
Newey-West t, its bootstrap interval, or the per-offset sign count. Those are
the results the run produces.

## Question

Is `grade-led-leader-weight/2` (entry at A, hold while A) distinguishable from
`grade-led-leader-weight/1` (entry at A, hold while B) on the honest S&P 500
point-in-time universe after 25 bp costs, and is any advantage stable across
the 20 offsets and the two reported windows?

The benchmark comparisons against SPY and QQQ are descriptive. The program's
objective names both; the A hold's published claim is a CAGR and Sharpe lead
over SPY and a Sharpe and drawdown lead over QQQ, not a mean-return lead over
QQQ. This study reports the paired mean-return difference against each so the
claim is stated in one place, but it does not turn a benchmark comparison into
a gate for the installed boundary.

## Data

- A hold: `~/dsv41/universe/regrade_broad_value3_ew_graded_leader_forecast_ewma.json`
- B hold: `~/dsv41/universe/regrade_broad_value3_leader_ewma_minB.json`
- Both payloads: 20 offsets, 25 bp, the same dated S&P 500 membership file, the
  same 2,957-session calendar (2016-01-01 through the cache end), and the
  median-offset daily return curves for `rule / point-in-time`, `SPY` and
  `QQQ`. The payloads are frozen; this analysis reads them, not the store.
- The daily curves are simple returns, already net of the payload's 25 bp cost.
  The per-offset `cagrs` arrays in each payload's `rows` carry the 20 offset
  outcomes used for the sign test.

## Statistics

- **Paired daily difference.** At the median offset, `d_t = r_A,t - r_B,t` on
  the sessions both curves price. Report the mean in basis points a day, the
  Newey-West t at lag 20 (`candidate_stats.hac_t`), and a 95% block bootstrap
  that resamples calendar months with replacement (2,000 draws; every session
  in a month moves together, because the strategies share names and regimes).
- **Windows.** 2016-2023, 2024-2026 and all sessions, using the payload's own
  window boundaries.
- **Offset sign test.** The per-offset CAGR difference from the two payloads'
  `cagrs` arrays; count how many of the 20 offsets have A above B. Report the
  median and worst difference.
- **Benchmarks.** The same paired statistics for A minus SPY and A minus QQQ,
  descriptive.
- **Sharpe and drawdown.** The payload's median CAGR, worst drawdown and median
  Sharpe for each line, repeated beside the paired result so the verdict is not
  read from the mean alone.

## Gate

Primary, all sessions at 25 bp:

1. mean A minus B is greater than 0;
2. the Newey-West t is at least 2.0;
3. the bootstrap 95% lower bound is greater than 0.

Robustness, all three must hold for a PASS:

4. the per-offset CAGR difference is positive in at least 15 of 20 offsets;
5. the paired mean is positive in both 2016-2023 and 2024-2026.

If the primary passes and robustness fails, the verdict is PARTIAL: the
advantage is real in the full sample but not stable enough to call established.
If the primary fails, the verdict is FAIL. The benchmark rows do not gate.

## What passing buys

A stronger evidence paragraph in the contract and the handoff: the installed
boundary is not only the best point estimate but is distinguishable from the
prior boundary at conventional significance. No live change; the 252-session
forward record continues and remains the out-of-sample arbiter.

## What failing means

The A hold's historical edge over the B hold is not statistically
distinguishable on this sample. The live boundary stays as installed because
the owner chose it and the forward record is running; the result is recorded
honestly, and the B hold remains the fallback at the 252-session review. A
failure is not retried with a different lag, bootstrap, window or universe
without a new pre-registration saying what changed and why.

## Look-ahead and multiplicity

- The payloads were built with the point-in-time membership mask and the
  next-open fill convention; this analysis adds no data after each decision
  session and reads only the stored curves.
- The A/B comparison is one pre-specified pair, not a search over arms. The
  program has run many arms; the deflated-Sharpe hurdle is reported as a
  descriptive check, with the trial count taken from the program of record,
  not used to rescue a failed paired gate.
