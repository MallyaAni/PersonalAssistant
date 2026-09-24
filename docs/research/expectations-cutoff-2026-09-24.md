# Preserve the expectations gap's requested data cutoff

## Objective and boundary

An explicit historical `asof` must reach every expectations-gap partition
reader: prices, EDGAR events/facts, release tone and split-adjusted valuation.
Adding later partitions must not change an earlier request's loaded inputs or
deterministic feature arrays. Omitted/None must remain latest; missing older
inputs must remain missing; a stricter `ResearchStore` cutoff must still win.
Plain-rule bypass, unavailable-gap fallback and the plain alternate must remain
unchanged. No learner fit, inference, market backtest, account write or deployment
is part of this acceptance.

Started clean on `main` at `a9a40d352c34c66c08da1ed423da48d0879375e8`;
`git pull --rebase origin main` was current. The three new test modules were
assigned separately; root alone edited production. No unrelated changes were
present. Spark and GitHub independently still matched that published SHA before
the next checkpoint. Preserve Spark's unrelated untracked `scratch/`.

## First failing boundary and targeted change

`desk.run` already passed `asof` to the book and ordinary analysts but omitted it
at `challenger.expectations_gap`. That function and the shared universe/records/
features helpers had no cutoff parameter. The underlying store, panel, tone and
valuation readers already supported it. Valuation independently re-reads filings
and split histories, so fixing only the first record load is insufficient.

Three production files now carry the original optional cutoff through that
chain. The helpers use trailing `asof=None` parameters, preserving existing
positional callers in `market_expectations.main` and `market_interactions`.
No score formula, cohort rule, fit parameter, execution policy or input-data
file changes. Relevant docstrings distinguish this limited vintage bound from
historical causality and qualify the older development-result narrative.

None is deliberately not replaced by the refresh date or last bar date.
`market_daily` passes `args.asof`, which is None for ordinary latest runs. A
newer extraction can have only old price bars and still contain different
filings or reconstructed tone/splits. Each data kind selects its own newest
eligible partition; there need not be a single shared extraction date.

## Reproduced failures

All baselines ran before production edits, with source hashes retained.

- Existing regression: **100 passed / 1 model-fit test deselected**, 28 synthetic
  fixture warnings, 2.24s.
- Actual desk/panel/record path: **6 failed / 3 passed**, 1.29s. A fixed historical
  book remains at 10/11 while the gap panel changes to 90/99 after a future
  partition is appended. Records change, later explicit cutoffs select newer
  data incorrectly, and missing historical inputs are backfilled from the future.
- Actual deterministic feature path: **10 failed / 1 passed**, 1.20s. Three
  failures are numerical, not merely absent keyword support: under the same
  historical cutoff, tone changes **0.25 → −0.75**, log P/S changes
  **0.530628 → −0.855666**, and split-driven market cap changes **680 → 1360**,
  while prices/calendar remain equal. Seven further cases expose the absent
  direct-helper cutoff API.
- Actual desk dispatch/assembly: **6 failed / 2 passed**, 1.95s. Every failure
  occurs at the unchanged-cutoff forwarding assertion; plain bypass, exception/
  all-NaN fallback, real augmentation and alternate identity already pass.

The older 17-assertion reproduction remains untouched. These new synthetic
fixtures do not establish which real securities or predictions were affected.

## Corrected acceptance

The first combined corrected run passes **128 tests / 1 deliberate model-fit
deselection** in 4.63s. Its 71 warnings comprise 60 synthetic all-NaN/empty-slice
warnings from existing regime/level/legacy-fundamental code plus 11 JUnit
`record_property` format warnings. Subsequent runs use `junit_family=xunit1`
to retain the numeric properties in a compatible format, not suppress code
warnings. The final exact-commit regression is recorded separately.

New coverage is 28 cases: nine cutoff, eleven feature and eight dispatch cases.
The cutoff subset passes **9/9 in 1.05s**: historical panel/records stay unchanged,
latest reads the changed vintage despite old bar dates, a later bound excludes
even newer data, missing bars/events/facts stay absent, and `ResearchStore`
retains its stricter cap. All 20 real desk paths stop before feature work;
dataset/carried-model/fit calls are zero.

The dispatch subset passes **8/8 in 1.83s**, preserving bypass, exception/NaN
fallback, actual finite augmentation and plain alternate identity. Cutoffs reach
the boundary unchanged, including None. The feature subset passes **11/11 in
1.18s**, no warnings or skips. It compares
every deterministic output array and NaN position, not just forwarded arguments.
Latest-data controls prove the appended fixtures actually affect calculations.
Missing tone stays None, missing eligible filings withhold all valuation
multiples, and missing eligible split history does not borrow a future split.

The feature tests use the actual `load_tone_features` function AST from the
source-bound `model.py`, compiled unchanged because the local test image lacks
Torch. Actual `MarketStore`, tone decoding, EDGAR conversion, level/split readers
and feature calculations run; feature results are not mocked. This verifies the
pure loader, not importability of the complete Torch model module. The source
hash and mode are recorded in every feature-case JUnit property. No model is
loaded, fitted or called. Ordinary analyst outputs are stubbed in boundary tests;
the dispatch tests separately exercise real desk assembly and augmentation.

Ruff passes for all six changed code/test files. Black passes for the two changed
helper modules and three test modules, and for the modified `desk.run` range.
Whole-file Black already wanted an unrelated line fold in `desk.py` before this
task; that line is deliberately unchanged. Diff checks pass. No UI behavior,
model prompt, API schema, permission or persistence mechanism changed.
Diagram impact: NONE — same data flow, propagated existing argument.

## Retained local evidence

- `/private/tmp/anios-cutoff-acceptance.ZR7RLg/`: existing and combined regression.
- `/private/tmp/anios-cutoff-tests.ZczfXC/`: failed actual-loader baseline/source.
- `/private/tmp/anios-cutoff-final.d9UzSW/`: corrected actual-loader acceptance;
  receipt SHA256 `c0d8efbf0d95d1aba9467feacce1b969692de93a703591f704961ee5ec2cbbc1`.
- `/private/tmp/anios-feature-cutoff.BLdoqTMe/`: failed/corrected feature runs and
  exact source; final receipt SHA256
  `c7256d6e325b0611d01e6d8701c86dcf6c0aa0cf053bed23c4a8f40292004d76`.
- `/private/tmp/anios-expectations-dispatch.ykAW52/`: dispatch/assembly evidence;
  receipt SHA256 `a8dadb9255bd8af6eb7c0b06c62f8745a8288dacd98bfea5a5d70af3a25fc194`.

All runs use isolated synthetic storage, the actual read-only checkout and an
offline image, not production data or a stale deployed source. The root image is
`sha256:63056fccae989b0ef65bb198bc913da58c87648169a50c1e2422b9b3c267d8ca`.

## Still unverified and next work

This fixes **partition selection**, not every meaning of point in time. It does
not filter rows inside a selected vintage, resolve within-vintage revisions,
establish historical membership/sectors or label publication eligibility, fix
future-calendar/global-500 cohort dependence, replace the legacy financial
adapter, or qualify the valuation proxy. `MarketStore.read` returns the whole
selected history; `build_panel` does not impose an upper row-date limit.

The frozen study consumes its original pinned report and is neither rerun nor
repaired. Prediction changes, real affected AAOI/ORCL decisions, return inflation,
live complete-module behavior and strategy profitability remain UNVERIFIED.
Do not present the large reconstructed returns as qualified evidence. Next
atomic work is publication-safe label/cohort construction with future-append
noninterference, followed by immutable release provenance and broader financial
quality. Keep model fitting and strategy promotion out of this repair step.
