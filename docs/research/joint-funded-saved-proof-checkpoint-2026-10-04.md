# Independent funded-account proof

## Causal regime attribution, October 5

The seven independently verified first-start, zero-cost books were attributed
to the existing causal market-state definition in `neural_study_metrics`.
The next account return uses SPY evidence only through the preceding close:
above/below its 200-close mean and 20-return volatility above/below the median
of 252 trailing volatility observations. These are diagnostic categories,
not a new trading gate, optimized definition or regime-switching policy.

All 2177 return intervals are retained, including the first return from the
January 31 initial cash mark into February 1. Missing states remain explicit;
none are unknown in this original dataset. No portfolio was rerun or refitted.
Mean excess values below are **daily log-return basis points versus the rule**.
Noncontiguous contributions must not be annualized as separate portfolios.

| Prior market state | Intervals | V2 excess | V2 excess after an available ordinary decision | Boosting timing excess |
| --- | ---: | ---: | ---: | ---: |
| Above mean / higher volatility | 731 | -2.98 bp | -1.74 bp | +0.34 bp |
| Above mean / lower volatility | 1045 | -0.20 bp | +1.29 bp | +0.12 bp |
| Below mean / higher volatility | 360 | -7.81 bp | -4.19 bp | -0.61 bp |
| Below mean / lower volatility | 41 | -39.26 bp | -40.50 bp | +3.05 bp |

V2 trails the rule in every full regime. Following available ordinary decisions
it has a modest positive contribution in the above-mean/lower-volatility state,
but not the others. That partition retains the original carried book; it is
not a restarted warmup-free backtest. The 41-interval below-mean/lower-volatility
sample is especially small. Boosting's small positive contributions in several
states do not establish statistically independent edge or a switching rule.

V2's actual end exposure averages 46.8%, 54.2%, 42.5%, 37.9% across those
states, versus the rule's 85.4%, 86.6%, 81.8%, 88.4%. Prior decision states
retain 1714 available ordinary, 257 unavailable ordinary and 206 event-priority
intervals. The final September 30 decision has no later account return and
is correctly absent from this interval attribution. Lower exposure and missing
warmup alone do not establish the cause of the lost growth; available-decision
intervals also lose ground outside the calm rising state.

VERIFIED: existing evaluator 43 tests pass/no skips. A separate scalar
`statistics`/`math` implementation independently reproduces every causal regime
count and all seven books' attributed log growth from the original hash-bound
compressed accounts, without importing the simulator or production evaluator.
Its result covers all 2177 intervals. A first diagnostic adapter attempt failed
before output on ordinary receipts lacking an outer status; corrected only
the adapter to use the original nested receipt. Failed source/log preserved.

Evidence under /home/animallya96/scratch/calibrated-funded-20261005-3a598702:
`proof/saved-regime-attribution.json` SHA
7351c73413551ad37cd81ffa33b40af939262ed97b762dadb2ad163805980d55;
successful diagnostic source SHA
6c1ac7bb160141d7ef0847dbc577ebe3cddc6233bc588040604614acb41f46bc;
independent verification source SHA
44a52298d69ea813b4564090c2c30d6c98eec44a400c4a6b68b92cb9b0a36c2b.
This reused zero-cost, first-start development evidence cannot promote V2 or
choose a favorable regime; the separate calibrated three-cost screen remains
running on its unchanged 3a598702 source. Nonzero-cost/start evidence and a
genuinely prospective carried-book evaluation remain required.

## Current fixed-calendar prefix, October 4

VERIFIED saved arithmetic: two v1 candidate accounts, the first v2 candidate
account and the first five controls. At their proof reads, 58/60 v1, 59/60 v2
and 295/300 control accounts remain pending. This is the registered first
start, not the best start. All three producers remain unchanged and active.

First start2018-02-01 through2026-09-30,2177 sessions,0bp per-side costs,
$100,000 initial cash, carried whole shares and matched corporate actions:

| Method | Total gain | CAGR | Maximum loss | Sharpe | Cumulative turnover |
| --- | ---: | ---: | ---: | ---: | ---: |
| Incumbent rule | 763.51% | 28.34% | 43.09% | 0.993 | 184.21x |
| Boosting timing control | 787.70% | 28.76% | 43.30% | 1.006 | 182.56x |
| Ridge timing control | 711.32% | 27.42% | 43.59% | 0.970 | 182.84x |
| Joint funded v1 | 283.76% | 16.84% | 36.30% | 0.777 | 530.60x |
| Joint funded v2 | 337.21% | 18.62% | 36.30% | 0.813 | 551.10x |
| SPY | 190.50% | 13.14% | 32.59% | 0.772 | 1.00x |
| QQQ | 350.63% | 19.04% | 34.54% | 0.862 | 1.00x |

Boosting and ridge retain the incumbent selection, equal-weight sizing and
grade/reset/FOMC exit plans; they change forecast-driven execution timing.
They are distinct from the joint funded sizing replacement. Boosting's
first full-period result is slightly higher than the incumbent, with slightly
larger maximum loss. It does not dominate: the reused32-session recent window
returned4.24% versus5.37% for the incumbent. Nonzero costs and other starts
are still missing. No parameter change, model refit or live adoption follows
from this first prefix.

Mean end-session exposure is 48.10% for v1, 49.49% for v2 and 85.43% for the
incumbent. The revised model improves on v1 but still trails QQQ and the
incumbent over the full period, with substantially higher turnover. Exposure
and turnover identify differences to investigate; they do not establish that
increasing leverage would recover the lost gain. No live replacement is
justified by these results.

| Method | 2018-20 CAGR | 2021-26 CAGR | Reused recent total gain |
| --- | ---: | ---: | ---: |
| Incumbent rule | 29.35% | 27.83% | 5.37% |
| Boosting timing control | 29.60% | 28.33% | 4.24% |
| Ridge timing control | 28.41% | 26.92% | 4.00% |
| Joint funded v1 | 5.08% | 23.34% | 3.75% |
| Joint funded v2 | 5.08% | 26.18% | 5.77% |
| SPY | 11.89% | 13.78% | -1.42% |
| QQQ | 24.41% | 16.39% | 1.26% |

Source/producer/verifier e396841bb5bdb4218491e0bc3adba96cb804635b. Existing
watcher independently verified original saved bytes, funding, shares, fees,
valuations, calendars and every missing comparison; no accounts were rerun.
Artifact /home/animallya96/scratch/funded-calendar-20261004-e396841b/proof/independent/saved-prefix1.json
SHA b1c5ac41001ad4d5c5b981347ca427b3eca01cb5c3990c4a9abf61949b755c3a.

V2 source/producer/verifier 4daa3bab18a44010d53dd845005678b427bc2cb1.
Its saved-only prefix verification ran once, without simulations or fitting.
Artifact /home/animallya96/scratch/risk-qualified-20261004-4daa3bab/proof/independent/saved-prefix1.json
SHA aa9152a8ea571dcd5ce4d6e23f702ac5034afb28dc515456f5fdded90af06571.
Every first-book window has zero missing NAV marks. V2's reused recent gain
of 5.77% accompanies 7.75% maximum loss and 7.32x turnover, versus the rule's
5.37%, 5.68% and 3.60x. The recent 32-session window is not fresh unseen data;
its higher gain cannot select a regime, threshold or replacement policy.
Later optimizer and persistence fixes are absent from these producer sources
and cannot be credited to their saved economic results.

Saved first-book behavior diagnosis (no refit or replay): v2 has no stock
holdings on 708/2177 sessions versus 5/2177 for the rule. Its first available
ordinary allocation is 2019-03-01; its first held session is 2019-03-04.
Of 1972 unique ordinary decisions, 251 refuse entry risk, 6 refuse numerical
optimization and 1715 are available. Among those available decisions, 396
explicitly target zero stock exposure. The 206 separate event-priority nights
are not counted as fresh model decisions. Thus missing history does not
explain all its cash exposure; deliberate model choices also contribute.

V2 has fills on 1501 dates versus 932 for the rule. Its realized notional is
$94.86 million from ordinary joint allocation changes, $3.08 million from
company exits and $3.55 million from FOMC reduction/restoration. Counts retain
the original 2018 start and all missed opportunities. Zero-quantity expiries
contribute no realized notional; partial fills ending expired still count.
These descriptions do not isolate a causal source of lost return or justify
loosening risk support. Do not trim the evaluation to the first tradable date.

Artifact /home/animallya96/scratch/risk-qualified-20261004-4daa3bab/proof/diagnostics-first-book.json
SHA c91c67244f0dc950a05e8619e5302de0dc5ce664e11e4dceca2f02e4c8a9f524.
Each input compressed account matches its previously verified declared hash.
The diagnostic explicitly separates event-priority metadata from allocation
receipts; it neither scores another account nor changes any producer input.

Saved mean-forecast diagnostic on expanded price support, independent of
grade/trading permission: 171,984 mature rows over 2175 represented dates;
186 missing outcomes remain explicit. Equal total weight per represented
date, exact next-open to following-open arithmetic target. Across the fixed
full period, mean-square error is 2.16% worse than a zero-return forecast;
direction accuracy is 50.31% versus 52.19% for always predicting a positive
return (binary positive versus nonpositive, including flat returns). MSE is
also worse in both registered eras (3.44% and 1.75%). Among
negative forecasts, the realized date-weighted mean return is positive 0.112%
versus the predicted -0.212%. These broad price-support comparisons are not
an executable grade-eligible portfolio test, confidence calibration or fresh
holdout. They do not prove every forecast lacks value or select a replacement.

Original risk NPZ SHA 0332800a54bcbacc963d4f3e67308b99efe1d98a3ba943299774382bc056c5cd;
bridge NPZ SHA b3e6c8445f9e8f6fa3d2618b8193c8fa0031b66bac546c287290c3c3644f4f14.
The diagnostic checks original bytes, grids, causal forecast support, benchmark
exclusion and mature label endpoints before comparing saved means. Native
NumPy 2.5.3; no model fits, estimator predictions or account replay. Archived
analysis/report: risk-qualified-20261004-4daa3bab/proof/mean-skill on Spark.

Next investigate past-only conditional mean calibration before giving these
raw forecasts more capital. Freeze any new specification before its outcomes,
keep all existing producers/source identities unchanged, and retain the original
rule/ETF denominators. Do not lower risk support, invert predictions, optimize
a cutoff from these observations or claim a new policy is live.

These are conditional current-vintage/proxy books, not exact historical live
reconstruction or proven broker/midpoint fills. Dividend claims contribute
to NAV but remain unspendable and unreinvested; ETF results follow that same
account convention. Arithmetic verification is not forecast calibration or
adoption evidence. The full objective remains ACTIVE.

## Earlier checkpoint, different producer source

The earlier figures below belong to their original source/proof, not the
current fixed-calendar cohort above. They remain as historical evidence.

The live replacement remains UNVERIFIED. This checkpoint verifies saved-account
arithmetic and receipt consistency, not predictive accuracy or adoption.

Exact verifier source: e7df67e778d59d470bae6d0fef9ed11287b3b7f6, pushed on
codex/learned-entry-risk-20261002. Starting tree bd3dcced; original main204689db
remains an ancestor and unchanged. Neither active producer was changed/restarted.
No production, UI, model, prompt, schema or deployment changes; diagram impact NONE.

VERIFIED:128 native tests24.93s;149 pinned-source tests19.09s, no skips.
The31 new cases use actual private-account artifacts and reject altered funding,
shares, valuation, fees, grades, policy, clocks, optimizer metadata, projections,
gains, selected/reordered partial indexes, incomplete final reports, future labels,
image/mount substitution and missing benchmark entry. Saved verification succeeds
with simulations and forecasts forbidden. Ruff and diff checks clean.

The existing independent ledger verifier retains its original policy default and
all raw-source/cash/share/fee/corporate-action assertions. An explicit keyword
admits the named candidate; silently relabelling it as the incumbent still fails.
The new saved-only CLI verifies full original producer trees, actual pinned images,
read-only source mounts, original input maps and compressed account bytes. It
rebuilds funded metrics independently and retains every pending start/cost/window.
Unknown wealth paths and unsupported benchmark openings cannot become complete
comparisons. An original control runtime receipt says image_id=unavailable;
actual Docker image identity is separately authenticated, without rewriting it.

First saved-prefix proof VERIFIED seven original accounts, zero candidate accounts;
60 candidate/293 control-method accounts remained pending at this proof's read.
The first0bp/start0 conditional full-period funded gains were rule856.4248%,
boosting827.5677%,ridge833.9933%,SPY190.4951%,QQQ350.6341%; two further start1
policy accounts were checked. These are partial/current-vintage research results,
not a finished cost/start comparison or exact historical live performance.
Every checked account retained all2177/2176 sessions and zero missing held marks.
No candidate gain or advantage has yet been established by this prefix.

Artifacts:
/home/animallya96/scratch/joint-funded-proof-20261004-e7df67e7/proof/
saved-account-proof.json SHA256cf46283333b9c0c2b1cc1b308f0a28ab0a390725d3071e4630ec9d5702442c9f;
tests.log SHA256fc874315296481a43ec4007e05c088c98b6999b8fb519c349c3e34800ad72805.
command.json/evidence.json bind actual producer IDs and mounts. The first launcher
attempt rejected the wrong control manifest path before reading any accounts;
the launcher was corrected to the original manifest.json location. No assertion,
producer source, result or original byte was altered. Successful second evidence
SHA25680d3a80853d5fd9a52189b5b3b4c6a3bfeee392d9fb01c15f7ceac0b1a09d81f;
command SHAb00100bfc23089e9e00fce1ac8414dcf4943081186b795e1e5898dc6a8e52f13.

NEXT: check compact process completion first; independently verify newly completed
candidate/control prefixes from saved bytes in fresh proof outputs, without
account reruns, model fits, threshold/window/start mining or active-source edits.
Compare all original20starts and0/10/25bp against unchanged rule,SPY,QQQ. Preserve
missing metrics and source identities; inspect any first failing boundary rather
than relaxing proof. Complete-book, complete-study and live adoption are separate.
Current-vintage grades/universe, reused recent outcomes, manually reviewed action
declarations, unspendable dividend claims and conditional raw-opening proxies
remain limitations. Neither broker/midpoint fills nor a calibrated confidence
advantage is verified. The full user goal remains ACTIVE.
