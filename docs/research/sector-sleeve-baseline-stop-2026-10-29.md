# C5 sector sleeve: stopped at the live-book baseline reproduction (2026-10-29)

**Status: STOPPED before the sleeve.** The pre-registration's live-book stop
condition fired: the current panel's installed `Rule()` baseline does not
reproduce the recorded current-panel baseline within 1e-6. The sleeve leg was not
run, no correlation or 80/20 combination was computed, and no gate was reached.
This is a data-staleness stop, not a failed trading result. The live rule stays
frozen through the 252-session review and nothing here is a live change.

## What ran

- Pre-registration: `docs/research/sector-sleeve-preregistration-2026-10-29.md`,
  committed `7ebe6acb`, before the first run.
- Runner: `~/dsv41/pit2/sector_sleeve.py`; payload
  `~/dsv41/pit2/sector_sleeve.json`; log `~/dsv41/pit2/sector_sleeve.log`.
- PIT cache: `~/dsv41/pit2/cache.npz`, 532 tickers, 2,970 sessions
  2015-01-02..2026-10-23. The 11 sector baskets were built; coverage passed the
  pre-registered stop with room to spare: 142 month-ends, minimum priced members
  Communication Services 12, Energy 16, Materials 18, Real Estate 16, Utilities
  25, Staples 28, Discretionary 33, IT 36, Health Care 40, Industrials 50,
  Financials 53; zero thin months in every sector (a thin month is fewer than 5
  priced members). The coverage stop is false.
- Live-book leg: the current `desk.run` panel, current deploy code,
  `FUNDAMENTALS_CURRENT`, 95 names, 2,970 sessions truncated to 2026-10-23, the
  installed `Rule()` at 10 bp, `policy_book.simulate` with the panel's grades,
  band, tilt and benchmark.

## The baseline does not reproduce

The recorded baseline is `~/dsv41/vision/grade_bc_policy.json` (`book.baseline`),
written by the grade-B/C study on the same panel construction. The current run of
the same construction gives:

| Metric | Recorded | Current | Diff |
|---|---:|---:|---:|
| all CAGR | 33.4031% | **34.3315%** | +0.9285 pp |
| all max drawdown | −28.8464% | **−28.0204%** | +0.8260 pp |
| all Sharpe | 1.3252 | **1.3576** | +0.0324 |
| all total | +2,675.76% | **+2,906.88%** | +2.3113 |
| to_2022 CAGR | 17.3337% | **18.0139%** | +0.6802 pp |
| to_2022 Sharpe | 0.8342 | **0.8644** | +0.0303 |
| from_2023 CAGR | 73.3277% | **74.9457%** | +1.6181 pp |
| from_2023 Sharpe | 2.1606 | **2.1920** | +0.0314 |
| fills | 6,989 | **6,867** | −122 |
| costs | 52,517.73 | **52,633.64** | +115.91 |

The maximum absolute difference is 122 (the fill count), far above the 1e-6
reproduction bar. The equity curve itself changed: every CAGR, drawdown, Sharpe
and total differs, not only the trade count and costs.

## Why

The recorded baseline is stale. The store's prices and fundamentals have updated
since the grade-B/C study wrote `grade_bc_policy.json`, so the same panel
construction now produces a different equity curve and a different set of fills.
The current panel's baseline is the honest current one; the recorded file is a
snapshot of an earlier store state. The C5 sleeve itself is unaffected — it is
built from the frozen PIT cache, and its coverage passed — but the pre-registered
live-book correlation and 80/20 combination are invalid against a stale baseline,
which is exactly what the stop condition is for.

## What this does not change

- The sleeve's definition, signal, scale, costs, starts, placebo and gate are
  unchanged; no sleeve result exists yet.
- The PIT sector baskets and their coverage are valid and can be reused.
- The live rule stays frozen through the 252-session review; no live change, no
  order, no position, no prompt.
- The C5 remains a separate mandate and the owner's decision. This stop buys
  nothing and closes nothing.

## Next

The pre-registration's stop condition forbids a retry without a new
pre-registration saying what changed and why. The only change needed is the
live-book baseline reference: the current panel's installed-rule baseline
(34.3315% CAGR, −28.0204% drawdown, 1.3576 Sharpe, 29.0688 total, 6,867 fills,
52,633.64 costs) replaces the stale `grade_bc_policy.json` snapshot, because the
store's data has moved. The sleeve's parameters and gate stay exactly as
pre-registered. That new pre-registration is committed before the re-run; the
result will be recorded in a separate note.

## Artifacts

- Pre-registration: `docs/research/sector-sleeve-preregistration-2026-10-29.md`,
  committed `7ebe6acb`.
- Runner: `~/dsv41/pit2/sector_sleeve.py`; payload
  `~/dsv41/pit2/sector_sleeve.json`; log `~/dsv41/pit2/sector_sleeve.log`.
- Cache: `~/dsv41/pit2/cache.npz`. Recorded baseline:
  `~/dsv41/vision/grade_bc_policy.json`. Current baseline: the payload's
  `baseline.summary`.
- Runtime: 310.9 s.

## The one number

The current panel's installed rule is **34.3315% CAGR, −28.0204% drawdown,
1.3576 Sharpe, 6,867 fills, 52,633.64 costs**, against the recorded
**33.4031%, −28.8464%, 1.3252, 6,989, 52,517.73**; the maximum reproduction
difference is 122, so the pre-registered live-book stop fires and the C5 sleeve
is not run under this pre-registration.
