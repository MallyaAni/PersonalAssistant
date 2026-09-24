# Nested chronological allocation runner — September 24, 2026

## Scope

`nested_ridge.py` and `nested_allocation.py` implement a separate research
experiment runner. It actually fits regression models inside chronological
training windows and chooses settings using earlier funded accounts. It does
not relabel one full-history fit as cross-validation, reset outer capital, or
use the score-only `harness.evaluate_scores` portfolio approximation.

This is machinery acceptance, not a completed historical study. Source assembly,
target derivation, the feature definition, exact `/3`, SPY, QQQ and equal-weight
comparators, and a market-performance evaluation are still required. The output
sets `benchmark_study_complete`, `label_derivation_verified`,
`historical_availability_verified` and `adoption_eligible` to false. No dashboard,
broker, prompt, holdings or adopted-policy arithmetic is changed.

## Declared protocol

The following default protocol was declared before any market-outcome run of
this runner. Synthetic tests may explicitly shorten its geometry; those settings
are returned and hashed rather than masquerading as the default experiment.

- First outer decision: source row 1260; outer blocks: 126 decisions.
- Each outer selection uses three earlier blocks of 126 decisions, with a
  fresh expanding-past fit at each inner block's first decision.
- Ridge penalties: 1 and 100; switching margins: 0 and 0.005, ordered penalty
  first and margin second. Every candidate is retained, including losers.
- At least 504 eligible training rows **per target**; insufficient evidence
  fails instead of manufacturing a cash signal.
- Stock baskets refresh on source rows divisible by 20. The anchor never
  restarts at a fold. The supplied basket must remain identical between refreshes.
- All accounts start with NAV 1, cash only; fees are 10 and 25 bp per traded
  dollar. Zero cash yield and the adapter's single-balance funding convention
  apply. No forced terminal sale.

For an outer start `S`, inner decisions occupy `[S−379, S−1)`, and the last
inner account mark is `S−1`. The three fit indices are `S−379`, `S−253` and
`S−127`. Thus model selection cannot observe the first outer return or mark.
The outer model refits at `S`, using only outcomes already available **before**
that date, then predicts decisions `[S, S+126)` (shortening only at dataset end).
The next outer block starts at the shared `S+126` close.

Each inner candidate has one account across its three inner blocks. Inner
candidates start from cash for comparability; they are not spliced into the outer
account. Selection maximizes the smaller of its two terminal log-wealth changes
at 10/25 bp, with declared candidate order breaking exact ties. This is a
cost-stress selection objective, not regression loss or a claim that the larger
cost always gives the smaller realized return.

Outer models and selected margins may change; actual cash, units, funding
follow-ups and intended allocation do not reset. One combined instruction path
is replayed once at each cost. The no-gate adapter control uses the identical
basket schedule and execution, always selecting the stock sleeve. It is **not**
the exact `/3` comparator: `/3` has its own midcycle entry/exit rules.

## What the model learns

The kernel receives named feature columns and three targets ordered stock, SPY,
QQQ. Values must be real numeric arrays; missing cells remain NaN. Dates must
already be daily `datetime64[D]`, not silently truncated timestamps. Inputs are
copied onto immutable buffers.

The allocation rule assumes the targets are comparable gross forward log-wealth
proxies on one declared horizon; the kernel does not establish this economic
meaning from numbers. A proposed market experiment uses next-open entry at `t+1`
and exit five sessions later at `t+6`. Its fixed-stock-basket gross proxy would be
`log(1−sum(w) + sum(w * open[t+6]/open[t+1]))`, preserving residual cash and
requiring both endpoints for every positive-weight member. That source/label
builder is **not implemented in this checkpoint**. This proxy is not the
adapter's close-sized, delayed-funded realized return. Any market experiment
must freeze and verify its labels and features before running outcomes.

Every feature is masked according to what was available at its **original
decision**, never backfilled when a later fit knows more. Finite values need a
publication date; late-published features become missing. A finite target needs
an actual endpoint after its decision and a publication date no earlier than
that endpoint. Both dates must be strictly before the fit to enter training.
The kernel uses the supplied endpoints, not an assumed `fit_index−horizon` rule.

Each target independently fits median imputation, population mean/standard
deviation and appended, unscaled missingness indicators on its own eligible
rows. An all-missing column uses median zero and scale one; constant columns
use scale one. Regression minimizes summed squared error plus `alpha` times
squared coefficient norm; its intercept is unpenalized. No probability
calibration applies to this return regression. Arithmetic failures refuse the
fit or prediction; they do not produce fallback recommendations.

Cash has forecast zero. The best stock/SPY/QQQ/cash forecast replaces current
intent only when it exceeds that intent's current forecast by the selected
margin. Exact ties retain current intent; otherwise ties among alternatives use
cash, stock, SPY, QQQ order. The margin is a log-return difference, **not** a
calibrated cost estimate, probability or prediction of tomorrow's color. Costs
affect funded results and selection, not separate per-cost instruction paths.
Intent means the chosen sleeve, not temporary cash while a buy awaits funding.

Composition is updated while defensive too. In the existing adapter an update
is a plan trigger, so it can also rebalance an index sleeve. This is deliberate
use of that adapter, not a metadata-only update. Off-schedule account starts seed
the effective basket; ordinary refits do not emit an extra rebalance.

## Evidence and integrity boundaries

Results retain actual per-target eligible/excluded row indices, exclusion reasons,
known/missing masks, fitted feature values, labels and dates, transforms,
coefficients and intercept. Past-only fitted-input/model hashes do not include
future source values. Each outer prediction block has its own fingerprint.
Full normalized input arrays, their dtype/shape/byte hashes and ordered names
are returned separately. Numeric inputs are consumed as float64; these hashes
are not hashes of original vendor files. Full-input hashes correctly change
when a future suffix changes. Model-state and complete audit-receipt hashes
are separate: changing an excluded row's reason can change the receipt while
leaving the actual fitted model unchanged.

Every inner candidate/cost and both outer accounts/costs retain their account
journal, a content hash and independent accounting verification. The separately
named `decision_output_sha256` binds protocol, fits, selections, predictions and
instructions; it is not a hash of every ledger result. No new archive writer or
CLI is included yet. Callers must persist complete returned evidence in a new
non-overwriting research archive before claiming a retained study. These data
are unencrypted research-only evidence, never a place for private holdings,
credentials or personal account identifiers.

Tests must exercise real NumPy fits, funded selection, independent journal
replay, exact boundaries, delayed evidence, immutable inputs, cadence and intent
continuity. Future perturbations compare the relevant earlier fitted state and
actions, not whole-source hash equality. Accounting reconciliation is not an
independent verification of model causality or source claims.

## Remaining market-study gates

The September 18 source inventory contains 2,945 sessions and 94 stock names
plus both index price histories; the pinned original desk report has 95 columns
and must stay unchanged when QQQ is mapped into a separate 96-column panel.
The different September 23 vintage must not be mixed into it. Ragged histories
must remain eligible individually; their all-name intersection has only 225
sessions. The source audit found no complete historical financial-feature rows
or historical membership manifest. Reconstructed prices cannot prove quality,
survivorship freedom or then-known availability.

Before any performance claim: freeze the full source/feature/label specification,
bind and archive it; preserve the unchanged incumbent including its historical
FOMC policy-era boundary; construct funded SPY/QQQ/equal-weight accounts on the
same calendar at both costs; reconcile all journals; and apply the strict
full-sample, rolling and causal-regime scorecards. Previously examined outcomes
remain exploratory. Nested chronological selection does not turn them into an
untouched holdout, guarantee gains, or replace independent prospective evidence.

## Verification of this implementation

VERIFIED: the combined applicable suite passed **674 tests**, with **1**
deliberately deselected completed cached-study reproduction and **5** existing
empty-slice fixture warnings in **5.53 seconds**. New modules contribute
**99** fitting, **45** runner and **4** numeric-boundary cases. Scoped Ruff
and formatting checks pass. Tests run in the local test image
`sha256:63056fccae989b0ef65bb198bc913da58c87648169a50c1e2422b9b3c267d8ca`,
with the exact checkout mounted read-only at `/app`; Python **3.12.14**, NumPy
**2.5.3**. JUnit evidence is
`/private/tmp/anios-nested-demo.ISEibY/acceptance.xml`.

Source SHA256 values:

- Runner: `660a2e61dedaa0fe670dafb4a1af76958a9ed59d43fa1dee492c9f430301f68b`.
- Ridge: `f8f2e840f3f53133e710c24fa28ddb596dfd289b63ea47f25f50b146576e6f21`.
- Runner tests: `827b5926ffc9c468ccbabe017b865fb5fe2c3ce6a5f832809d5c627e61e8f34c`.
- Ridge tests: `3ee6e8332d3a0fec037e29e684d90b3ecddb70ac6f69f317258b9481be873157`.
- Numeric tests: `aef8254f49da8ef6d8b8726426a8fde5d9e2152a33b3c0c42c182047040e0071`.

Reproduced input failures were corrected before this verification: an
extended-precision forecast became infinity after a float64 conversion and was
treated as a stock signal; distinct extended-precision penalties became one
effective candidate. Overflow/underflow checks and post-conversion uniqueness
now refuse these inputs. A separate audit finding split complete receipt hashes
from model-state hashes, so reclassifying an excluded label no longer changes
the claimed identity of an unchanged model.

Full deployment gates and deployed behavior remain UNVERIFIED; no deployment
was requested or attempted. No model server or production database is needed
for this acceptance.

The retained end-to-end demonstration uses **71 artificial daily rows**, not an
exchange calendar, with one initially missing unused asset. It derives causal
price-only features and five-session open-to-open proxy labels, executes
**14 distinct real fits**, two outer folds, all four candidates, **16 inner +
4 outer accounts**, then reloads the saved arrays/receipts and independently
recomputes predictions from saved coefficients. All **20** actual standalone
journal CLI invocations passed; **388** closing marks reconciled. Maximum
residuals: cash **4.9960e-16**, units **3.4694e-18**, NAV **6.6613e-16**.
These are arithmetic residuals on synthetic data, not returns or prediction skill.

Final demonstration: `/private/tmp/anios-nested-demo.ISEibY/run-03/`.
Its manifest covers **150 files / 2,025,660 bytes**, including the exact executed
script and proof log. Manifest SHA256:
`5b1aeea0c29cfafc924dce683b0ba966346e8d370ececc82b67cbf12c066be91`.
All **30** exercised source files match the current checkout. The demonstration
records baseline HEAD `1f361d91` plus exact new-file hashes; it does not claim
that the uncommitted implementation was already contained in that baseline.
The initial failed `run/` remains preserved: its script read a nonexistent
journal event field, a demonstration bug corrected in fresh directories without
changing product code or overwriting the failed evidence.

The complete demonstration history and JUnit are retained on Spark under
`/home/animallya96/anios/data/market/research/nested-allocation-20260924.HdOl1e/`.
All **317 files / 5,202,735 bytes** match local readback hashes, including the
preserved failed first run and final `run-03`. No existing archive was overwritten.

Diagram impact: UPDATED — market-data. All **32** diagram checks and the
published architecture page check pass with pinned Mermaid **11.16.0** and
Playwright **1.61.1**. The automated browser exercised actual page/SVG/source
links, five new labels, node containment and 100/125/300% zoom/reset with zero
page, console or required-request failures. Root inspected the focused branch
screenshot; the new flow is readable and unclipped. Evidence lives at
`/private/tmp/anios-nested-diagram.Cv0T8U/`, with its selected proof/scripts/images
copied to the Spark archive's `diagram/` subdirectory. All 31 unrelated SVG byte
sequences were preserved after rendering. This is documentation acceptance,
not a deployed dashboard or strategy result.
