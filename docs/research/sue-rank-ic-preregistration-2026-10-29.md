# Pre-registration: SUE rank-IC study on the honest PIT universe

Written 2026-10-29 before any run of the study. This is the C4 rank-IC step from
`top-tier-algorithms-2026-10-28.md`, following the adequate coverage audit
(`sue-coverage-audit-results-2026-10-29.md`, committed `136735e0`). It is an
association study, not a trading rule: no costs, no portfolio, no live use. The
selection overlay is a separate pre-registration and is not run here.

## Question

Does a standardized unexpected-earnings (SUE) measure built from consecutive filings
predict 20- and 60-session forward returns cross-sectionally on the honest PIT
universe? And is the association stable by year, or is it one or two earnings seasons?

## Data

- PIT cache: `~/dsv41/pit2/cache.npz`, the frozen S&P 500 point-in-time cache used by
  C1-C3 and the risk dial: 532 tickers, 2,970 sessions 2015-01-02..2026-10-23. The
  `member` matrix is the session-level membership; `adj_close` is the split-adjusted
  close; `sector` is the sector label; `grades` is the installed rule's grade (used only
  for a diagnostic).
- Filings: the store's `edgar_facts_versions` frames, read with
  `fundamentals_asof.versions_from_frame`. Primary earnings: `net_income`
  (`NetIncomeLoss` and its fallback tiers); secondary diagnostic: `eps`
  (diluted/basic). The five foreign private issuers with no US-GAAP quarterly earnings
  (ASML, FDXF, NBIS, SIMO, TSM) are excluded from the primary sample and stay in the
  denominator; SPY is the benchmark and is excluded.

## Signal

- Quarter series: the earliest filing per period end, quarter spans only
  (`span_kind == "quarter"`, 80-100 days), with a finite value and filing date.
- Seasonal pair: quarter q and the quarter whose period end is 350-380 days earlier.
- Seasonal change: `E_q - E_{q-4}`.
- SUE at quarter q: the seasonal change divided by the sample standard deviation
  (ddof=1) of the prior 4 seasonal changes in the series. Require 4 prior seasonal
  changes. If the standard deviation is zero or non-finite, the SUE is missing (fail
  closed; no fill).
- Decision date: the first cache session at or after `Version.available`. The SUE is
  usable from that session. The SUE value is unitless; higher is a more positive
  surprise.
- The EPS diagnostic repeats the same definitions with `eps`.

## Monthly cross-section (primary)

- Signal dates: the last cache session of each calendar month, January 2016 through
  October 2026. A horizon is used only when `t + h` is inside the cache; months without
  a full window are reported and excluded from that horizon's mean.
- Universe: PIT members at the signal date with a SUE whose decision date is within the
  prior 60 sessions (inclusive), and a finite `adj_close` at t and t + h. If a name has
  more than one SUE in the window, the latest period end wins.
- Forward return: `adj_close[t+h] / adj_close[t] - 1`, h = 20 and 60 sessions. Price
  return, no costs.
- Rank IC: Spearman correlation between the SUE values and the forward returns across
  the cross-section. Require at least 50 names; months below 50 are reported and
  excluded from the mean.
- Yearly statistic: the mean of the valid monthly ICs in the calendar year, the number
  of valid months, and the share of months with a positive IC.
- Pooled statistic: the mean over the valid months 2016-2023 (choosing) and 2016-2026
  (reported), with a 95% block bootstrap over calendar months (2,000 draws, resampling
  months).

## Event-based diagnostic (reported, not gated)

For each SUE observation whose decision date is in 2016-2026 and whose name is a PIT
member on that date: the cross-section at that date is the same 60-session SUE
cross-section; the event name's percentile rank of its SUE is the signal; the forward
return is measured from the event date's close. The IC across events is the Spearman
correlation between the percentile and the forward return, by year and pooled, at 20 and
60 sessions. This is the direct PEAD event test; it is a diagnostic because the events
cluster in earnings seasons and their forward windows overlap.

## Gate (choosing window 2016-2023)

The study passes only if all three hold at both 20 and 60 sessions:

- **G1:** the pooled mean monthly IC is greater than 0 and the 95% block-bootstrap CI
  lower bound is greater than 0.
- **G2:** the real pooled mean is greater than the 95th percentile of 200 placebo pooled
  means, where each placebo permutes the SUE values across names within each month's
  cross-section (seeds from RNG 20261029).
- **G3:** the yearly mean IC is greater than 0 in at least 6 of the 8 choosing years.

The 2016-2026 window, the event-based diagnostic, the EPS diagnostic and all controls
are reported and do not gate.

## Diagnostics (reported, not gated)

- EPS-based SUE: the pooled and yearly mean IC at 20 and 60.
- Sector-neutral IC: within each sector with at least 10 names, the Spearman IC of SUE
  against the forward return; the name-weighted mean across sectors, averaged over
  months.
- Momentum control: the mean Spearman correlation between the SUE and the prior
  120-session momentum (`adj_close[t]/adj_close[t-120] - 1`) across the cross-section;
  the mean IC of SUE against the forward return within each momentum tercile (at least
  15 names per tercile), averaged over terciles and months. This tests whether the SUE
  is just momentum.
- Grade diagnostic: the mean Spearman correlation between the SUE and the installed
  grade at the signal date; the mean IC of SUE against the forward return among names
  graded A/A+ (`grade >= 2`), where the live rule actually buys.
- Cross-section size: the median, minimum and the share of months below 50 names; the
  staleness distribution of the SUE used (median and maximum age in sessions).
- Placebo: the 200 pooled means, their median and 95th percentile, and the best draw.

## Look-ahead controls

- The SUE at a signal date uses only filings whose decision date is on or before the
  signal date; the forward return uses only prices after the signal date; the
  membership is the PIT matrix at the signal date.
- Perturbation: for 100 sampled (name, signal date) pairs, multiply every `adj_close`
  after the signal date by a random factor in [0.95, 1.05]; the SUE values and the
  cross-sectional SUE ranks at the signal date must be identical. Change one SUE value
  by +1 and the IC must change. Report the counts.
- The study reads no live book, no order, no position, and no prompt.

## Stop conditions

- The audit's coverage bar is already met. If the cross-section is below 50 names in
  more than 20% of the months, stop and report before the gate.
- If the SUE is missing (zero or non-finite standard deviation) in more than 10% of the
  candidate observations, stop and report.
- If the gate fails, record it and stop. The arm is not retried with a different
  standard-deviation length, staleness limit, horizon, universe, earnings measure or
  cross-section definition without a new pre-registration saying what changed and why.
- The event-based diagnostic cannot rescue a failed monthly gate; it is reported, not
  gated.

## What passing buys

Only a pre-registration for the selection overlay: the SUE as a sixth analyst or a
rank tilt on the eligible A/A+ set, run through the production policy engine at 10 and
25 bp on the honest PIT universe, with its own placebo and drawdown gate. A pass there
would be a forward-shadow candidate, not a live change. The live rule stays frozen
through the 252-session review.

## Clarifications

- This is not a retry of the tone-surprise study. The tone study failed; SUE is a
  numeric earnings measure with a different information source and a different
  construction.
- The study is an association test. A positive IC does not prove a tradable edge; costs,
  turnover, position limits and the overlay's interaction with the installed grade are
  the overlay's problem.
- Net income is primary because the coverage audit found 342-445 tier C names per
  choosing year; EPS is a diagnostic because its coverage is slightly lower.
- No model call and no prompt; the measure is fully mechanical.
