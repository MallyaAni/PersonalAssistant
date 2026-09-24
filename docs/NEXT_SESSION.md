# Next session

Standing operator workflow (reconfirmed 2026-09-24): push completed code from
the working checkout to `spark main`; perform live deployment **on Spark**
through `scripts/deploy.sh`; push to **GitHub from Spark**, not directly from
the Mac. A reminder of this workflow does not authorize deploying unfinished
research changes.

## 2026-09-24 — Archive buffering acceptance complete; publication pending

Started clean on `main` at `ebc33159e6546dab066dcbe7f45d84218daee093`;
the initial pull was current. The continuation fetch also shows 0/0 divergence.
Only the archive module, its new serialization tests and associated documentation
are in this checkpoint. Source SHA256
`6417dbd925f6ea9970911d5f49a0fbd1005273e6fdfe38b7268b7f9c609c1a5c`.

VERIFIED: **1,096 passed, one deliberately deselected, five existing warnings**;
33 new serialization cases, independent 90-case byte/hash probe and scoped
lint/format. Same-size **1,131,163,836-byte synthetic metadata pressure** under
3 GiB: old writer OOM/exit137 after full evidence write but before final manifest;
new writer exit0/no OOM, **846 MiB process RSS / 1.89 GiB cgroup peak**.
All **218 manifest entries, 146 arrays, 80 journal files and 20 actual ledger
CLI checks / 544 marks** pass. This bounds document/file buffering, not packed
trees, copied arrays or individual escaped strings.

Full experiment, fixture-age diagnostic caveat and hashes:
`research/archive-buffering-2026-09-24.md`. Local roots:
`/private/tmp/anios-archive-buffering.5HrHog/` and
`/private/tmp/anios-nested-market-acceptance.teTufe/archive-memory-acceptance.doHMXX/`.
The original 634 historical result files were independently rehashed unchanged;
their interrupted producer still has no final manifest. No market rerun,
retuning, new strategy, holdings/order change or deployment.
Diagram impact: NONE — internal archive buffering, unchanged data flow.

Next: finish fresh Spark evidence retention and readback, commit this scoped
checkpoint, push `spark main`, then GitHub **from Spark**. No live deployment.
The user also surfaced an AAOI semantics problem: the fundamental score is
growth/margins, sentiment is dated earnings-release tone, and the composite
A+ is not fair value or entry timing. Source inspection and live API reads
show September23 A+ versus September24 15:30 ET intraday B. The detail panel
can place the evening "Own" summary beside a current grade/price without an
evening date label; its automated browser reproduction is next. Price/book
is cited under Value but does not drive the active score. Correct the
presentation and attribution without silently changing votes or rewriting
historical records. Then continue the historical causality and quality/
membership audit; do not tune another model grid on the rejected study.
Overall goal remains active.

## 2026-09-24 — Frozen history executed; archive OOM; saved-account recovery

Evidence publication checkpoint:
`4ed8e57949a15e56fe6952ec1becd26a0af648bc`, pushed to `spark main` and to
GitHub **from Spark**, with Spark/GitHub divergence **0/0**. All 80 reported
table values, fold/window counts and cited proof hashes match the independently
checked saved results; documentation diff checks pass. This is a verified
evidence/report checkpoint, not successful completion of the OOM-killed
producer or qualification of the strategy. No deployment occurred.

Started clean on `main` at `e749c0af98aa104a04d0b12992e427265f7469e2`.
We did not interrupt or modify the frozen study; after its OOM termination,
`git pull --rebase origin main` confirmed source was current. No production
code, economic parameter, holding, order or live service changed in this task.
The operator workflow above remains mandatory; no live deployment is authorized.

**FAILED:** `market-run-02` ran for 557.66 seconds on the exact clean checkpoint
above, then its child exited `-9`. Docker recorded an `oom` event for container
`89a5985692dc`; the last observed memory use was 7.127 GiB of 7.652 GiB.
All 124 journals and their proofs, source copies, protocol, `evidence.json`,
`summary.json` and `arrays.npz` had been written, but the final root manifest
was not. The precise Python statement at the kill is UNVERIFIED. Do not call
this a successfully completed CLI or manufacture its original manifest.

**VERIFIED:** a new external observer inventoried all **634 saved files /
1,688,236,289 bytes**, then ran all **124 standalone journal CLI checks**.
Every proof equals the saved verification, reconciling **62,668 closing marks**;
the complete file inventory remained unchanged. No strategy was rerun. These
checks prove saved accounting, not the original whole-study completion digest.
Bounded-memory recovery also verifies **874 arrays, 191 source files, 288 price
comparisons, 14 outer folds, 46 unique fit receipts / 138 target fits, 234,186
training-row checks across those fits and 68,556 forecast values**. Forecast
reconstruction error is zero; maximum relative normal-equation residual is
1.26e-14. Peak RSS was
794 MiB under a 3-GiB limit. An independent scorecard check passes **728/728
comparisons** and eight synthetic checks, maximum residual 3.55e-15.

**FAILED economic hurdle:** the new gate loses to `/3` and to its matched
stock-only adapter at both costs. From 2020-01-06 through 2026-09-18, candidate
CAGR is **23.32% / 20.50%** at 10/25 bp, versus **36.29% / 34.65%** without
the gate and **59.23% / 56.40%** for reconstructed `/3`. Funded QQQ is
**20.47% / 20.45%**, SPY **15.27% / 15.24%**. Candidate closing drawdown
**−35.47% / −36.50%** is worse than no-gate **−32.57% / −33.59%**.
It beats `/3` in only **1/14** carried folds and **0/1,433** overlapping
252-session windows at either cost. No promotion or outcome-driven retuning.
These are recovered exploratory outputs, not audited point-in-time quality
returns or reliable live expectations. Full six-account/rolling/regime results:
`research/nested-market-validation-2026-09-24.md`.

Evidence: `/private/tmp/anios-nested-market-acceptance.teTufe/market-run-02/`.
`completion.json` and `oom-observation.json` preserve failure;
`interrupted-files-inventory.json` SHA256
`cc25cd0fa6c304aac227ab4c16a92f4058b00b6c6c1796a064975271eff40204` and
`interrupted-journal-proof.json` SHA256
`5e3fbb34472714e8d8f0aef243600fbc503bcaba6c94b69c648444ffa372163e` are
observer receipts outside the immutable `study/`, not replacement manifests.

Spark retention root:
`/home/animallya96/anios/data/market/research/nested-market-20260924.xEBPm7/`.
All **193 original source files / 192,833,769 bytes** match readback. An old
interrupted rsync left an extra partial; its 78,643,200 bytes were preserved
under `transport-evidence-4k18k383/` before stopping only the two confirmed stale
transfer processes. Rsync removed its own temporary; no original was removed.
All originals match before/after. The separate static acceptance/failed-run/
diagram copy passes **4,199 files / 1,786,630,468 bytes**, zero mismatches;
`static-retention-01/retention-readback.json` SHA256
`7dc92deef299c4d27588021b1761b32b72a8640f9d5965096606696c545ba190`.
The supplemental recovery proofs/scripts/parser distribution pass **42 files /
1,065,977 bytes**, with all **4,392 prior files** rehashed unchanged before/after;
`supplemental-retention-01/retention-readback.json` SHA256
`fd415384fd5cc57a9e66766555bedd739dacd5c38f8336b0a8c6e09717a75294`.
Fifteen volatile parser bytecode files are explicitly omitted; source, native
libraries and licenses are retained. The failed study's root manifest stays absent.

Next: implement bounded JSON/file buffering in archive validation,
with canonical-byte equivalence and memory acceptance; its internal packed
trees must not be mislabeled globally constant-memory. Do not refit or retune
this completed set of saved market outcomes. Then audit the reconstructed
incumbent's historical input availability and sourced quality/membership
coverage before treating its large backtest return as investable evidence.
Historical quality, membership, vendor accuracy and adoption remain UNVERIFIED.
Goal remains active.
Diagram impact: NONE — evidence/recovery documentation; no changed data flow.

## 2026-09-24 — Market assembly and matched study verified; frozen run next

Implementation checkpoint `22eb5c8b0d239700a76bdd98d48d14cf120bbb0f` is pushed
to `spark main` and to GitHub **from Spark**, divergence0/0. The exact committed
source repeated **1,033 passed,1 deselected,5 existing warnings in23.41s**;
proof `acceptance-committed.xml`/`pytest-03/` below. No deployment.

The first real CLI attempt subsequently **FAILED**, before a valid study result,
at an independent buy-scale check. Command/status/logs and exact script remain
in `market-run-01/` under the acceptance folder. It ran8.13s at the checkpoint
above with unchanged protocol and single-threaded CPU BLAS. A passive observer
reproduced and captured the first invalid account in `account-failure-01/`:
`inner:1260:candidate-1:10`, event293,2019-01-24 SPY top-up. Snapshot SHA256
`3035f4b3f468bc3e688c13528c890cb02e3188b4502d2e82aa4fcb8b23d518df`.
Observed/replayed cash differed3.0986e-16, amplified to a2.0197e-9 scale gap
on a1.5342e-7 requested spend. The original scale guard bounded total request,
not discrepancy, and falsely refused ordinary floating-point conditioning.

A targeted verifier correction now requires agreement with
the recorded funding formula and bounds both monetary discrepancy calculations
by the existing1e-12*max(1,NAV). All ledger checks/carry and global tolerances stay
unchanged. The **unchanged captured account now passes379 marks**, including an
actual standalone CLI. Correction acceptance: **1,063 passed,1 deselected,5
existing warnings in26.90s**, including30 new negative/numerical cases; scoped
lint/format pass. Proof `acceptance-scale-02.xml`/`pytest-scale-02/`. No strategy,
label, model setting, execution calculation or cost was tuned. The prepared
external run script now targets fresh `market-run-02/`, which has not run.

Started clean on `main` at `6aadd062052fd13d5f90ae2aff2dd3421b79eb94`;
`git pull --rebase origin main` was current. Prepublication Spark/GitHub check
showed0/0 divergence and only Spark's pre-existing untracked `scratch/`.
No deployment, holding/order change, dashboard or incumbent-policy change.

Implemented `nested_market_sources`, `nested_market_inputs`,
`nested_market_study` and the fixed-protocol `market_nested_study` CLI.
VERIFIED: **1,033 passed,1 deliberately deselected,5 existing warnings** in
24.86s, scoped lint/format and40 actual standalone synthetic journal CLI checks.
Source126/input186/study47 new tests. New receipt/binding guards reject report,
source and conclusion drift, including the reproduced grade mismatch (.15 basket
versus0 changed incumbent). The consumed FOMC CSV and holiday JSON are retained.
No algorithm or protocol parameter was changed after outcomes; **no real-market
fit has run at this checkpoint**.

Actual input assembly:191 source hashes,570 price-field comparisons and2,945
XNYS dates pass; original95-column report preserved, separate96-column execution
panel,22 gate features,2,939 raw/2,739 eligible-after-warmup labels per target.
First outer session2020-01-06. Q/TYL terminal OHLC-envelope anomalies remain
explicitly flagged and unrepaired; fetches were after the verified final close.
Historical report causality, membership, quality completeness and adoption remain
unverified. The gate is price-only, not a financially qualified stock selector.

Protocol: `research/nested-market-study-2026-09-24.md`, SHA256
`11898d28ad41c8e625a54a56f604b7daac508a91bc85dc6ba1a3ac4cfffec483`.
Exact source hashes, runtime and acceptance:
`research/nested-market-validation-2026-09-24.md`.
Evidence: `/private/tmp/anios-nested-market-acceptance.teTufe/`;
final JUnit `acceptance-02.xml`, synthetic archives under `pytest-02/`.
Source-loader proof SHA256
`6de5cd2501506361545b67f7c94e0936c3f64b087cd0a73b1c4fff0734b64515`.
Pinned local inputs: `/private/tmp/anios-nested-market-inputs.nsm4Sm/`.
Optional research dependencies: `/private/tmp/anios-nested-calendar.MeavxY/`,
mounted `/deps` with `PYTHONPATH=/deps:/app` in the existing local test image.

Diagram impact: UPDATED — market-data. All32 diagram/page checks,19 browser
labels,7 node-containment checks, SVG/source links and100/125/300% zoom pass,
zero page/console/request failures;31 unrelated SVGs preserved. Root inspected
the research branch. Evidence `/private/tmp/anios-market-study-diagram.i2IPJH/`.
Deployment gates and deployed acceptance remain UNVERIFIED.

Next: publish the verified checkpoint to Spark and GitHub **from Spark**, then
run the frozen real-history CLI once. The prepared external attempt logger
`/private/tmp/anios-nested-market-acceptance.teTufe/run-frozen-study.py` retains
stdout/stderr/status in fresh `market-run-01/` even on failure. It has not run.
Reconcile every real account and archive hash before reading outcomes; retain
losers without retuning. Archive local evidence and the trusted report on Spark.
No live deployment is authorized or underway. Overall goal remains active.

## 2026-09-24 — Nested fitting/selection machinery verified; source study next

Verified implementation checkpoint:
`a560018eb61c0a6f19281509c9638d730bc0de9d`, pushed to `spark main`, then to
GitHub by `git push origin main` **on Spark**. Spark/GitHub divergence is **0/0**.
The exact committed implementation repeated the applicable suite: **674 passed,
1 deliberately deselected, 5 existing warnings in 5.29 seconds**. The worktree
was clean after that implementation commit; this handoff is the follow-up.
Spark retains only its unrelated untracked `scratch/`. No deployment occurred.

Started clean on `main` at `1f361d91aa8c229007d4eed9860f8f59591f893d`;
`git pull --rebase origin main` was current. User reconfirmed that live deployment
and GitHub publishing run from Spark. No live model, database, holdings, order,
dashboard or adopted `/3` policy was changed. No completed losing study was
retuned or rerun. New fits were on synthetic data only.

Atomic objective achieved: actual inner chronological model fits and funded
selection, followed by one continuous outer stock/SPY/QQQ/cash account. New
`backend/market/nested_ridge.py` owns immutable dated `RegressionInputs`, fits
three separate real NumPy ridge regressions, and retains exact training rows,
known/missing masks, values/dates, transforms and coefficients. Features are
masked at their original decision; both actual label endpoint and publication
must precede fitting. Each target owns its own transform. Model-state hashes
exclude dropped-row classifications; complete receipt hashes preserve them.

`nested_allocation.run(panel, regression, stock_weights, protocol=...)` performs
every inner fit and every candidate/cost account. Defaults: first outer1260,
outer126, three inner126 blocks, min504 rows per target, penalties1/100 and
switch margins0/.005. At outer startS, inner decisions `[S−379,S−1)` end at
markS−1; the selected outer model then refits atS. Selection maximizes the
worst 10/25-bp terminal log wealth, stable declared-order ties. Forecasts are
comparable gross log-wealth proxies, not red/green probabilities; calibration
is none. The margin alone governs switching; actual costs belong to accounts.
Intended mode carries across refits; account cash/units/funding state never
reset. Global stock composition cadence is source-row `%20==0`; an update can
also rebalance a defensive index sleeve. The stock-only no-gate adapter control
is not a substitute for the exact incumbent.

VERIFIED: **99** ridge, **45** runner and **4** numeric-boundary cases in the
combined **674** suite; scoped lint/format. Real coefficients independently
reconstructed with augmented least squares; actual churn costs select a
non-first candidate; next outer prices cannot alter earlier selection. Tests
cover delayed evidence, non-interference, margin/intent continuity, funding
retries through folds, ragged unused prices and fail-closed arithmetic.
Reproduced extended-precision overflow/duplicate-grid bugs were fixed before
freeze. No strategy-level economic improvement is claimed.

Final retained synthetic journey:
`/private/tmp/anios-nested-demo.ISEibY/run-03/`. **71 artificial daily rows,
14 distinct real fits, 2 outer folds, 16 inner + 4 outer accounts**; all **20**
standalone journal CLI checks passed and **388** close marks reconciled.
All **150** final-demonstration files (2,025,660 bytes) and **30** exercised
source hashes match. The initial script failure (`kind` instead of the actual
event `type` field) remains preserved; it was not a product failure.
Full history + JUnit retained on Spark:
`/home/animallya96/anios/data/market/research/nested-allocation-20260924.HdOl1e/`.
All **317 files / 5,202,735 bytes** matched readback before the separate eight
diagram evidence files were added; those eight also matched. No overwrites.
Exact source/image hashes, APIs and limitations are in
`research/nested-allocation-runner-2026-09-24.md`.

Diagram impact: UPDATED — market-data. All **32** diagrams/page checks and
the actual documentation browser journey pass (new labels, node containment,
SVG/source links, zoom/reset, no page/console/request failures). Root inspected
the focused branch. Only the changed diagram and published page retain render
changes; 31 unrelated SVGs remain byte-identical. Evidence:
`/private/tmp/anios-nested-diagram.Cv0T8U/`, selected files under the Spark
archive's `diagram/`. Isolated pinned Mermaid11.16.0/Playwright1.61.1 were
needed because host node_modules had drifted; no dependency files changed.
Full deployment gates and deployed acceptance remain UNVERIFIED.

Next substantive task: **freeze and implement the market source/label assembly
and full comparator study**, not another synthetic-account adapter. The runner
returns normalized source arrays, receipts and journals in memory, but has no
general archive writer/CLI yet. Its `label_derivation_verified`,
`benchmark_study_complete`, historical-availability and adoption flags remain
false. Before a market-outcome run, freeze features, economically comparable
labels and source fingerprints, archive all outputs without overwriting, and
include exact `/3`, no-gate adapter, funded SPY/QQQ and equal weight at both
costs on one calendar. Apply the existing strict wealth/rolling/causal-regime
scorecards; never use `harness.evaluate_scores` for funded accounting. Do not
equate the adapter's cadence with the separately implemented daily funded index
controls. Already examined history remains exploratory, not a new untouched test.

Read-only source inventory, verified this turn on Spark:

- Trusted original report:
  `/tmp/codex-trading-evaluation-inputs-20260921/corrected-exposure-report.pickle`,
  SHA256 `d6f8fe0cbf74e7318352b8e9c02910cae00164a2a4900be6a8e24a9960401c26`.
  Verify before unpickling. **2945 sessions ×95 symbols**, 2015-01-02 through
  2026-09-18, 94 stocks+SPY, no QQQ. Keep this incumbent report unchanged.
- Same-vintage QQQ:
  `/home/animallya96/anios/data/market/bars/asof=2026-09-18/QQQ.parquet`, SHA256
  `e496f36ebe70fd5ddbe25115cc44883b3c690b2fa71438436468725f37d55cd3`.
  Build a separate96-column execution panel and map stock compositions; do not
  append a column to mismatched95-column grades/scores. **191/191** Sep18 source
  and benchmark hashes match. Adjusted open is derived open*adjusted_close/close.
- 64 names cover the full grid;32 start later. No duplicate/interior missing
  or invalid stored price rows per asset. All-name intersection starts only
  2025-10-27 (225 sessions): preserve individual ragged eligibility.
- Sep23 learned-price arrays are a different vintage with52 missing Sep22 rows;
  their declared complete prefix is Sep21. Do not mix them with the Sep18 report.
  Neural archives have features/labels, not full execution prices.
- Historical membership manifest and prospective `learned_inputs` are absent;
  all10 preserved financial feature channels have zero finite values. The
  SEC cohort has2160 rows/720 sessions/zero complete-feature rows. Raw SEC facts
  exist, but sampled versioned acceptance timestamps were blank. Nothing here
  qualifies historical quality or survivorship freedom. No source copy/download
  or real-data fit occurred this turn.
- The incumbent `event_risk.live_path` intentionally applies its FOMC reduction
  only from2026-06-18; earlier history is current-rule stress testing. Preserve
  this policy-era boundary instead of silently extending the current rule.
- Spark research Python: `/home/animallya96/research-venv/bin/python`; NumPy2.5.2,
  pandas3.0.6, PyArrow25, sklearn1.9.1; exchange_calendars absent. Local test
  container includes the checkout dependencies. No inference/GPU service change
  was made. Spark lacks `rg`; use a read-only fallback there.

Goal remains active: implemented validation machinery is progress, not proof of
the best strategy. Historical quality/cohort completeness and independent
economic validation remain outstanding.

## 2026-09-24 — Zero-safe stock/SPY/QQQ/cash adapter verified; nested runner next

Verified implementation checkpoint:
`dd1a871bc3d925153b15daaf0fa50d86fd6563a6`, pushed to `spark main`, then to
GitHub by `git push origin main` **on Spark**. Both remote main branches match;
Spark/GitHub divergence is **0/0**. The local worktree was clean after commit;
only Spark's pre-existing untracked `scratch/` remains there. No deployment.
The exact implementation source passed the 526-test acceptance and eight
archive/CLI journeys recorded below; its source hashes match the retained proof.

Prior goal turn was progress: journal checkpoint `fe74e82` and handoff `8f124d6`
were verified and synchronized. This turn started clean on `main` at
`8f124d6c3cf5fb5f6c676bd4b4a1fb65b5b7c2d1`; `git pull --rebase origin main`
was current. Pre-checkpoint Spark/GitHub fetch again showed zero divergence;
Spark's unrelated untracked `scratch/` was untouched. No live deployment.

Atomic objective: safely execute externally supplied stock/SPY/QQQ/cash
instructions with a stable unscaled stock composition, complete zero exits,
close-time sizing, next-open funding and independently replayable accounting.
Implemented in the separate `backend/market/allocation_replay.py`; no incumbent
planner, simulator arithmetic, dashboard, broker or model prompt changed.
The first failing boundaries were verified in the old paths: zero rejected,
relative restoration divides by prior scale, and tiny zero-target holdings can
survive both planners. The new adapter reuses only `_Book._fill`, with explicit
ending-unit targets and no suppression threshold.

VERIFIED: **526 passed, 1 deliberately deselected, 5 existing warnings in
4.13 seconds**. The new suites contribute **234** cases: 76 behavior, 158
validation. All successful main paths independently replay their journal;
recording enabled/disabled outputs match. Future instruction/price perturbations
preserve earlier decisions and states. Eight actual archive/CLI journeys
(switching, no-gate, SPY, QQQ at 10/25 bp) reconcile **72** closing marks.
Prices and instructions are synthetic, not a new market-performance result.
Scoped lint/format pass. Full deployment gates remain UNVERIFIED.

New adapter source SHA256:
`c8dfcf93de108f1fbed615a0609470a60590e89dceb4f798237b6483f9841f15`.
Behavior tests: `83255f02a872acc08a1f229df28fde6e9278401bca903d8da63d6f6266514a79`.
Validation tests: `cfba49c3a81b04599e263d0eb2aeba80cf41ce5fac45f20ba52bd9c1b9b6b54a`.
Runtime image and complete semantics are in
`research/allocation-adapter-2026-09-24.md`. Final demonstration:
`/private/tmp/anios-allocation-verified.1fg7Mp/`, retained on Spark at
`/home/animallya96/anios/data/market/research/allocation-adapter-20260924.3sVFrv/`.
All **30 files / 135,475 bytes** match after readback. No overwrite. Largest
residuals: cash/NAV 4.44e-16, units 3.47e-18.

Two additional new-adapter defects were reproduced and corrected before freeze:
complex prices discarded imaginary components, and an unordered ticker set
silently changed column identities. Real numeric source arrays and ordered
symbol sequences are now required. Nonfinite/negative cash, units or traded
notional are refused. A stock scale is a multiplier, so base 0.2 at scale 1 plus
SPY 0.8 is valid; actual composed exposure, not scale+indexes, is bounded by one.

Receipts use `earliest_execution_session`, never claim it is an actual fill, and
hold-only rows have `submitted_units: null`. The full instruction path/hash and
the consumed row/composition session are retained; information dates and source
IDs remain unverified declarations. The journal CLI reconciles accounting, not
instruction-sidecar hashes, causal model fitting or policy/retry semantics.
There is no real settlement, market-impact/volume or cash-yield model. `/3`
remains incumbent; no holdings/orders, completed studies or model fits changed.

Diagram impact: UPDATED — market-data. All **32** diagram checks and the
published-page check pass. Automated browser acceptance verified the adapter
label, containment, source links and zoom with no page/console/request errors;
root inspected screenshots. Evidence:
`/private/tmp/anios-allocation-diagram.zjzsQP/`. This verifies documentation,
not a newly deployed dashboard. Unchanged-source SVG generation diffs were
normalized away; only market-data.svg and architecture.html changed.

Next substantive task: freeze and implement the nested chronological runner.
It must retain outer/inner boundaries, actual training row and matured-label
availability sets, train-only transforms/calibration, inner-only model/gate
selection and frozen fit/output hashes. Feed a single continuous instruction
path to this adapter rather than resetting capital at fold boundaries; attach
and independently verify every account journal. Retain exact `/3`, a no-gate
adapter control, funded SPY/QQQ and equal weight at both 10/25 bp on the same
calendar. Do not use `harness.evaluate_scores` for portfolio accounting: it
filters by available future outcomes and is not a delayed funded ledger.

Read-only data audit: no local `data/market` tree. The preserved study copy at
`/private/tmp/anios-chronological-artifacts.p1zCAB/` has reconstructed 95-name
features and labels but only SPY's parquet, not the full execution-price set.
Remote input availability must be inspected before a new run. The SEC cohort
still has zero complete-feature rows; it is not training-ready. Already examined
history remains examined research; neither fold geometry nor a successful
synthetic account makes it untouched validation. Goal remains active.

## 2026-09-24 — Research account journal verified locally; deployment not requested

Verified implementation checkpoint:
`fe74e8265881528f355bd3f3c4df7e4e73d66622`, pushed to `spark main`, then to
GitHub by `git push origin main` **on Spark**. Both remote main branches match;
Spark/GitHub divergence is **0/0**. Local working tree was clean after commit;
Spark retains only its pre-existing untracked `scratch/`. No deployment occurred.
The final applicable suite repeated on the exact checkpoint source:
**292 passed, 1 deliberately deselected, 5 existing warnings in 3.86 seconds**.

Started clean on `main` at `128a5d51e41af23dd23f22fd9cfcb993ce19ed8b`;
`git pull --rebase origin main` was current. The user reconfirmed Spark-only
deployment and GitHub publishing. Spark was eight commits ahead of GitHub and
zero behind; `git push origin main` **on Spark** synchronized GitHub to that SHA
with zero divergence. The unrelated untracked Spark `scratch/` was untouched.

Atomic objective: observe existing research execution without changing it and
independently reconstruct every account. Implemented `ResearchJournal`, the
independent replayer and read-only `market_verify_journal` CLI; attached optional
observation to `simulate.run`, `_Book`, `learned_research.replay` and funded
`constant_exposure` controls. No default recording, broker/API/model integration,
holdings mutation, study rerun or strategy retuning. `/3` stays incumbent.

VERIFIED: final combined **292 passed, 1 deselected** (only the completed
cached-study reproduction), with five existing All-NaN/empty-slice fixture
warnings; scoped lint/format; five actual fresh archive/CLI journeys, all exits
0 and all **32 close marks** independently reconstructed. Runtime was the exact
checkout mounted read-only, not stale baked source. Source/image hashes,
artifact paths, numerical tolerance and complete semantics are in
`research/accounting-journal-2026-09-24.md`. Largest demonstration residuals:
cash 2.60e-16, units 1.74e-18, NAV 4.44e-16. Prices are synthetic; none of those
numbers is performance evidence. Host Ruff was unavailable; the image passed.
The demonstration and runner are preserved on Spark at
`/home/animallya96/anios/data/market/research/accounting-journal-20260924.0fgNNN/`;
all **16 files / 54,258 bytes** match local readback hashes and sizes. No existing
archive was overwritten.

The recorder never executes. Its archive freezes full price arrays and preserves
actual pending state without liquidating. The replayer never resets its ledger
to reported balances. Holds are observations, not trades; `complete` is recording
status, not an accounting verdict; missing held valuations remain explicit and
fail independent verification. Pending policy semantics, historical availability,
security identity, actual settlement and adoption readiness remain unverified.
The JSON is research-only and unencrypted, never a store for personal holdings.

Reproduced and resolved one numerical boundary: fully invested zero-cost ETF
rounding makes sub-ULP buy-scale ratios unstable. Only the scale comparison may
use a currency-level exception when both reconstructed and reported requested
spend are <= 1e-12 * max(1, NAV). Cash/unit/fee checks stay strict; material
tampering and accumulated drift have tests. No producer arithmetic changed.

UNVERIFIED: full deployment gates and deployed acceptance, real-data journal
studies and strategy improvement. No deployment occurred. Diagram impact:
UPDATED — market-data. All **32** diagram fingerprint/syntax checks and the
generated architecture page check passed. An automated browser exercised the
actual SVG and page, verified new labels/source links and 125%/100% zoom, with
zero page/console/network errors. Root inspected the rendered branch and page;
no clipping or overlap. Screenshots and browser evidence are retained at
`/tmp/anios-journal-diagram.h96L70/`. Only the changed source's SVG and published
architecture page retain generation diffs; unrelated SVG bytes were preserved.

Next atomic work: a research-only zero-safe stock/SPY/QQQ/cash adapter with
explicit full liquidation and stable unscaled stock composition for restoration.
The existing simulator rejects zero exposure, divides by prior exposure and can
retain tiny positions via `planner.target_shares`; do not loosen a validation
check and call that cash switching. Then freeze bounded nested chronological
selection, inner-only preprocessing/calibration/threshold choice and matured
purged labels, with future-input perturbation tests and every account journaled.
Keep exact `/3`, an identical no-gate adapter control and funded SPY/QQQ at
10/25 bp. Already examined history remains examined; the three-name historical
cohort demonstration is not training-ready. Goal remains active.

## 2026-09-24 — Single stock list verified and pushed; research continues

Objective: remove the duplicate **Every grade in detail · diagnostic view**
universe while preserving unique diagnostics, source clocks, search/sort/filter
controls, owner-only confirmed-fill recording and legacy detail links. This
follow-up began on `main` after history/cohort checkpoint
`16cb39426a6e253ec8dc7290e40a45e38718186f`. Only the task's three frontend files
were pending; the earlier staged history/cohort tree was committed separately.

Implementation checkpoint: `e65eb334b67e945cb838f271f99b946755bf619e`, pushed to
`spark main` and verified against the remote branch. No deployment occurred.

VERIFIED: **106/106** Desk Playwright tests in **1.1 minutes** against the
checkout mounted into Playwright 1.61.1 with its own Vite server; production
TypeScript/Vite build; targeted compact/mobile acceptance; clean diff. Tests
exercise one stock list, row diagnostics, quote/research expiry, explicit zero
targets, role restrictions, and persisted confirmed shares/entry price after
reload. They use deterministic API fixtures, not the production account.
Desktop board top stays **323.5 px** against the unchanged **<340 px** bound;
the compact fixture's visible words fall from **464 to 359**. Phone commentary
and the complete fill form have viewport ratios of **1**, form fields fit the
board and horizontal scroll stays **0**. Root inspected both phone screenshots
and independently checked these final source hashes:

- DeskPanel.tsx: `6a5164ec4b1224d9109a5a26032db20f2149a9289cfe5e93b0a2d4cc81903441`.
- StockBoard.tsx: `c908dea96645da7b0e99c924a745e688a8de38c8ceafc57a3475f65caafe41a0`.
- desk.spec.ts: `7da70c869a93828ccfba720c6928976d46062164a7936db0c74dce6f2bec0b11`.

Reproduced failures before correction: the redundant diagnostic list remained
present, expanded phone content extended outside its board, and the old height
cap clipped commentary (viewport ratio **0.65076**, required **1**). The final
tree removes the table, bounds expansion width and lets small screens scroll
naturally. The compact Desk guide retains explanations without another universe
list. Grade source stays explicit; ranking copy describes the actual
allocation-first order. Recorded reasoning is no longer sliced before display.

UNVERIFIED: deployed browser acceptance and full deployment gates. Existing Vite
CSS/chunk warnings remain. No backend, model prompt, trading policy, holdings or
orders changed in this follow-up. Deploy only through `scripts/deploy.sh` when
the operator is ready; a browser refresh does not rebuild the gateway.
Diagram impact: NONE — existing Desk/StockBoard boundary. CHANGELOG records the
functional evidence. The prior history/cohort checkpoint's migration and backend
proof are below, not replaced by the frontend test count.

Goal remains active. Next atomic research work is the independently replayable
all-account journal, before the zero-safe exposure adapter or nested fits. The
read-only code review identified these concrete boundaries:

- Instrument actual `_Book._fill` batches, with decision/phase context through
  `settle`, `settle_split` and `learned_research.replay`. Preserve arithmetic and
  default outputs. `SimTrade` is not a fill journal: it misses partial fills,
  costs and cash. Instrument SPY/QQQ `constant_exposure` in place with the same
  schema rather than replacing its ledger with the incumbent implementation.
- Independently replay initial cash, submitted/adjusted orders, actual fills,
  fees, all held close marks and the explicit terminal open state; validate price
  references against immutable hashed arrays, not only prices copied into events.
  Use session/phase timestamps, never invented historical observed timestamps.
- The current ledger has one cash balance, not actual T+1/T+2/T+3 settlement.
  `recycle_sells=False` bounds buys to pre-batch cash, then credits net sales at
  the batch end. Preserve and name each batch's recycling convention. A real
  settlement model is a separate versioned change.
- Zero exposure also encounters `planner.target_shares`' minimum-trade rule:
  small positions can survive a zero target. Record desired zero versus actual
  residual honestly; the later adapter must explicitly liquidate and restore
  stable unscaled composition. Do not merely permit a zero brake override.

No new journal or strategy implementation has begun, and no completed losing
study was rerun or retuned. `/3` remains incumbent; source-complete historical
quality/cohorts and genuine independent validation remain outstanding.

## 2026-09-24 — Personal receipts and sourced cohorts; next: one stock list and risk allocation

Started clean on `main` at `8953aee30eb7f324e5c350b7ce6c46eeb7bed109`;
`git pull --rebase origin main` was already current and the pre-checkpoint fetch
confirmed zero divergence. All current edits belong to this task. No deployment
occurred; the user deploys from Spark through `scripts/deploy.sh`.

Implementation checkpoint: `16cb39426a6e253ec8dc7290e40a45e38718186f`, pushed to
`spark main`. The staged
frontend hashes matched the browser-tested source before the separate
single-list work began. The migration verification was repeated after the
encrypted-only receipt reader landed and again built all **47 tables** at
`20260924_0021`. Both disposable local test databases have been removed; no
production database was touched.

VERIFIED: **82** planner/API/personal-history tests, with **5** actual
HTTP/Postgres receipt journeys and **4** pure projection guards; **103/103** Desk
Playwright tests plus **17/17** targeted repeat and production build; **41**
cohort/membership/CLI tests; complete migration replay to `20260924_0021`, **47
tables**, using the repository's `verify-migrations.sh` in a disposable local
Compose project with tmpfs Postgres (never the live database); **32** diagram
synchronization checks and the published architecture page. Existing Vite
CSS/chunk warnings remain. The host renderer required a container-only Chromium
wrapper; no system/browser security setting was changed. Only the two affected
SVGs retain regeneration changes. Diagram impact: UPDATED — agent-trading-desk,
market-data.

Personal advice history is implemented in `backend/market/personal_history.py`,
`backend/models/personal_decision.py`, the market API and new Desk history UI.
Only the primary desk owner can capture/read/export/delete/acknowledge. Capture
is explicit on POST; generated payloads are minimized and encrypted, and
acknowledgements are separately timed, idempotent, revision-bound and expire with
executable evidence. Reads do not mutate receipts. Unacknowledged rows expire
after 24 hours; acknowledged rows after 90 days; physical owner-scoped cleanup
runs on capture. The tests read storage back, inspect ciphertext and exclusions,
exercise concurrent acknowledgements, ownership, corruption, retention and
untouched holdings/paper files. Reproduced and fixed plaintext replacement
acceptance and a delayed list response resurrecting a deleted receipt. No past
AAOI advice is backfilled or inferred. Live deployed history remains UNVERIFIED.

The historical importer now copies and reads back actual SEC source bytes, not
just a caller's hash assertions. It is deliberately a retrospective three-name
demonstration: AAPL continuing, SNOW later included, TWTR removed. All **2,160**
rows over **720** XNYS sessions remain; all **8,640** feature cells are unavailable.
Publication dates, conservative availability bounds, ingestion times, identity,
membership and unfunded terminal entitlement stay distinct. This is not a
training-ready or unbiased universe. Archive and exact hashes:

- Spark: `/home/animallya96/anios/data/market/research/historical-cohort-20260924/`.
- Local: `/tmp/anios-historical-cohort-final.ekJucf/archive/`.
- All **14 files / 16,926,539 bytes** match after copy; the 10 original SEC bodies
  total **14,920,321 bytes**.
- Readiness SHA256: `ca90d58d6eeb8c48e18cf9901e05228e2e21caca73bcae634052b01cca7bf66c`.
- Archive manifest: `419be2dcc3afc71df2de0decc1179491706e031f7038c2c97936cbf7403aaa74`.
- Domain code: `516164bda2aa6fb60d4dba63f7634615ad061c753dd582e0d6f0215a59d66b5e`.
- CLI code: `82499d7471ebb2979fd0818bb6ca36f599eda72296d4589013dc1dbee1d15df2`.

Latest user steering and next substantive work:

1. Remove the redundant **Every grade in detail · diagnostic view** stock list.
   Root inspected the actual render. `StockBoard` already lists the same universe;
   preserve the lower view's useful vote changes, archived commentary, bar timing
   and owner-only confirmed-fill form inside existing upper-row expansion. Keep
   one compact ranking/data-timing guide, including legacy `deskDetails=1` links.
   `dashboard_review` has an exact consolidation plan and is waiting for the
   current history checkpoint before editing overlapping frontend files. Repeat
   the full browser path; the 103 count above does not prove the follow-up.
2. The operator clarified the strategy objective: own high-upside volatile quality
   names during favorable conditions and switch ahead of deteriorating conditions
   to cash or indexes. The updated strategy protocol treats this as forecast-driven
   stock/exposure allocation, not hindsight day-color switching. Indexes are not
   safe on broad red days. Keep `/3` fixed and the losing studies frozen.
3. Read-only audit found `learned_policy.walk_forward_brake` predicts a **20-session
   >8% QQQ drawdown**, not the next day, and only scales to 0.5. The simulator
   rejects zero and divides by previous exposure when restoring targets. A new
   isolated zero-safe research adapter with stable desired composition and an
   independently replayable cash/fill journal is required. Do not just allow zero.
   The current funded allocator only supports SPY as an index; do not silently
   narrow the operator's desired stock/index/cash design for compatibility.
4. Then freeze a bounded nested experiment before results: after-close decisions,
   earliest next-open fills, matured/purged forward labels, training-only
   preprocessing/calibration and inner-only gate selection. Include an identical
   no-gate adapter control as well as exact `/3`, funded SPY and QQQ at 10/25 bp.
   Preserve all fits, candidate scores, fees, turnover, missing data and continuous
   account state. Any already-examined history stays labelled examined research.
   Source-complete quality features, historical cohorts and genuine independent
   validation remain outstanding; these cannot be manufactured by fold geometry.

Goal remains active. No holdings/orders, live policy, inference model or deployed
service changed. No new strategy was promoted. Do not confuse the checkpoint
push with deployment.

## 2026-09-24 — Chronological diagnostics verified at e972117; broader work continues

Implementation checkpoint: `e9721173f5976da40246d8f8268c5cce360bd84d` on `main`.
It adds the pure chronological scorecard, a hash-checked read-only CLI, tests,
and `docs/research/chronological-stability-2026-09-24.md`. It follows dashboard
checkpoint `c73861b` (88/88 browser tests), already pushed with handoff `f43f6d2`.
No deployment occurred. Use `scripts/deploy.sh` only when deployment is requested.

VERIFIED: 76 related backend tests plus 14 CLI tests; root independently reran
43 metrics tests. Root also recomputed all 40 account/block returns and drawdowns
directly from preserved NAV arrays and checked exact code hashes. Scoped Ruff,
format and diff checks pass. The command was exercised against read-only copies
of the actual completed study with exchange-calendars 4.13.2. All nine original
run artifacts and SPY parquet remained unchanged.

Fixed shape 126 reference / 63 evaluation / 21 label-horizon / 5 embargo was
chosen before block results. Four blocks cover 252 of 428 intervals; 152 prefix
and 24 tail remain explicit. Incumbent beats SPY and QQQ in 4/4 at both costs;
neural beats incumbent only in block four. The evaluated regime counts are
113 above/high, 127 above/low, 12 below/high, zero below/low. This is post-hoc
stability on examined survivor/reconstructed accounts. Independent-validation
and adoption flags remain false, and historical input availability is UNVERIFIED.
No policy, model, holdings, order, or deployed service was changed.

Full report preserved on Spark, separate from the completed study:
`/home/animallya96/anios/data/market/research/chronological-stability-20260924.zcXplA/chronological.json`.
Local copy: `/tmp/anios-chronological-output.dJ9xb5/chronological.json`.
Both SHA256: `819e4bd49f0a5355ff48d6303a5f3bf5add84db43413f8478fcf0476ae1b6ccd`.
Source/input hashes and limitations are inside. Do not rerun the completed
model, retune the block shape, or present this diagnostic as independent K-fold.
Diagram impact: NONE — calculation within existing research components.

Next substantive tasks (goal still active):

- Build a sourced historical cohort/evidence importer with a readiness report
  before a genuinely nested runner: retain publication and ingestion times,
  bytes, stable security IDs, availability, membership and terminal outcomes.
  Exercise a real small cohort containing a continuing listing, a later entrant
  and a removed/delisted security; retain missing names explicitly rather than
  letting panel construction drop them. A validator alone is not the end state.
  Existing membership validation is not wired into
  `desk.book_panel`, which still builds today's cohort. Read-only Spark inventory
  found no membership histories and zero learned-input captures; price and
  related partitions span only September 2026 vintages. Zero captures is not
  a reproduced writer failure: the last September 23 nightly record predates
  deployment of capture. Do not manufacture historical captures or invoke an
  account-changing nightly run to make the directory nonempty.
- Add a research-only cash/fill journal for all accounts, including ETFs, so
  costs, turnover and NAV can be independently replayed in future studies.
- Implement faithful personal-decision history separately from research:
  generated immutable receipt plus acknowledgement of the accepted dashboard
  response. Retain a narrowly allowlisted encrypted output, not raw cash/equity
  or holdings quantities. Only the primary operator may populate personal
  history. Label acknowledgements as loaded into dashboard, not proof the user
  read every row; preserve generation, acknowledgement and expiry separately.
  This needs a dedicated owner-scoped store, migration, security/retention
  documentation, existing trading-desk diagram update, and HTTP/database/browser
  proofs. Do not reuse task-change/undo records or public research archives.
  Prior AAOI advice cannot be recovered from evidence never recorded.

## 2026-09-24 — Research-history and account-evidence checkpoint c73861b

Started on `main` at `ea755e7336a9d85cdad420eadfcdcb587a9bca9d`, with four
inherited frontend edits from this task. Fetched origin and confirmed zero
divergence; preserved Spark's unrelated untracked `scratch/`. Implementation
checkpoint: `c73861b0ee63affb58587d7e713b33bf70a62cce`. NOT DEPLOYED.

VERIFIED on the exact frontend source: **88/88 Desk Playwright cases** in
56.3 seconds, with the checkout mounted into Playwright 1.61.1 and its own
Vite server; TypeScript/Vite production build passed. The existing CSS
`hover:bg-black` and chunk-size warnings remain. `git diff --check` is clean.
Five additional failing acceptance paths were reproduced and corrected:
wrong paper snapshot date, fabricated snapshot when missing, omitted zero
strategy target, same-session obsolete actionable count, and concealed archive
read failure. One new action-count test initially checked loading state; it was
corrected to observe a valid Buy before refreshing a changed record, and then
reproduced the actual defect. Two legacy assertions were updated for the
corrected paper-reset wording; confirmed fill persistence still passes.

History now says Recorded research readings and describes bounded coverage.
Paper snapshot dates use the paper record itself; absent evidence remains
unavailable. Research freshness controls the sizing source. Covered zero
targets, recorded personal positions, planning-equity assumptions, paper reset
timing and FOMC target exposure are explicit. Duplicate expanded sizing is gone.
No backend policy, holdings, order, model or deployed service was changed.
Diagram impact: NONE — internal UI behavior within existing components.

UNVERIFIED: this checkpoint on the deployed UI, and alignment of historical
personal AAOI/ORCL guidance with archived research. The current history has no
personal decision receipts or their account context; it cannot prove what the
operator saw. Do not backfill that claim from current decisions. A later receipt
design must distinguish server-generated advice from browser-accepted advice,
since superseded responses are discarded and expiry changes eligibility.

Broader goal remains active. Chronological research diagnostics are being
implemented separately in the backend, with no model refit or adoption. Finish
hash-checked application to the preserved study, report all regimes and excluded
intervals, and retain the examined-survivor/source-vintage limitations. Genuine
nested chronological training/selection evidence remains outstanding. Ship any
approved deployment only through `scripts/deploy.sh` and its gates.

## 2026-09-24 — Desk semantics merged to main and deployed as 26b3cb1

Codex's Desk implementation (3b45ed0 "Clarify Desk market status and trading
intent", 1940045 handoff) was merged into main alongside the neural research
(merge 5af6513, freeze d300760) and deployed through `scripts/deploy.sh`.
Unit gate 4645 passed / 26 skipped / 1 xfailed; routing gate passed; cheap
post-deploy checks ok. One gate failure was fixed by declaring the shadow
ledger successor `19f933ff -> dc1d5fa6` in
`backend/market/data/opportunity_shadow_migrations.json`: Codex's
calendar.py change (exchange_status) is hashed into the shadow identity but
does not touch `_future_session_offset`, the shadow's only calendar read; the
live ledger (sequence 6, 2026-09-22) continues unchanged.

## 2026-09-24 — Fixed benchmark and causal-regime acceptance gate

The forward `incumbent-neural-rank-blend/1-research` review now has an enforced
comparison boundary in `backend.market.neural_study_metrics`. Every scorecard
requires candidate, unchanged incumbent, SPY, QQQ, and equal-weight funded
account curves on identical sessions and at the same declared 10 or 25 bp cost.
Net total return is the primary objective, with an explicit strict-pass result
against incumbent, SPY, and QQQ; CAGR and rolling 63/252-session wins remain
reported alongside drawdown, turnover, Sharpe, and the separately retained
exposure/fee/concentration diagnostics.

The reusable regime scorecard labels each return from point-in-time SPY adjusted
closes available before that interval: prior close versus its trailing
200-session mean, and trailing 20-session log-return volatility versus its
trailing 252-observation median. Equality follows the frozen replay (trend
above, volatility low). It reports all four trend/volatility combinations plus
an explicit unknown/unavailable bucket. Missing evidence, noncontiguous
sessions, and warm-up shortfalls cannot be dropped or backfilled. Regime tables
attribute one-session net log growth without restarting accounts or annualizing
stitched segments; they do not implement or authorize a regime-switching policy.
The 252-session forward hold, frozen model/input hashes, research-only status,
and no-retuning rule are unchanged. Diagram impact: NONE. NOT DEPLOYED.

VERIFIED locally: **85 passed** across the scorecard, simulator, rank-blend,
challenger and baseline harness suites; the scorecard's own **24 tests** cover
all four regimes, prior-information invariance, fixed equality behavior, missing
evidence, calendar/cost alignment, SPY/QQQ/incumbent rolling comparisons,
compounded growth, fees, exposure, and concentration. Scoped Ruff and format
checks pass with an isolated current Ruff because the repository's pre-existing
Ruff table is rejected as duplicate TOML by current Ruff; `git diff --check` is
clean. The optional historical-study module was not part of this count because
host Torch is unavailable. No historical strategy was rerun and no policy was
promoted. Verified implementation checkpoint: `d87a5f9`.

## 2026-09-24 — Fixed incumbent/neural blend protocol, research only

The next challenger is frozen as
`incumbent-neural-rank-blend/1-research`: equal cross-sectional percentile
ranks from the incumbent and the separately named price-only neural model,
using only the incumbent's existing evidence coverage and all of the unchanged
live risk/account rules. It is an attribution test, not a claim of superiority.
No historical rerun, scoring, strategy promotion, recommendation, paper-account
write, or deployment occurred. The completed losing neural and HGB studies must
not be retuned.

The protocol and current 2026 literature review are in
`docs/research/top-tier-strategy-protocol-2026-09-24.md`. A forward run must
freeze the exact price-only model/input hashes before its first decision and
retain 252 completed sessions before review. It must compare the blend with the
unchanged incumbent, SPY, QQQ, and equal weight at 10 and 25 bp. The primary
hurdle is higher net total return than all three incumbent/index comparators;
drawdown, turnover, exposure, fees, concentration, and rolling consistency stay
visible diagnostics. A model-specific trust gate remains deferred until genuine
forward forecast-error history exists.

VERIFIED locally against the exact research code: **33 passed** across the
baseline/rank-blend, market-challenger and neural-policy comparison suites;
scoped Ruff and `git diff --check` are clean. Diagram impact: NONE — this adds
one policy option inside the existing research adapter and no component, store,
dependency, ownership boundary or data flow. NOT DEPLOYED.

## 2026-09-24 — Desk semantic consistency implementation, not deployed

Working tree changes on `main` at starting HEAD
`1ad7e5996f57a46589a8f7585a030f7067c1e09c` make the Desk's live status and
labels match their actual sources. XNYS state comes from the backend's reviewed
2026–2028 holiday and early-close files and fails closed outside that coverage;
the UI explicitly calls it scheduled state, not observed exchange operations.
Both `/desk/live` and `/desk/mine` carry the same contract.

Personal strategy intent is distinct from executability: blocked Buy/Sell
intent and its intended allocation change remain visible, while the blocker is
named and expired evidence is removed from the actionable-now count. Personal
allocation, adopted strategy target, current-bar research allocation, and paper
broker position no longer share ambiguous `Plan`, `Size`, or `Desk position`
labels. Research allocation does not gate a strategy Sell. Overlapping personal
guidance requests are sequenced; errors clear executable fields and show an
alert. The paper account remains a separate surface. The live policy remains
`cash-bounded-breakout-rotation/3`; learned/neural work remains research-only.

VERIFIED locally against the shared checkout: **46 passed** in
`test_market_calendar.py` + `test_market_desk_api.py`; scoped Ruff lint and
format clean; frontend TypeScript/Vite production build passed; **81/81 Desk
browser tests passed** with no test failure. New browser proofs cover a blocked
Buy, visible 503 fail-closed state, stale-response ordering, deadline expiry in
the actionable count, dynamic research-vs-strategy allocation labels, and the
2026 day-after-Thanksgiving 13:00 close. Vite emitted the pre-existing
`hover:bg-black` minifier warning and chunk-size warnings. Host Python initially
lacked backend extras; the passing run used isolated `/tmp` dependencies and
did not modify the repository environment.

Implementation checkpoint `3b45ed0` was pushed to `spark/main`. NOT DEPLOYED.
Before release, run the required full gate, deploy only through
`scripts/deploy.sh`, and exercise the real Desk workflow against that exact
deployed revision. Do not promote a research policy as part of this UI
correction.

## 2026-09-24 — Actual neural price study and deployed results VERIFIED

Release `879abc56ca4d7b3827bf4b8244991d0d02bf0c00` is LIVE through guarded
`scripts/deploy.sh`. Full backend gate: 4621 passed, 26 skipped, 1 known xfail;
serial real-model gate: 100 passed in 802.94s. Postdeploy marker is ok.
Log: `/tmp/codex-neural-results-release-20260924.log`.
Independent read-only proof PASS:
`/tmp/codex-neural-results-release-proof-20260924.json`. All 30 displayed
cost/year/account rows match the actual authenticated API, with no browser
exceptions or failed API requests. Exact backend source/artifact hashes match.
Gateway image: `sha256:af80b2d26b3e7ff7f5a4c169f5901f196117d44b190f12b61cf2d97424996c59`.
Model container IDs/start times are unchanged. Root inspected the browser proof
and rendered screenshot. No orders or holdings writes. Watcher finished verified.
Main after this release adds documentation only; DO NOT redeploy to align markers.

User clarified the primary objective: maximize total portfolio gain and beat
BOTH SPY and QQQ. Drawdown and turnover are diagnostic checks on its quality.
The completed candidate fails the primary objective versus the incumbent.
New saved-curve regime decomposition also loses to incumbent in all three
observed regimes; the fourth has zero observations, explicitly unassessed.
Details and provenance are added to the research report, without refitting.

Additional bounded HGB reuse check is complete: do NOT score old HGB forecasts
as if they used the pinned report's inputs. Different source vintages change
features across the window, and 1,361 forecast cells are missing during warmup
or for the benchmark. No estimators were saved for rerunning inference.
Receipts: `/tmp/hgb-reuse-audit-20260924.json` and
`/tmp/hgb-feature-reuse-check-20260924.json`. A later separately declared refit
on verified inputs is needed; do not fill missing predictions, calibrate ratios
or alter the incumbent's opportunity set to manufacture compatibility.
All delegated tasks are finished. No active OpenCode or research training job.

User is sleeping and explicitly requests continued work and concrete results
on the dashboard. The fixed run is COMPLETE, not merely prepared. Protocol
`5e19336` preceded outcomes; exact training/evaluation source `1ad7e59`.
Artifacts: `/home/animallya96/anios/data/market/research/neural-price-rule-20260924`.
Preserved inputs, model, forecasts, source manifest, 10/25-bp curves and results.
Do not refit, rescore, change windows or rerun this completed study.

Result: price-only neural ranking loses to the unchanged live-rule reconstruction
at both costs. At10bp total returns are242.2% versus399.9%, drawdowns−37.1% versus
−31.7%, annual bought-plus-sold notional/meanNAV20.80 versus16.36. Those large
returns reflect an examined current-survivor reconstruction, NOT achievable
returns or personal-account history. Candidate wins0/177 overlapping252-session
windows against incumbent. It is NOT the separate frozen nightly neural model.
No adoption. Both costs, SPY/QQQ/equal weight, calendar-year slices and rolling
win rates are in the preserved JSON. All financial inputs are missing explicitly.

Independent artifact verification PASS:
`/tmp/neural-study-artifact-review-20260924.json`. Verified191 source hashes,
14 consumed source files at1ad7e59,22685 training examples, last label2023-12-27,
training-only normalization,429 common NAV marks/428 return intervals, all
full/year metrics and rolling counts. Raw trade/cash traces were not saved, so
independent turnover verification covers its denominator, not raw ledger replay.
The fixed simulator/account path has separate parity tests.

Root reviewed a minimal Research-only dashboard card, API read-only payload and
static curated artifact. No recommendations/action/policy changes. Frontend80
browser cases and TypeScript pass against exact source5178;34 API/desk cases
pass, including actual authenticated response and unchanged paper/neural files.
Final narrow wording follow-up: 3 browser cases and 46 API/desk/metrics cases
passed. The actual8080 deployment and browser evidence above completes this
bounded research-results release. Live policy remains
`cash-bounded-breakout-rotation/3`; candidate is research-only, not adopted.

Completed delegated work includes read-only saved-curve regime decomposition using
the already-fixed prior-close200MA/20vol/252median definitions. No retraining or
selector; regimes.json and reproduction script are preserved in the run folder.
Both frontend ownership and all prior module ownership returned to root.
Shared `/home/animallya96/anios` remains deliberately preserved at localfc703b0,
one local-only commit plus newer incoming main, with AGENTS.md/scratch changes.
Root worktree and GitHubmain carry reviewed work; do not silently mergefc703b0.
The bounded actual-results task is complete; pause its hourly heartbeat as
authorized to avoid repeated completed work. This does not establish universal
best performance, validate the frozen nightly neural model, or finish the broader
learned ranker/brake request. A first ordinary archived price-opinion receipt
remains unverified; do not manufacture one or manually run the nightly process.

## 2026-09-24 — Corrected neural inputs and matched-rule adapter

User asks whether other approaches could outperform neural/momentum: yes,
neither is established best. Do not choose an architecture before measurement
or expand into an outcome-driven search. Continue the neural comparison; the
chart release below is complete and does not need another deploy.

New research-only `neural_price_basis.py` reconciles original pre-split share
facts to an explicitly supplied source vintage, preserves versioned filing
availability, handles reviewed early closes, and masks unsupported currency,
ADR/share units or ambiguous historical facts filed after a split. It validates
all consumed close, adjusted-close and volume arrays against supplied history.
Independent tests found and fixed incomplete adjusted-price/volume provenance
and possible double adjustment of restated share counts. Missing evidence stays
missing; no numeric ratio calibration. Frozen neural inputs/model/journal remain
unchanged. The known frozen-path defect remains a strict xfail, not hidden.

New `neural_policy_comparison.py` substitutes only scheduled ranking through
the unchanged live simulator/risk/account rules, same event path and costs.
It preserves incumbent score coverage and rejects future or missing predictions,
immature training/selection labels and silently truncated subday timestamps.
Independent review reproduced and fixed a 0% -> 15% eligibility expansion and
23:00 timestamps being truncated to dates. This is a ranking hybrid: midcycle
entries retain the incumbent rules, including purchases whose neural return
forecast is negative. It is NOT the original positive-only neural shadow policy.
Supplied daily provenance and SHA256 strings are assertions, not an input audit.
Outputs explicitly say adoption_eligible=False and reconstructed research.

Verified research checkpoint: `20d842a`, pushed to GitHub main; production
remains the verified chart artifact `d6369276` because these modules are inert.
VERIFIED: combined exact-source acceptance **89 passed, 1 known xfail**, scoped
Ruff clean; `/tmp/neural-research-checkpoint-20260924.log`. The two independent
comparison cases and three independent input cases passed after correction.
Same-score parity reproduces the live simulator at 0/10/25 bp; event tests
actually change a funded account, and future-score mutations change later
results while preserving an already-invested earlier prefix. No historical
scoring, fitting, production policy change or deployment in this checkpoint.

UNVERIFIED / NEXT: bind actual cached source bytes and fundamental currency/ADR
unit evidence to the corrected path before a separately named corrected-input
retraining study. Inspected AAPL versioned-frame metadata contains CIK, fetch
time and parser version, but no unit evidence: do not set the verification flag
from that alone. Reuse fixed cached data; retain missingness and original frozen
model identity. Freeze cohort/cutoffs/execution/benchmarks before results. Report
the ranking hybrid separately from the full neural-policy comparison, current
survivor-cohort reconstruction separately from archived live decisions, and
2025+ as already examined rather than an untouched holdout. No superiority or
replacement decision has been established. Root owns all four new files; both
independent review agents returned ownership. No active OpenCode work required.

## 2026-09-24 — Chart consistency release LIVE and verified

`d6369276fec135edf7d1d8a7403354d817950b60` is LIVE through the single guarded
`scripts/deploy.sh` release. Full backend gate: **4554 passed, 25 skipped**;
real-model gate: **100 passed in 764.02 seconds**. Exact postcheck:
`2026-09-24T03:52:09Z d6369276 ok (cheap)`. Running chart and market API
hashes match the deploy tree. Gateway image:
`sha256:912796e0497eec3f8596aa175672bc2602a8e3d8d32a9882b7b40c98e08a7b94`.

VERIFIED: all **190 authenticated daily/weekly chart API payloads across 95
quoted tickers** return aligned arrays and the new quote timestamp contract.
Actual deployed browser workflows for **AAOI, AVGO and AAPL** render daily and
weekly canvases and close prices matching those API snapshots, with no page,
console or required-network failures. The changed stale-quote/concurrent-response
fixture also passes against deployed port8080 (1 test). Model container IDs and
start times match the original baseline. No holdings or orders were written.

Two harness failures are retained, not hidden: a blanket `networkidle` wait timed
out despite successful AAOI content assertions, so readiness now asserts the
specific daily/weekly chart state; WRB had no ranked-board row because the actual
94-name `latest.grades` omits it (search rendered zero matches). WRB's chart API
was tested; its board workflow was not. AAPL was confirmed in both actual grades
and rendered search before replacing WRB as the third browser case. This is not
a guarantee that every provider value or every ticker's rendered chart is correct.

Evidence: `/tmp/codex-chart-release-proof-20260924.json` (PASS),
`/tmp/codex-chart-release-20260924.log`,
`/tmp/codex-chart-deployed-fixture-20260924.log`,
`/tmp/codex-chart-release-proof-networkidle-20260924.json`,
`/tmp/codex-chart-release-proof-wrb-locator-20260924.json`, and
`/tmp/check-wrb-board.json`. No production changes or redeploy were used to fix
the verifier. Main's later tests/docs-only commits do not require marker alignment.

The preceding `aa15c03057c8b27a26c5ac09da161dde492963d0` evidence-capture release
also passed runtime hashes, actual API/AAOI browser and unchanged-model proof:
`/tmp/codex-entry-evidence-release-proof-20260924.json` (PASS), 4541 backend
passes/25 skips and 100 model-gate passes. Its first ordinary completed-session
receipt remains **UNVERIFIED** until market collection runs. Momentum/breakout
remains the live strategy; neural remains experimental and was not promoted.

## 2026-09-24 — Parallel chart consistency correction, release pending

User asked whether all tickers/charts are consistent and whether neural is live,
then authorized parallel work. The existing momentum/breakout rule remains live;
neural is a separate experimental paper comparison. No policy was promoted.

Reproduced chart disagreement: the browser independently overwrote an API candle
with its board quote while leaving API indicator lines unchanged. The chart now
uses one API candle/indicator snapshot, exposes its actual quote-bar timestamp,
refreshes when the board observation changes, and rejects older HTTP responses.
Retained quotes no longer say "Price now" or "today". Grade declines say "below A",
not "sell"; recorded versus replayed grades and provisional weekly lines are explicit.
Backend daily/weekly completeness follows the included bar and exchange close,
including early closes. Forming-week swing series now have the same length as bars.

VERIFIED: seven new backend cases and the browser acceptance failed before fixes;
26 chart/backend checks (including authenticated actual ASGI routes), TypeScript,
and all 77 desk browser cases pass against exact worktree source at port5178.
Cached cross-ticker audit: 95 names x daily/weekly =190 payloads, zero missing,
array-length or quote-source timestamp failures after correction. This is not an
external audit of every provider price or every rendered ticker. The hypothetical
AAOI $106 race fixture is not an actual past UI receipt. Existing chart modules
have pre-existing lint debt; scoped market API/new HTTP test Ruff passes.
Evidence: /tmp/chart-contract-before-20260924.log,
/tmp/chart-contract-after-20260924.log,
/tmp/chart-consistency-desk-suite-20260924.log,
/tmp/chart-consistency-audit-after.json (original audit retained).

The preceding aa15c03 entry-evidence release is already running through full gates:
/tmp/codex-entry-evidence-release-20260924.log. NEVER restart it. Read-only verifier
/tmp/verify-entry-release-20260924.py must run after the exact postcheck marker;
proof /tmp/codex-entry-evidence-release-proof-20260924.json. It does not validate a
future ordinary research receipt while the market is closed. Chart changes are
not live until their subsequent guarded deployment and actual browser proof.

## 2026-09-24 03:09 UTC — Grade and dashboard fixes LIVE and verified

`facbdeed1bd07cb14c3d00abcb7c78739c2da20f` is LIVE: 4529 backend tests,
25 skips; 100 real-model gate cases; exact postdeploy status
`2026-09-24T03:09:42Z facbdeed ok (cheap)`. Running decision_view, market API
and simulator hashes match the deploy tree. Read-only actual HTTP and browser
acceptance verifies that old backtest metrics are withheld and actual AAOI
history preserves setups with correct grade/Buy distinctions; zero browser
errors or failed required requests. Model IDs AND start times unchanged.
Proof `/tmp/codex-grade-release-proof-20260924.json` PASS. The first proof read
the postcheck marker a second too soon because the cheap check detaches even
with --wait-post; a verification-only retry passed without redeploying.
The older active-release instructions below are superseded. No worker remains
active for facbdee. No new strategy was promoted.

New bounded work: `entry_evidence.py` captures matched, unfunded Dip versus
incumbent entry opinions at collection time. Existing archive lacks numeric
band inputs, so cannot reconstruct historical personal Buy receipts honestly.
New records preserve those exact20 prices, band/stretch/current grade and
common blockers, without altering signals, orders or account state. The
incumbent opinion calls actual production entry_action with current grade and
flat-position assumption. Builder stores evidence in immutable records and
includes it plus dependency/calendar files in source/input fingerprints.
39 focused capture/builder/archive/forward/history tests pass with Ruff;
tests include actual builder integration and legacy archive non-backfill.
Protocol `docs/research/entry-evidence-protocol-2026-09-24.md`.
This extension is not yet deployed at this handoff. Ordinary future collection
and 5/20-session outcome maturity remain to be observed. No comparisons or
profitability claims were manufactured from absent receipts.

## Active guarded release — do not launch another deployment

Source `facbdeed1bd07cb14c3d00abcb7c78739c2da20f` is pushed to main and
contains the grade fix plus the timeline clarification. One authorized
follow-through process `/tmp/finish-grade-release-20260924.py` is running.
It waits for the existing 020ae42 deployment to pass, then requires main to
equal facbdee exactly, runs scripts/deploy.sh with all gates and serial model
tests, verifies running source hashes, actual API and AAOI browser behavior,
deployed fixture cases, and unchanged model IDs/start times. Read
`/tmp/codex-grade-release-proof-20260924.json` and
`/tmp/finish-grade-release-20260924.log`; final deploy log is
`/tmp/codex-grade-release-20260924.log`. It aborts on failure, never retries or
skips gates. Do not advance main before it has pulled facbdee. No live completion
claim until its PASS is independently checked. The previous "frontend-only"
release plan below is superseded by this combined reviewed successor.

## 2026-09-24 — Live grade inconsistency reproduced and corrected

Further account-path review found `build` read `grade` from `live_grades`,
whose actual key is `grade_live`. Intent silently fell back to the nightly
grade while the funded planner used the current grade. A current downgrade
could therefore be suppressed by a stale Buy opinion; an upgrade could disagree
with its displayed intent. Six causal upgrade/downgrade cases failed before
the one-key fix; all pass afterward. 112 decision/personal/API cases pass,
including two authenticated POST grade-transition checks with unchanged saved
holdings. Scoped Ruff passed. Logs `/tmp/personal-live-grade-before.log` and
`/tmp/personal-live-grade-after.log`. This is not proven to explain AAOI.

Read-only AAOI reconstruction at $106 using the preceding session's archived
prices gives band 0.08867 on Sep22 and 0.12304 on Sep23, both below the actual
1.1 Buy threshold even with assumed A+. This is a conditional source replay,
not a historical personal-screen receipt. `/tmp/aaoi-price-rule-20260924.json`.

Broader regime work also advanced without refits/replays: fixed saved HGB-study
curves were decomposed by four causal SPY trend/volatility regimes (prior-day
200-session mean; 20-session volatility vs its trailing252 median). Tests prove
same-day/future/prefix invariance, complete counts and exact log-growth
reconciliation. 1882 intervals, no missing regimes. At10bp learned rank's mean
daily log excess versus momentum120 is negative in all four bins (-2.13,-2.92,
-18.74,-15.92bp). The last bin has only37 intervals/five months. This is an
exploratory decomposition of previously examined survivor-cohort outcomes, NOT
neural or exact live-strategy evidence; no regime selector is promoted.
Protocol, script, tests, source hashes and full table persist under
`data/market/research/regime-diagnostic-20260924/`. No frozen history changed.

## 2026-09-24 — Preserve Dip setup separately from trade permission

User correctly identified the mismatch between research Dip states and personal
breakout Buy actions, and asked to retain focus on the broader evaluation too.
The recommendation timeline now names research allocation and price setup,
explains that Dip is not a Buy instruction and A+ is not entry timing, and
retains the original setup during FOMC pauses rather than replacing it with
Hold. A browser regression reproduced the hidden Dip before the change and
passes afterward; all 77 desk browser cases pass on the exact checkout at
5178, along with TypeScript. Logs `/tmp/setup-mismatch-browser-before.log`,
`/tmp/setup-mismatch-browser-after.log`,
`/tmp/setup-mismatch-desk-suite-20260924.log`. No strategy rule changed.

Missing-valuation release `020ae42` is in its guarded serial deployment:
`/tmp/codex-held-marks-release-20260924.log` (4521 backend tests / 25 skips
already passed; real-model gate running at this handoff). Do not restart it.
After successful completion, ship this separate frontend-only clarification
through scripts/deploy.sh. Prepared read-only actual API/AAOI browser probe
`/tmp/verify-setup-release.mjs` takes temporary auth on stdin and never writes
holdings/orders; verify final source and model starts before reporting live.

## 2026-09-24 — Live-policy missing valuation reproduced; release pending

The full incumbent LIVE_POLICY path silently omitted held positions with absent
marks: a flat-price synthetic 15% holding produced a false -15.00% loss and
+17.65% rebound. Eight immutable cases failed before the fix. The simulator
now rejects unavailable held marks (NaN/infinite/nonpositive); missing unheld
names remain acceptable and real price losses remain measured. Funded research
retains its existing explicit unavailable-NAV handling. No entry rule changed.
New curves declare `complete-held-marks-v1`; the latest desk response withholds
older backtest metrics with an explanation, preserving original record bytes
and paper curves. Evidence: 144 relevant simulator/funding/event/parity checks,
74 API/daily/valuation checks, scoped Ruff, TypeScript, and 3 browser acceptance
cases against this checkout on 5178. Browser log
`/tmp/held-marks-browser-20260924.log`. Not deployed at this handoff.

User reports AAOI personal fill yesterday at $106, prompted by Buy or A+;
believes paper entered near $97. Read-only source audit finds initial archived
paper fill September 11 at $107.997097, September 22 add $107.51375, September
23 add $106.70. September 17 position increased but the saved record lacks its
individual fill, so do not claim a complete execution audit or infer its price.
The separate board-paper archive contains no AAOI fills. Personal displayed
decision at the user's entry time is not established. Research Dip observations
around $97 are real, but they are not funded personal Buy decisions: Dip is a
negative stretch/lower-band rule; personal entry uses upper-band breakout plus
grade, freshness, event, cash and position gates. Grade A+ is not an entry
signal. Preserve this distinction without dismissing the reported loss or
changing rules to fit this one trade. No holdings or orders were modified.

Continue the requested thorough actual-live-policy and chronological/regime
evaluation alongside this bounded incident review. Do not conflate momentum20
research, frozen neural, research Dip states and the actual live account rule.
No new regime study has run yet; the already completed HGB study stays fixed.

## 2026-09-24 02:10 UTC — Integrity release LIVE; September 23 reconstructed

Guarded release `eec2d6dd32eda1f4a9cff32015e046f478a33a3b` is LIVE:
4509 backend tests passed / 25 skipped, 100 real-model cases passed,
postdeploy `2026-09-24T02:10:36Z eec2d6dd ok (cheap)`. Running snapshot,
store and learned-policy source hashes match the release exactly. The
read-only acceptance in the running image reproduces ACN's missing-date
rejection with two supplied responses, no network request, unchanged source
bytes and unchanged original neural ledger. Model container IDs AND start
times are unchanged. Proof: `/tmp/codex-trading-data-runtime-proof-20260924.json`;
release log: `/tmp/codex-trading-data-release-20260924.log`.

User asked to use that day's archived data. Reconstructed September 23 marks
for the already-held frozen neural accounts, without a new prediction or
ledger append. Both prices use the September 23 adjusted series where
available; missing September 22 anchors use that day's stored source close
only when the overlapping close agrees exactly and neither vintage reports
an intervening split/dividend. Refuse incompatible bases; no fitted ratio.
Manual dollar-weighted accounting agrees with the frozen transition engine.
At 10 bp cumulative: neural +14.94%, valuation +10.49%, momentum20 +0.98%,
SPY +1.72%. All source and ledger hashes unchanged. This is five return
intervals/one basket; reconstructed time is distinct from source times.
Script/result: `/tmp/reconstruct-neural-mark-20260923.py` and
`/tmp/reconstructed-neural-mark-20260923.json` (also retained in the research
artifact directory). This reconstruction is not a fabricated nightly row.

Latest user scope: compare market regimes, like cross-validation across
regimes. Use chronological, purged walk-forward folds and causal regime
labels, not shuffled K-fold or ex-post switching to the best regime winner.
Do not refit the already-evaluated HGB study or claim neural universal
superiority. Existing neural archive is frozen. A regime comparison may
reuse its exported network with the archived September 14 inputs; that is
a retrospective reconstruction and must be labelled as such.

## 2026-09-24 — Conditional learned study complete; neural audited; snapshot guard

The user authorized retrospective testing and asked whether the strong nightly
neural result could improve live recommendations through a combination. See
`docs/research/learned-price-results-2026-09-24.md` and its JSON table.
Do not rerun, refit or tune this study. Source `8f36135` fit once on the fixed
current-cohort single-vintage inputs. Full requested scoring FAILED because
52 names lack September 22 bars in the September 23 snapshot. Amendment
`1753a6e`, declared before stock metrics, permits only the mechanical complete
prefix through September 21, with identical saved forecasts and controls.
Artifacts: `/home/animallya96/anios/data/market/research/learned-price-20260924`.

The new HGB ranker does not earn adoption. At 10 bp its conditional CAGR is
48.7%, drawdown -57.9%, turnover 19.48/year versus momentum120 70.5%, -46.6%,
9.33/year; final withheld interval returns 6.0% versus 28.8% (QQQ 7.9%).
These survivor-selected price diagnostics are NOT historical live performance.
The common window begins in 2019 due to minimum training history; the full
live incumbent, dated fundamentals/tone and historical membership remain
unavailable. No new live policy is selected. Common regime features now
retain their numeric values instead of being ranked to a constant across
stocks; retrospective forecasts are structurally rejected by live sizing.

The separate frozen neural ledger was independently replayed read-only:
six input hashes and inference arrays exact, all ten accounts exact across
six observations. September 15 decision, September 16 close fill, latest
September 22 mark: neural +15.84%, valuation +12.01%, momentum20 -0.20%,
SPY +2.46% at 10 bp. Only one basket/four return intervals; no matured
20-session comparison or regime-selector evidence. Original ledger unchanged.
Audit `/tmp/audit-neural-20260924.json` and reproducible script beside it.
September 23 nightly stopped on the frozen identity guard; the continuation
was already fixed in the prior deployed release. Do not fabricate a missed
observation or change the frozen model to chase these returns. A future fixed
50/50 blend is a control to test before any learned selector, not implemented
or approved live by this audit.

Snapshot refresh now checks all previously retained date columns within the
requested range, retries one response that drops a known date, then rejects
it without writing. Existing bad partitions remain immutable. Real ACN
September 23 bytes reproduced the missing September 22 failure with zero
network requests and unchanged source hash. Scoped Ruff passed; 66 focused
learned/store/nightly tests plus 9 frozen neural tests passed. Production
deployment and next ordinary nightly behavior still require verification.
Do not run `desk_daily.sh` manually: it includes paper-account writes.

All code is in the isolated `codex/trading-evidence-20260923` checkout;
preserve OpenCode's unmerged shared checkout and its unrelated edits. Ship
only through guarded `scripts/deploy.sh`, no model/settings changes. At this
handoff the running release is still `5072dd64`; no new deployment claimed.

## 2026-09-24 01:14 UTC — Causal learned shadow bridge LIVE, rule unchanged

Commit `5072dd6456e825e1fde74322ff7cd16007fb7d1d` passed the guarded
`scripts/deploy.sh` path and is running. Full backend gate: **4498 passed,
25 skipped**; serial real-model gate: **100 passed**; postdeploy marker:
`2026-09-24T01:14:25Z 5072dd64 ok (cheap)`. Deployed and running backend
SHA-256 matches for `learned_inputs.py` (`9647c118...e29`) and
`learned_archive.py` (`6dc6cff7...e3a63`). The `ds4-head` and embedding
containers kept their prior start times; no model service was changed.

The ordinary nightly now records the real desk's grade, score, side, target
weight and rule receipt along with its previously captured features. Its
20-session high-low range is adjusted bar by bar using the capture-vintage
adjusted-close/raw-close ratio, so a split is not a false volatility shock.
The new read-only archive bridge retains missing sessions, uses one first
mature price vintage for stock and SPY adjusted-open labels, and feeds
publication-dated outcomes to monthly purged rank and quarterly purged crash
fits. Targeted Ruff and **67 focused tests** passed, including split,
missing-vintage, late-capture, label-maturity and insufficient-history cases.
It places no orders and does not change personal or paper recommendations.

Read-only acceptance in the **running backend image** on the real store found
16 September sessions, 15 stored bar vintages, **0 learned-input captures,
0 rank scores, 0 brake scores**. This is expected because the 2026-09-23
nightly completed before the prospective capture release. The next ordinary
nightly must be checked for a single immutable `asof=DATE.json`, its source
record hash, captured time and complete bars. Do not force a historical run
to fabricate one. The host `~/research-venv` initially lacked scikit-learn;
with user authorization, installed the repository-pinned `scikit-learn==1.9.1`
plus its missing dependencies without changing NumPy or SciPy. The same
read-only archive/fit check now runs in both the host venv and deployed
backend, yielding **0 captures and 0 forecasts** in each. Nightly capture
does not invoke the fitter.

The current live rule remains recommended. There is no valid 2016–26
learned-versus-incumbent/SPY/QQQ/equal-weight table, no scored prospective
cohort and no adoption claim. The separate OpenCode `fc703b0` rank files
remain unmerged in the shared development checkout; its four reproduced
price-basis/purge/brake blockers and differing target are documented in
`docs/research/TRADING_LEARNED_REVIEW_2026-09-23.md`. Preserve that checkout's
user work and do not import it as a learner.

## 2026-09-24 00:24 UTC — Prospective learned inputs LIVE; first nightly pending

Source `37f523ab2dafd82295d63a1e2d5da7580238dd77` is deployed by the
required `scripts/deploy.sh`. The full backend gate passed and its serial
real-model gate passed **100/100**; postdeploy status is
`2026-09-24T00:24:44Z 37f523ab ok (cheap)`. The running backend's
`backend/market/learned_inputs.py` SHA-256 exactly matches the deploy source
(`2a815358...10072f0`). Model containers were not changed. The deploy
checkout's untracked `data` and `secrets` links were preserved.

The ordinary current `market_daily` writer now appends a separate immutable
feature observation after saving the desk record. It records actual capture
time, source record hash, code revision, bar completeness/provenance, price
momentum/volatility/raw range, market breadth/regime, dated filing ratios and
scored earnings tone; missing values remain null. Historical and forced runs
do not fabricate an observation, and an earlier capture cannot be overwritten.
**58 focused tests passed**, scoped Ruff passed, and a read-only build using
the actual 2026-09-23 desk record serialized successfully: 95 names, 95
complete current bars, 89 known tone records, 82 available earnings-yield
features. This proves the real source schema, not learner profitability.

The 2026-09-23 19:30 nightly finished before the 20:24 local deploy. Thus
`data/market/learned_inputs/` correctly has no file yet; verify the next
ordinary trading-session nightly creates `asof=DATE.json` and that its hash,
capture time, complete-bar counts and source partitions are valid. Do not
force/replay today or rewrite the existing desk record to seed it.
The host's two cron launchers originally ran from the shared development
checkout, whose OpenCode commit `fc703b0` is ahead of remote `main` while it
is behind the docs checkpoint. To keep scheduled personal guidance on the
tested source, `/home/animallya96/desk_daily.sh` and `desk_intraday.sh` now
run from `/home/animallya96/deploy/anios` without an unmanaged `git pull`.
The deploy checkout's `data` link resolves to the same persistent store;
both Alpaca key values match the shared `.env`, and the host research venv
imports both CLI modules from the deploy checkout. No launcher was executed
to avoid a second record, balance write or paper trade. Shell syntax passed;
the next scheduled run still needs actual acceptance. Preserved original
scripts as `*.pre-verified-checkout-20260923`; installed script SHA-256s are
`e6a884f4...43b45c43` (daily) and `d99134b3...deb8497fe` (intraday).
The shared checkout's OpenCode commit, modified AGENTS.md and scratch files
were not changed, staged, reset or pushed. Do not deploy during an active
nightly process because its code checkout must remain stable until the record
is written.
Independent read-only review of that separate `fc703b0` ranker commit found
four adoption blockers despite its 60 owned tests passing: raw high/low mixed
with adjusted close makes ATR **9.1** on a flat split-adjusted series; a pure
10:1 split yields **−0.9** from its raw forward-return label; its fold helper
does not enforce chronological or label-end purging; and its brake is fixed
thresholds rather than a trained adaptive model. Its label also differs from
the registered SPY-relative next-open/open-at-t+11 target. See
`docs/research/TRADING_LEARNED_REVIEW_2026-09-23.md`. Keep it out of `main`
until those contracts and real point-in-time data are reviewed.
The learned rank/brake remain **shadow-only**. A 2016–26 comparison against
the incumbent, SPY, QQQ and equal weight is still **UNVERIFIED** without
dated historical membership, delisted outcomes and compatible price vintages.
Do not switch the live recommendation policy based on a survivor-selected
or restated-price diagnostic.

## 2026-09-23 23:43 UTC — Desk correction and complete recommendation log LIVE

Source `42c5a74618a7ad7d29e288fd4c2e73d1f2d0b523` is deployed through
`scripts/deploy.sh`; marker `42c5a746`, gateway image
`sha256:1e8b3d7c03258a01f2398430294b0efc95241d7b882c1ab6df29e9e1cb256c61`,
backend image `sha256:1b01602a25f5e5e53cc820cc922858cee1f81cbe4fb035495a345bd5fdab4aa2`.
Required full unit gate **4480 passed, 31 skipped**, live-model gate **100 passed**
under `ANIOS_GATE_WORKERS=1`; postdeploy status
`2026-09-23T23:42:12Z 42c5a746 ok (cheap)`. The first guarded attempt stopped
before restart on missing `scikit-learn` and a changed, frozen shadow-ledger
identity. Commit `4ab453a` installed the fitter and declared the exact
continuation from the ledger's actual current identity; no archived record
was rewritten. The successful retry used all required gates.

Actual deployed API/browser acceptance in
`/tmp/trading-release-proof-20260923.json` is **PASS**. Backend source hashes
match the running container. Personal account API/browser checked unknown and
zero cash, invalid/cross-account inputs and unchanged holdings, with no page
errors. AAPL history returned **138** archived readings (2026-09-14..23); the
live ticker view rendered all **138** rows and distinguished recommendations,
subsequent stock changes and personal fills. Three relevant browser fixtures
also passed against the deployed 8080 bundle. A first live check caught an
invalid `en-US@posix` locale in the chart library's time-axis formatter;
`42c5a74` pins its chart locale. The regression browser test failed before
that fix and passed after, and deployed browser errors are now empty. Model
container identities/start times did not change. No real orders were sent.

The new learned rank/brake are still **shadow-only** and lack a historical
point-in-time input adapter, sourced 2016–26 membership and mature comparison
results. Do not present them as better than the incumbent or adopt them.
The shared `/home/animallya96/anios` checkout remains at `9e4fab9` with
pre-existing uncommitted OpenCode/other-session changes; this task never
edited or staged that checkout. Main and the deploy checkout carry the live
release. Do not reset or clean the shared checkout.

## 2026-09-23 23:02 UTC — Recommendation readings and personal fill state reviewed

Candidate checkpoint `f8494501afce133a246f87dd1ce89054475d8207` on
`codex/trading-evidence-20260923` is **not deployed**. The ticker history now
shows every saved recommendation reading instead of folding consecutive equal
states. Each row retains its original grade, suggested allocation, entry state,
policy identity and bar price. The later stock change is explicitly hindsight,
not prediction accuracy, a fill or personal profit. The archive currently has
138 saved intraday decisions dated 2026-09-14..2026-09-23; readings before the
archive began cannot be reconstructed. The reader still returns its most recent
200 valid rows and flags older records if that limit is exceeded.

An earlier draft treated viewing a Buy as though a trade had occurred, writing
an issued-entry file and returning Hold on refresh. That read-side write was
removed. A repeat read retains Buy; only a recorded same-session fill or an
explicitly supplied working buy order suppresses another Buy. `last_buy_date`
records adds to an older holding without replacing its original entry date.
The dashboard stamps it only after the user records a confirmed fill; it does
not query Schwab or place an order.

On the exact code checkpoint, **127 focused backend tests and Ruff passed**;
the full desk browser suite passed **76/76** on the isolated candidate Vite
source, including every saved timeline row and confirmed buy/add persistence.
Candidate TypeScript check passed. A container-local
`npm run build` on the safety checkout could not reach Vite bundling because
its reused Node modules lacked the arm64 Rolldown optional binding; the
guarded deployment build remains the required production acceptance path.
No live strategy was switched, no real orders were placed, and the learned
ranker/brake remain shadow-only. Full learned-policy backtest/live parity,
dated fundamental/earnings-tone inputs and the requested 2016–26 comparison
remain **UNVERIFIED** for the point-in-time reasons below.

## 2026-09-23 22:31 UTC — Trading candidate reviewed; learned policies remain shadow-only

Isolated branch `codex/trading-evidence-20260923` combines Fables' imported
review-fix branch and OpenCode's first-step patch. The first-step browser work
passes all **76/76** desk Playwright cases against isolated Vite source
(`trading-evidence-vite` on 5178; `/tmp/trading-evidence-browser-full-20260923.log`).
The combined relevant backend acceptance passes **421** tests with 27 existing
numerical missing-data warnings (`/tmp/trading-evidence-final-backend-20260923.log`).
Scoped Ruff and frontend TypeScript pass. Early-close, drawdown-sign,
FOMC-entry gate and policy-version fixes are in the candidate, not deployed.

New research-only `learned_policy.py` has a ten-session next-open/open-at-t+11
SPY-relative label, publication/membership checks, purged monthly boosting,
purged 20-session logistic crash-risk fits, hysteresis, named shadow ranking,
shared desk sizing and an opt-in simulator brake ceiling. Synthetic acceptance
tests check future-prefix invariance, data availability, labels, caps and
accounting parity. `membership.py` plus `universe.as_of` fail closed without a
sourced dated history. These components are **VERIFIED as causal kernels on
synthetic inputs**, **UNVERIFIED as a live or historical profitable strategy**.

Only 14 daily-bar `asof=` snapshots exist (2026-09-05..2026-09-22); historical
membership/delisted outcomes are absent. Existing older prices are adjusted
retrospectively. Therefore the requested 2016–26 learned versus incumbent,
SPY, QQQ and equal-weight results table is **UNVERIFIED** under common
point-in-time inputs. No candidate superiority or adoption is claimed. See
`docs/research/TRADING_LEARNED_REVIEW_2026-09-23.md`. The deployed tree remains
`8ce637b4`; no orders or deployment occurred in this continuation.


## 2026-09-23 08:38 UTC — Final dashboard release VERIFIED; supervision complete

Live8ce637b486175475aa934c8b27061a6dc2244686, marker8ce637b4, through
scripts/deploy.sh without bypasses. Unit4373pass31skip, model100pass. Actual
authenticated API/browser PASS:94personal rows, unknown/zero cash0buys,
invalid cash422, cross-account403, holdings unchanged, no browser/required
request errors. All8 final deployed-browser cases PASS3.7s. Postdeploy
07:57:36Z8ce637b4 ok. Source hashes match; model container IDs/start times
unchanged. Independently read logs, marker, status and current gateway image:
sha256:efb497499bd44ef33ca97874f80bb9a4751fcc2e4db4c1a76d21b317875d9d65.
Evidence /tmp/codex-final-copy-proof-20260923.json (PASS),
/tmp/codex-final-copy-release-20260923.log and
/tmp/codex-final-copy-deployed-browser-20260923.log.

Bounded implementation/account/wording work and targeted test cleanup complete.
Pause completion heartbeat; no recurring audits or redeploys for docs-only HEAD.
All worker-owned files integrated/root-owned. No personal orders placed.
Keep15m candidate experimental: no paired evidence supports replacing incumbent.
Tests establish implemented behavior, not trading profitability or correctness
of every future provider/model statement. No further work implied by this handoff.


## 2026-09-23 07:42 UTC — Final bounded wording corrections gated for release

Reviewed remaining RecordStatus, RegimeBanner, WhatChanged and account/header
data bindings plus backend research note/basis/missing-evidence producers.
Concrete fixes8ce637b: evening-record lateness no longer claims all quotes and
account data are old; sizing multiplier no longer asserts actual cash holdings;
target changes explicitly are recorded differences, not submitted orders.
Typecheck and8focused browser cases PASS on5177, evidence
/tmp/codex-final-copy-browser-20260923.log. No backend/strategy changes.
Remaining limitation is accuracy of future data/provider/model explanations;
this review cannot certify every dynamic sentence or strategy profitability.

Guarded deploy active /tmp/codex-final-copy-release-20260923.log using
ANIOS_GATE_WORKERS=1. Script chooses full gate because previous test cleanup
is in diff; no gates weakened/skipped. Do NOT restart deployment. Current live
08e236ae until successful marker changes. Deploy checkout only untracked data
and secrets; preserve them. Read-only proof watcher2206012 is running
/tmp/watch-final-copy-proof.py 8ce637b, expects actual API/browser plus8fixture
cases, source hashes/models/postdeploy. Output
/tmp/codex-final-copy-proof-20260923.json and watch log; not proof until PASS.
Original launcher may invoke watcher again after deploy; it is read-only, but
avoid further launches/repeated checks. Once exact release proof passes,
persist completion and stop scheduled unchanged audits. All workers integrated;
no new workers, data scoring, model work or strategy adoption authorized here.


## 2026-09-23 06:43 UTC — Wording release verified live; test cleanup integrated

Frontend release08e236ae is LIVE through scripts/deploy.sh, automatic frontend
path (no skip flags), build/typecheck pass. Gateway image
sha256:9b551c36346587559f13116d02bd9a2d89be65aa883e1d741d090d70be4035f5.
13 focused browser cases pass on root5177 and deployed8080: account help,
cash/holdings isolation and invalidation, chart rendering, benchmark missing
data, forward missing outcomes, FOMC and execution panels. Logs
/tmp/codex-copy-browser-20260923.log and
/tmp/codex-copy-deployed-browser-20260923.log. Postdeploy08e236ae ok (cheap).
Model container identities/start times unchanged. Existing actual authenticated
API probe for unchanged backend0fab65c remains applicable; no orders written.

All three copy workers exited and reviewed owned edits are integrated/root-owned.
Root replaced misleading personal/paper explanations, allocation/profit confusion,
guaranteed reinvestment and fixed-hours freshness claims; removed unqualified
historical edge percentages and unrelated FOMC performance persuasion. Research
timestamps and cost-limited sizing text corrected. No strategy/math changes.
Browser review found old EveryGrade explanatory component is not mounted in the
current page; updated mounted HowToUse and tested it, rather than claiming a
source-only edit proves visible behavior. Test zero-cash request assertion now
polls the asynchronous request; same required body/value, no weakened assertion.

Test cleanup84712fa integrated as9d04628 AFTER frontend deployment;31tests pass
in current tree (/tmp/codex-test-cleanup-integrated-20260923.log). Net81lines
removed, assertions/test bodies unchanged, previous8fixture-equivalence checks.
No runtime redeploy needed for this test-only commit. Do not repeatedly deploy
to align a marker with test/docs changes or rerun unchanged model gates.

Limits: focused13 cases do not prove every dynamic backend/model sentence is
correct, nor all dashboard paths. Remaining bounded review: backend-origin
displayed note/reason/basis strings and components outside worker groups
(RecordStatus, RegimeBanner, WhatChanged, AccountSummary). No need to restart
workers, score candidate again, or repeat previous audits. New15m entry remains
experimental; six-name diagnostic has no paired entries and proves no advantage.


## 2026-09-23 05:40 UTC — Account release live and acceptance verified

Deployed 0fab65c4 through scripts/deploy.sh: unit 4373 passed/31 skipped;
sequential model gate 100 passed. Actual authenticated deployed browser/API
probe PASS (94 rows, zero buys with unknown/zero cash, invalid cash 422,
other-account 403, holdings unchanged, no browser errors). Backend hashes
match source; model container IDs/start times unchanged; postdeploy cheap
status is ok for 0fab65c4. Exact images and live evidence are retained in
/tmp/codex-trading-release-proof-20260923.json. Its original FAIL is retained:
fixture tests had development-only auth URLs and saw the login page. Root
changed ONLY fixture URL origins to portable **/api/v1 paths, no assertions.
Rerun against deployed 8080: all 7 passed in 7.2s, evidence
/tmp/codex-dashboard-deployed-browser-originfix-20260923.log. No redeploy needed
for test-only change; this supersedes the fixture failure, not the source SHA.

Copy board and overview workers exited; research PID1862215 still active.
No copy changes imported. Root review REJECTS overview's retained claim that
all plans ignore personal holdings, same-session guaranteed sale reinvestment,
and 'nothing on the board moves' outside normal hours. Rewrite these using
personal decision_view behavior; remove unnecessary old 43%/24-point claims.
Board tooltip corrections look appropriate; chart sell explanation still
implies automatic reinvestment and needs correction. Never import either
worker wholesale or claim wording audit complete. Research files remain owned.
Next: finish narrow source-backed copy corrections, browser validation and
guarded frontend release; preserve experimental entry status. Keep test cleanup
84712fa separate from frontend deployment to avoid unnecessary model reruns.


## 2026-09-23 — User requests targeted test cleanup; first pass verified separately

User asks about redundant code, especially tests. Static scan of35 changed test
files (15085 total lines) found7 exact structural helper-duplication groups of
at least5 lines; not proof that whole test suites are redundant. Artifact:
/tmp/codex-trading-test-duplication-audit-20260923.json. Preserve distinct failure
cases and do not delete tests to get deployment green.

Separate verified/pushed branch codex/trading-test-cleanup-20260923 at84712fa,
tree /home/animallya96/codex-worktrees/trading-test-cleanup-20260923. It changes
ONLY two simulator test modules and new funded_simulator_fixtures.py: net81
lines removed, shared deterministic setup, no production or gate changes.
31 tests pass before AND after. AST comparison proves all31 test functions,
decorators and assertions unchanged;8 pickle comparisons establish identical
default/custom-open/custom-grade fixtures. Ruff/format/diff checks pass.
Evidence /tmp/codex-test-cleanup-before-20260923.log and -after-20260923.log;
comparison script /tmp/verify-test-cleanup.py. Not merged into integration/main
while the0fab65c deployment/proof watcher is active. After release verification,
review/integrate this exact3-file checkpoint without overwriting current handoffs
or any copy worker files. No new model cleanup worker was started; release stays
the priority. Remaining duplication candidates require semantic review, not
blanket deletion or a claim all tests are now clean.

## 2026-09-23 — Sequential gate release0fab65c and read-only proof watcher active

Main/integration now0fab65c (account source30afe7d plus optional gate concurrency
and handoff). Guarded deploy is active with ANIOS_GATE_WORKERS=1, log
/tmp/codex-trading-release-serial-20260923.log. Never restart it while active.
Detached watcher launched through parent1926651: /tmp/watch-release-proof.py
0fab65c, watch log /tmp/codex-trading-release-proof-watch-20260923.log. It waits
for this exact successful deployed revision, then checks backend file hashes,
real personal API/browser, seven fixture cases against the deployed bundle,
unchanged model container identities and postdeploy status. It never deploys,
retries, places orders or changes holdings; short-lived credentials remain in
private temporary files and are deleted. Final summary will be
/tmp/codex-trading-release-proof-20260923.json; browser/API detail in
/tmp/codex-dashboard-live-20260923.json and deployed-browser log. A watchdog
result must be independently read; script launch is not proof. It stops if
the required gate fails. All three wording workers are still active at30afe7d.

## 2026-09-23 — Repeated parallel timeout; bounded gate concurrency

Second full attempt again ended99pass1fail, same two-reminders wall-clock
assertion, in881.63s; see /tmp/codex-trading-release-retry-20260923.log. The
isolated unchanged test passed102.30s. Live is still a89bba40. Root added
ANIOS_GATE_WORKERS (default5, positive integers only) to scripts/gate.sh so a
guarded release can run the required model suites with one worker. No assertion,
case, skip list, model setting or timeout changed. Bash syntax, diff check and
invalid0 rejection pass. This is an evidence-backed contention test, not proof
that production model latency under concurrency is fixed. Next deployment uses
ANIOS_GATE_WORKERS=1; do not restart while active. All copy workers remain active.

## 2026-09-23 — Isolated timeout passed; one guarded retry active

The unchanged two-reminders case passed in102.30s under scripts/gate.sh.
Log /tmp/codex-trading-release-timeout-check-20260923.log. A single guarded
deploy retry is now active at source30afe7d, preserving all required gates:
/tmp/codex-trading-release-retry-20260923.log. Do not erase the first failure,
restart the active retry, or treat the isolated pass as full release proof.

## 2026-09-23 — First guarded release stopped on model-test wall clock

Deployment30afe7d did NOT reach restart. Unit gate4373pass31skip; model gate
99pass1fail in853s. Only failure is
test_trajectory_evaluation_behaviour.py::test_two_reminders_are_both_written:
stopped='the wall clock ran out', not one of the allowed completion stops.
See /tmp/codex-trading-release-20260923.log. This code/prompt was unchanged by
the trading release; concurrent local-model load is a hypothesis, not proven.
An isolated unchanged case is running via scripts/gate.sh, log
/tmp/codex-trading-release-timeout-check-20260923.log. No gate/assertion/config
was weakened, no model service changed. Live marker remains a89bba40. Read the
isolated result before any guarded retry; do not blindly restart active work.
Prepared postdeploy read-only API/browser check /tmp/verify-live-dashboard.mjs
requires a short-lived local bearer token in runner-local auth JSON; do not
print credentials. It has not run against a newly deployed artifact yet.

## 2026-09-23 — Whole trading-dashboard wording audit authorized

User now requires every word to be correct, useful and nonredundant. Three
isolated OpenCode workers use spark/deepseek-v4-flash at source30afe7d:
copy_board1862162 (StockBoard/TickerChart/RecommendationTimeline/OpportunityCard),
copy_overview1862178 (DeskPanel/EconomicContext/FomcGate), and
copy_research1862215 (EntriesNow/ExecutionQuality/ForwardEvidence/FundingPreview/
StrategyBench). Exact trees/logs/owned files are in the worker manifest. Each
must read DASHBOARD_COPY_TASK.md and COPY_OWNERSHIP.json, write COPY_HANDOFF.md,
then exit. Review only completed owned diffs; never import drafts or dependencies.
No logic/redesign/strategy adoption. Check visible labels, tooltips, formulas,
account origins, timestamps, chart meanings and evidence claims; cut repetition.
Root continues the account release in parallel, then reviews/deploys wording
corrections and exercises actual rendering. Required full unit gate passed
4373 tests with31 skips; real routing gate is still running. Do not restart it.

## 2026-09-23 — Personal dashboard release in progress

Checkpoint 30afe7d integrates only the five owned dashboard files, independently
reviewed after worker exit. Root corrected formatting and comments. VERIFIED:
63 personal API/isolation/account checks; frontend typecheck; all 7 account-input
browser cases against the integration tree on port 5177; Ruff and diff checks.
Logs: /tmp/codex-dashboard-root-api-20260923.log and
/tmp/codex-dashboard-root-browser-20260923.log. Initial browser harness attempt
used a glibc image for musl dependencies and failed startup; corrected to the
existing frontend image, then all seven tests passed. No source workaround.
Worker reported 35 pre-existing failures in the broader browser suite; do not
call that suite green. Main fast-forwarded to 30afe7d without history rewrites.
Guarded scripts/deploy.sh is active from the real deploy checkout; log
/tmp/codex-trading-release-20260923.log. Deployment/runtime acceptance is still
UNVERIFIED until its gates and actual deployed browser/API checks finish.
Model containers captured in /tmp/codex-models-before-release-20260923.txt.
The incumbent entry rule remains in production guidance; no new strategy adopted.
User uses the board for real decisions and explicitly prioritizes this release.
All OpenCode workers have exited; never recopy their superseded sources.

## 2026-09-23 — Turnover review integrated; only dashboard worker active

Checkpoint175cbd5:11 owned turnover acceptance cases PASS, Ruff/format PASS.
Log /tmp/codex-turnover-integrated-20260923.log. Root corrected the worker's
fill fixture (it deducted two purchases but updated only one holding), and
removed an unsupported three-session portfolio replay claim from the report.
Source remains unchanged by this review. Read intraday-turnover-review report.
Verified per-session signal dedupe and current-cash bounds do NOT establish low
portfolio turnover: repeated later-session entries and after-fill additions have
no separate holding-period/cadence constraint. Do not silently add/tune a cooldown
or claim candidate superiority. Role is integrated/root-owned, never recopy.
Only dashboard1423440 remains active; its browser stale-BUY case is still under
correction. Wait final+exit and independently reproduce behavior before release.

## 2026-09-23 — First fixed diagnostic: insufficient adoption evidence

Integrated source98bd6c10aae552b76cdd4ebaeed9a6787b2dd094:86 targeted checks PASS
(17 source +26 parity +41 replay +2 unchanged root cases), Ruff/format/scoped
strict mypy PASS. Root independently reviewed completed source/parity ownedfiles.
Those roles are now root-owned; never recopy old drafts. Original source handoffs
are superseded. Log /tmp/codex-single-source-integrated-20260923.log.

Ran fixed snapshot ONCE: /tmp/codex-single-source-diagnostic-20260923.json plus.log.
204 requested,170 ready,34 unavailable (WRB). Candidate1entry, incumbent5, BOTH0,
neither164. Six proxies have complete20/5 labels; no paired entry-price estimate.
Insufficient evidence to promote candidate; unequal conditional return means are
not superiority. Read docs/research/intraday-single-source-results-2026-09-23.md.
No retuning/refetch/repeated unchanged run. Source image/inputs/calendars hashed
in artifact. Formula parity is verified, exact live grades/portfolio proof is not.

Dashboard1423440 remains active (~3h), working on browser stale-BUY failure;
do not import active source. Turnover1651795 remains active (~1h), no final yet.
Never restart active workers. Latest live marker remainsa89bba40; no deployment.
Continue minimal tested account release when ready; new entry strategy remains
experimental. User13%remaining: compact reviews, no new unrelated work.

## 2026-09-23 — Four parallel OpenCode jobs; user has13% usage left

User explicitly requested parallel validation and corrected the priority: prove
the entry candidate before adopting it. Four isolated spark/deepseek-v4-flash
jobs are active, no active job restarted. Existing diagnostic correction1645036
and dashboard1423440 continue. New incumbent_parity1651779 owns ONLY new
test_intraday_incumbent_parity.py and its research report, INCUMBENT_PARITY_TASK.md,
PARITY_HANDOFF.md. New turnover_validation1651795 owns ONLY new
test_intraday_turnover_acceptance.py and its research report, TURNOVER_VALIDATION_TASK.md,
TURNOVER_HANDOFF.md. Both based18e3cda; exact paths/ownership in manifest.
These independently verify real incumbent formula parity, missed-opportunity
attribution, repeat signal identity and personal funded/no-paper-leak behavior.
No real historical scores, production edits or provider calls in review jobs.
Root reviews completed owned diffs only. Keep Codex supervision compact; no
repeated unchanged polls/tests/research. Account plumbing may ship independently;
new entry strategy adoption requires comparison evidence, not software tests.

## 2026-09-23 — Single-source correction; dashboard validation still active

Root independently reproduced two failed acceptance cases on completed single-
source worker: run_diagnostic suppresses ALL events with empty eligibility, and
hash-valid pages with disconnected request cursors are accepted. Evidence:
/tmp/test_single_source_review_edges.py (immutable) and
/tmp/codex-single-source-review-repro-20260923.log (2 failed). Not integrated.
Root's original empty-timeline instruction caused the first defect. Protocol
is corrected BEFORE any real outcomes: fixed assumed grade A/nonrejecting at
each session open, identical for both methods, explicitly conditional diagnostic
and NEVER historical grades or actual live eligibility. All other fixed inputs,
dates/horizons/cohort/mapping unchanged. Correction worker1645036 review_round1,
exact SINGLE_SOURCE_REVIEW_TASK.md, requires NEW SINGLE_SOURCE_REVIEW_HANDOFF.md
plus exit; old final superseded. Only owns its new module/test. Dashboard1423440
still active, ~2h, verifying browser tests/baseline in isolated checkout. Do not
import drafts or touch its owned files. No deployment yet; live marker a89bba40.

User asks active-trader labels and chart freshness, and wants release in2–3h.
Root answered this is an aim, not guaranteed or proof of strategy superiority.
Verified deployed StockBoard: Move is trade allocation (blank for Hold), Target
is allocation under selected policy (default plan, optional research live sizing),
not signal return/profit target. Existing charts fetch every60s, daily/weekly only,
merge board snapshot; no15m candle chart currently. Quote freshness fix awaits
release. Recommended clearer labels, but no new label/chart worker or UI edits
dispatched. Finish active minimum release before expanding scope.

## 2026-09-22 — User requests active completion and dashboard release ASAP

User explicitly rejected waiting and asks to get the latest tested implementation
onto the dashboard. Root confirmed deployed image997055... and marker a89bba40;
our source changes are NOT live. No claim that new candidate is best/beat momentum.
Do not stop at restating the data blocker. Two bounded OpenCode workers now run:

- comparison_single_source PID1415486, tree comparison-single-source-20260922,
  task COMPARISON_SINGLE_SOURCE_TASK.md, final SINGLE_SOURCE_HANDOFF.md. Owns ONLY
  new intraday_single_source.py/test. Pure fixed diagnostic over supplied fresh
  response pages, derive daily references from SAME IEX15m rows. Protocol181e408
  docs/research/intraday-single-source-protocol-2026-09-22.md was committed before
  outcomes. Fixed AVGO/WRB/WDC/APTV/SPY/QQQ, entry08-03..09-18, source06-29..09-18,
  label as-of09-18close, unchanged20/5 horizons. Explicit price-component source
  change, NOT exact live parity. Root acquired /tmp/codex-single-source-snapshot-
  20260922.json (continuous filename); audit /tmp/codex-single-source-input-audit-
  20260922.json: all15pages200 with hashes/pagination checked. Five symbols have
  58 complete regular-session grids; WRB has21 incomplete dates, retained missing
  rather than repaired. No real scores yet; never refetch unchanged snapshot.
- dashboard_release PID1423440, tree dashboard-release-20260922, exact
  DASHBOARD_RELEASE_TASK.md, final DASHBOARD_RELEASE_HANDOFF.md. Owns exclusively
  DeskPanel.tsx, services/api.ts, e2e/desk.spec.ts, backend/api/v1/market.py and
  test_personal_guidance_api.py. Minimal confirmed personal equity/cash wiring,
  POST body (no cash URLs), stale-response rejection and fill/account invalidation.
  Necessary to ship corrected personal funding: existing page never passes cash.
  No design refresh/strategy change/paper borrowing. Root may not edit these
  files concurrently. Worker must test its own frontend, not deployed5173.

Both use spark/deepseek-v4-flash; inspect compact status and wait final+exit.
Review owned diffs only, never history/seeded dependencies. Root handles guarded
deployment after review: current main is ancestor of integration181e408, deploy
clone /home/animallya96/deploy/anios only untracked data/secrets, no tracked edits.
Use scripts/deploy.sh with gates, preserve model services and existing settings;
no skip-gate. Script --activate writes paper recovery code hash, does not itself
submit orders. Verify actual API + browser behavior after deployment; keep new
entry candidate experimental until evidence supports adoption. No real orders,
paid data, frozen-history rewrite, parameter mining or repeated daily baselines.
User17%usage constraint remains: targeted supervision, do not stop necessary work.

## 2026-09-22 — Preparation integrated; remaining gate is data evidence

Source checkpoint `f7703e2` integrates reviewed preparation and root-corrected
tests. VERIFIED: 55 preparation/replay checks, Ruff/format, scoped strict mypy.
Log `/tmp/codex-preflight-integrated-20260922.log`. Root replaced a false prefix
test (the worker compared the same corrupt cache twice) with separate clean
input and added duplicate-preservation and missing-session denominator checks.
All OpenCode roles have exited and are integrated/root-owned. Never recopy their
old source, restart them or import seeded dependencies/Git history.

Basis report `b989047ca00feb1ea55466f0411d752a49527f4c` is root-reviewed:
`docs/research/intraday-price-basis-reconciliation-2026-09-22.md`. Eight bounded
free IEX all/raw requests independently checked four action examples; evidence
`/tmp/codex-provider-adjustments-20260922.json`. No source caches were written.
Current AVGO/WRB responses differ from cached specimens; WDC/APTV cached values
match current all-adjusted responses despite disagreement with daily inputs.
Neither a universal correction nor all-September compatibility is established.
The original worker's raw-price and September-readiness claims are superseded.
FAILED: historical cross-provider scale compatibility. UNVERIFIED: performance
comparison, midpoint fills and live adoption. No outcomes scored or deployment.

User reports 17% weekly usage left: conserve review tokens, no feature expansion,
repeated baselines, whole-cache audits or repeated provider samples. Read existing
evidence first. Remaining work is a bounded compatible-input/forward-evidence
path, not more strategy variants. Require explicit action/adjustment provenance
across full prior-20-session history and outcome windows; four recent matching
closes are insufficient. Keep fixed 20/5-session horizons and missing outcomes.
Archived records through the cached 09-18 price end have no mature primary labels.
Stay quiet when no new actionable evidence; no new worker merely to stay busy.

## 2026-09-22 — Corrected replay verified; preparation wiring underway

Checkpoint `4730d6cb4877c7e7318cff6c20d9c9e5a2d52bf5` is pushed with the reviewed
replay and tests.124 relevant replay/cache/input/adapter tests PASS; unchanged
root9-case acceptance also passes against integrated source. Ruff/format and
scoped strict mypy pass. Log `/tmp/codex-replay-integrated-20260922.log`.
Root additionally reproduced/fixed3 edges after worker correction: newer rejection
with no grade publication resurrected stale eligibility, subsecond execution time
passed the bar grid, and data_as_of before the entry close still consumed later
entry bars. Log `/tmp/codex-replay-clock-repro-20260922.log` records that failure.
Replay is now root-owned; never recopy its old worker source or restart it.

Basis audit1191134 remains active, no final handoff yet. New bounded OpenCode
comparison_preflight1246346 owns ONLY intraday_preflight.py/test: pure preparation
of supplied cache objects with calendar/daily/history/freshness/provenance gates,
retained unavailable opportunities and per-observation eligibility receipts.
Exact COMPARISON_PREFLIGHT_TASK.md; no IO, CLI or real historical scoring.
Both active workers use spark/deepseek-v4-flash and COMPARISON_HANDOFF.md.
Inspect compact status; never import active drafts or seeded dependencies.

Historical price-scale compatibility is still FAILED, so no historical candidate
outcomes, live adoption, deployment or UI changes. Do not rerun the whole scale
audit or daily baselines. Next review basis evidence and preparation handoff,
then build the bounded diagnostic runner only after the input basis is resolved.

## 2026-09-22 — Cache reviewed; historical price-scale compatibility FAILED

Verified source `bc9a900b5ef809f9a1a14906e5100979d6d20bf4` is pushed with the
read-only cache adapter and root corrections.83 relevant tests pass, Ruff/format
and scoped strict mypy pass. Logs `/tmp/codex-cache-integrated-20260922.log`
and `/tmp/codex-verify-cache-adapter-20260922.log` include synthetic behavior and
an actual AAPL/cache/11-record read with exact source hashes. Root reproduced6
worker failures before correcting naive timestamps, invalid/conflicting archive
dates, true bounds and hashing the bytes actually parsed. Cache is integrated
and root-owned; never recopy worker source. No deployment or strategy score.

Material new finding in audit commit `4f3b4ed`: across529 symbols/782,568 paired
closing observations, median absolute scale difference0.0280% hides large
corporate-action inconsistencies (AVGO roughly10x, WRB1.5x/2.25x and others).
MSTR lacks the selected daily file. Historical scoring remains blocked on price
reconciliation; adjustment=all source code is not proof of compatible cached
bytes. Read the updated input-audit document and `/tmp/codex-intraday-scale-audit-
20260922.json` (one continuous filename), with per-file hashes. No fitted ratios,
future-completeness filtering, threshold changes or frozen-cache rewrites.

Original replay worker exited but failed9 independent root acceptance cases:
observation clock, duplicate/extended-hours proxy fills, partial eligibility
fallback, mutable horizons, duplicate denominators, reversed missed opportunities,
explicit label availability and relative price units. Correction worker1150197
is active, review_round1, exact REPLAY_REVIEW_TASK.md. Wait for NEW
REVIEW_HANDOFF.md, not its old COMPARISON_HANDOFF.md. Unchanged root acceptance:
`/tmp/test_intraday_replay_review_edges.py`; log `/tmp/codex-replay-review-repro-
20260922.log`. No replay source has been integrated.

New comparison_basis1191134 is a bounded read-only OpenCode audit, owns only
its new reconciliation report and COMPARISON_HANDOFF.md. Read its exact task.
Both workers use spark/deepseek-v4-flash; never restart active work or import
drafts. Manifest/MAC_CONTINUATION.md carry ownership. Next: independently review
replay corrections and dated scale evidence, then wire tested input gates before
any historical diagnostics. Live momentum superiority remains UNVERIFIED.

## 2026-09-22 — Research input freshness and exchange-calendar gates verified

Source checkpoint `47015bfbd4c4e26a39e22dbac44ef6afaa6590c1` is pushed.
Root-owned `intraday_inputs.py` reads the reviewed 2019–2028 calendars, counts
early closes for outcome horizons, rejects unknown calendar coverage, and
requires the preceding20 exchange sessions rather than any20 available rows.
Archived eligibility uses actual publication plus the existing current/next-
session freshness rule. A missing replacement grade stays unknown; stale older
records cannot revive it. A daily record published before its session closed is
not accepted as point-in-time final daily evidence.

VERIFIED:54 input/adapter checks pass, including10 new input cases; Ruff/format
and scoped strict mypy pass. Log `/tmp/codex-intraday-input-gates-20260922.log`.
No candidate outcomes or deployment claims follow from these input tests.

Two isolated OpenCode workers remain active: comparison_replay979209 and new
comparison_cache1068445, both spark/deepseek-v4-flash. Replay owns only its new
module/test. Cache owns only new intraday_cache.py/test: explicit partition and
basis, raw observation preservation, actual recorded eligibility and source hashes.
Read their exact task files; wait for COMPARISON_HANDOFF.md and process exit.
Never import active drafts, restart active workers, or recopy integrated roles.
Root owns the new input gates; no worker may replace them. Loader provenance,
replay correctness and cross-provider scale compatibility remain review gates
before historical scoring. Personal guidance still uses incumbent entry inputs.

## 2026-09-22 — Causal comparison adapter verified; outcome replay underway

Checkpoint `425ef664e9a86a785340bcbe335d6ac8d5ebe0dc` is pushed with the reviewed
adapter and historical calendar. **131 relevant tests pass**, including44
comparison cases. Root reproduced/fixed after-close incumbent readiness and
naive availability, then added mandatory raw/adjusted basis, scale-equivalence
proof and ledger unit protection. Log `/tmp/codex-comparison-integrated-20260922.log`.
Ruff/format and scoped strict mypy pass; transitive legacy typing debt remains.

Adapter/calendar roles are integrated and root-owned. New isolated OpenCode
comparison_replay PID979209 owns only `intraday_replay.py` and its new test:
causal observation replay, next-consecutive-bar-open proxy, fixed20/5-session
outcomes, explicit missing/immature labels and common comparison denominators.
No cached historical scoring or CLI yet. Read its exact task and wait for
COMPARISON_HANDOFF.md; never restart active workers or import drafts.

All existing data/eligibility caveats remain: this is an experimental flat-account
entry-component comparison, not verified portfolio profitability or live momentum
superiority. Recorded eligibility lacks mature primary labels at the cached end.
No UI, deployment, real orders, model changes or repeated daily benchmarks.

## 2026-09-22 — Input audit reviewed; raw/adjusted and availability gates clarified

Checkpoint `6df1109` integrates the root-corrected comparison input audit and
explicit price-basis clarification, before outcomes. Cached Alpaca intraday bars
use adjustment=all; do not feed them into raw conversion formulas. Tests must
prove raw/adjusted scale equivalence and explicit basis before scoring.

Root also verified saved session dates are not availability: the09-14 record
was written09-15 at10:18:21 New York. Earlier entries cannot use it. Grades are
deterministic, contrary to the worker's original model-output claim. Earliest
archived-grade entry09-08 has a20-session outcome on10-06, outside the09-18
cache. Primary comparison remains unmeasurable on that archive; do not shorten
the horizon or substitute an unrelated old candidate evaluation.

Evidence role is integrated/root-owned. Adapter796057 remains active; wait for
its final handoff, then review against the updated root protocol (its seeded
copy predates units clarification). New calendar888056 independently verifies
2019–2025 official exchange schedules. Manifest/tasks/MAC_CONTINUATION.md
describe exact ownership. Root added a verified2026–2028 early-close data file;
the entry engine does not yet consume it. No historical scoring or deployment.

## 2026-09-22 — Comparison protocol fixed; two bounded OpenCode workers active

Protocol checkpoint `b507f70` fixes the level mapping, comparator, eligibility,
dedupe, execution proxy and outcome horizons before candidate historical scoring.
Read `docs/research/intraday-comparison-protocol-2026-09-22.md` before proceeding.
New workers: comparison_adapter PID796057 and comparison_evidence PID796070,
baseaa73e5d, same spark/deepseek-v4-flash. Manifest and root MAC_CONTINUATION.md
record ownership. Both use COMPARISON_HANDOFF.md; do not restart active workers.
Original three workers are integrated and their files remain root-owned.

Adapter implements a pure synthetic-tested comparison boundary; evidence audits
dated eligibility, adjustments and calendar support without computing returns.
Historical scoring waits for root review of both. Price-only or prior-night-grade
diagnostics must not be called exact live momentum reconstruction. Declared20-day
primary outcomes may be immature for the short saved-record archive; that is
insufficient evidence, not permission to change the horizon. No new strategy has
been proved superior, deployed or connected to the personal guidance route.

## 2026-09-22 — Personal account integration reviewed and pushed

Verified source checkpoint `95ee6fada42b2e6b7f73d0d207286306632bbc1b` on
`codex/trading-integration-20260922`: **272 relevant checks pass**, including
11 ASGI API cases plus personal isolation, funding, paper and parity suites.
Log: `/tmp/codex-personal-combined-20260922.log` on Spark1. All three OpenCode
workers are finished and integrated; root owns their files. Never recopy worker
source over root corrections. Manifest `/tmp/codex-intraday-workers-20260922.json`
and root `MAC_CONTINUATION.md` carry current ownership and next steps.

Personal recommendations now use actual holdings and optional explicit cash,
with eligibility checked before and after shared funding. Unknown cash cannot
claim a funded buy. No uncovered liquidation or invented sale proceeds; paper
remains separate. Root reproduced and corrected six additional boundary cases,
including paper cash-scope leakage, unfunded entries and invalid account prices.
Ruff passes for changed source/new tests; one pre-existing PT006 in the old
decision test was reproduced at the parent and excluded from that lint check.

No deployment or UI changes. Entry engine checkpoint `1a2c2c1` remains an isolated
research library, with its earlier80 tests; these changes do not make it live.
Performance relative to unchanged momentum is **UNVERIFIED**. Next: fixed causal
setup mapping and fair entry-quality/turnover comparison on identical eligible
data, zero added costs and an honest execution proxy. No fitting or threshold
search; no midpoint-fill or best-strategy claim. See the detailed root handoff.

## 2026-09-22 — Causal entry research engine integrated; 80 checks pass

Root checkpoint `1a2c2c1aa513667b7aa85f014d80acf94b365716` is pushed on
`codex/trading-integration-20260922`. The entry correction worker exited and its
reviewed owned files were integrated. Root now owns those files and additionally
fixed missing-newest-candle readiness: an old prefix preserves its trigger/event
but becomes unavailable when the next completed observation is missing. Never
recopy the worker's source over this correction.

VERIFIED: **80 tests pass**, including 39 entry cases, with Ruff/formatting and
strict mypy clean. Log `/tmp/codex-entry-integrated-20260922.log`. Tests cover
causal filtering, confirmation timestamps, immediate/later invalidation, gaps,
OHLCV validity, evolving daily context, stable identity and current-bar freshness.
UNVERIFIED: live wiring, performance versus momentum, actual midpoint fills and
half-day support. The candidate stays isolated research code; no deployment/UI.

Personal correction worker PID602840 remains active; wait for REVIEW_HANDOFF.md.
Root independently found its draft applies the personal unknown-cash gate to the
explicit-target paper path too. See `/tmp/test_personal_account_review_edges.py`
and `/tmp/codex-personal-second-review-20260922.log`. Root will correct scope after
the worker exits and validate the combined API/account/paper path. API wiring and
shared-test updates are staged, not integrated; paths and ownership are recorded
in root MAC_CONTINUATION.md. Check actual import paths before trusting a worker
test run pointed outside its checkout.

Cached intraday data exists on Spark: latest `bars_15m/asof=2026-09-20` has 530
files and 19,871,542 rows, with raw timestamp bounds 2019-01-02..2026-09-18.
SPY/QQQ are absent from that partition. Metadata inventory:
`/tmp/codex-intraday-input-inventory-20260922.json`. These bounds are not proof of
shared causal coverage or point-in-time eligibility. No outcomes inspected,
strategy fitting, history rewrite or completed daily-baseline rerun.

## 2026-09-22 — OpenCode correcting rejected entry and account submissions

All initial workers exited. Entry final still fails the 13 independent acceptance
cases; personal source still needs action gating after cash sizing and protection
for uncovered holdings. Neither source was integrated. Two bounded corrections
are active: entry PID602839 and personal PID602840. Manifest
`/tmp/codex-intraday-workers-20260922.json` now records `review_round=1`, updated
logs and original process receipts. Read their `*_REVIEW_TASK.md` files and wait
for **REVIEW_HANDOFF.md**, not the old handoff. Never restart an active worker.
Personal worker rebased its own branch; import only reviewed owned file diffs,
never that history or seeded dependencies. Root branch remains `f49db2a`.

Root staged optional personal `available_cash` API wiring at
`/tmp/codex-market-api-intraday-candidate.py` on Spark1, forwarding to `build(cash=)`.
**6 HTTP validation/ownership checks pass**: invalid cash is rejected before quote
collection and holdings remain unchanged. Log
`/tmp/codex-personal-api-boundary-20260922.log`. Original API source restored after
this isolated validation; full integration waits for corrected personal code.
Root `test_personal_guidance_api.py` has 11 cases covering account isolation,
known/unknown/invalid cash, stale evidence and ownership. Its price fixture now
explicitly matches its expected personal weight. Current unchanged source has
10 expected failures and 1 pass; no full behavior/deployment claim.

Hourly continuation now recognizes correction-round ownership and final handoffs.
No UI, orders, model changes, strategy fitting or repeated daily benchmarks.

## 2026-09-22 — Quote boundary fix reviewed; entry and personal work still active

Root integration checkpoint `f49db2a738cc2635f7462dd86643dbc287da6b0e` is pushed
on `codex/trading-integration-20260922`. It preserves published branch history
and merges current main handoffs. Only completed quote-worker owned files were
integrated. VERIFIED: the 09:59-to-10:00 stale-cache regression fails before the
fix, then **78 relevant checks pass**, including existing HTTP route checks;
Ruff and formatting pass. Log: `/tmp/codex-intraday-quotes-reviewed-20260922.log`.
UNVERIFIED: deployment and real-feed acceptance. No deployment or UI changes.

Entry and personal OpenCode workers remain active; do not restart them. Root's
independent review of the entry draft reproduced 13 failing boundary cases:
future-data validation affecting an earlier prefix, setup-bar invalidation,
trigger timestamps before close confirmation, invalid OHLCV, gaps/grid validity,
daily context frozen after a trigger, and old-session readiness. Tests are at
`/tmp/test_intraday_entry_review_edges.py`, log
`/tmp/codex-intraday-entry-review-repro-20260922.log` on Spark1. These findings
are against a draft, not a completed worker submission. Do not integrate until
reviewed and corrected. Root also owns new `test_personal_guidance_api.py` in
the integration checkout: **2 reproduced failures, 1 ownership check passed**.
The HTTP route currently reports paper weight instead of personal weight and
still says Buy on an expired quote. Log `/tmp/codex-personal-api-repro-20260922.log`.
Coordinate final route wiring with the personal worker's eventual API contract.

Read root `HFT_TRANSFER_ADDENDUM.md`: transfer ordered-path ideas to 15-minute
entries, without inferring true order flow from OHLCV or claiming ML/edge already
exists. Current entry candidate stays isolated and experimental; no training,
threshold search, data purchases, live orders or repeated daily backtests.

## 2026-09-22 — OpenCode implementing the 15-minute entry layer

User explicitly requested OpenCode implementation. Three isolated sessions launched
on Spark1 with spark/deepseek-v4-flash; no model-service changes. Manifest
`/tmp/codex-intraday-workers-20260922.json`; source basee71b906. Read each worker's
INTRADAY_TASK.md for ownership and INTRADAY_HANDOFF.md when finished. Never restart
an active worker or copy seeded dependencies.

- entry: new intraday_entry.py, test_intraday_entry_structure.py and research
  contract only; causal completed15-minute sequence, evolving daily candle,
  supplied setup/levels, explicit invalidation/ambiguity and stable signal identity.
- quotes: live_quotes.py and its tests only; reproduce/fix cache extending across
  a completed15-minute boundary while preserving causal completed-bar filtering.
- personal: decision_view.py and new personal isolation tests only; personal
  guidance must not borrow paper weights/cash/fills; stale entry evidence must
  not imply fresh executable readiness. Root handles any necessary route wiring.

Read-only running-container audit pinned image
sha256:997055765439e8d37539430c7ed87bb3707c6a619615532fecee18b057b4da90.
It found daily technical features recomputed on one aggregated partial-day OHLC
row, not a preserved15-minute path; personal/paper action coupling; and freshness
often advisory on BUY. These are implementation/scope findings, not proof the
momentum strategy loses money. No new strategy has yet beaten live momentum.
New entry logic stays experimental until compared on identical causal data and
user's zero-cost convention, with turnover/repeated signals/missed fills measured.
No dashboard changes, live orders, fitting, threshold sweeps or desk.run authorized.

## 2026-09-22 — Precise 15-minute entries are required

User corrected the interpretation of avoiding overtrading: "i told you we need
precise entries on the 15 min timeframe". The personal dashboard must provide
precise entry setups/triggers on15-minute bars. Avoiding overtrading means
rejecting weak/repeated signals and unnecessary position churn, NOT replacing
15-minute timing with daily-only entries or imposing an arbitrary slow cadence.
Portfolio selection/sizing and15-minute entry timing are separate decisions;
paper execution remains a separate account/section.

The fixed daily next-open vol/vol_trend evaluation does NOT validate15-minute
entry quality. This work has not established that layer as complete. Inspect the
existing intraday/entry implementation and validate causal15-minute triggers,
invalidation, stale signals, repeat alerts and midpoint-target fill assumptions
before claiming the user's dashboard workflow is ready. Do not invent thresholds
or infer that15-minute precision requires frequent trades.

## 2026-09-22 — Portfolio guidance must avoid overtrading; paper is separate

User clarification: "remember to avoid overtrading, this dashboard will be used
by me to make buys in my portfolio. the paper trading is its own section in the
dashboard". Treat this as a product and strategy requirement, not permission to
execute trades or begin dashboard changes ahead of implementation validation.

The main dashboard supports the user's discretionary decisions using their own
holdings, cash and allocation; the paper account has separate positions, cash,
orders and performance in its own section. Never turn paper fills or its rebalance
clock into instructions for the user's actual portfolio. Shared signals do not
make the accounts interchangeable. Account scoping must remain explicit.

Avoid unnecessary turnover even with the requested zero-cost assumption and
midpoint execution target. Prefer HOLD when the investment case has not materially
changed; surface additions, trims or exits only with a clear reason. Evaluate
trade count, turnover, holding duration, rapid reversals and recommendation
stability alongside return/drawdown. Do not copy the experimental daily resizing
into personal recommendations or choose arbitrary cooldown/band thresholds without
validation. Earlier measured policies turned over roughly10–11timesNAV annually
(two-way); that is a diagnostic concern, not an accepted personal trading cadence.
This entry records the requirement; no new anti-churn logic or dashboard UI is
claimed implemented by this documentation change. Paper remains experimental.

## 2026-09-22 — User requests zero costs and midpoint execution target

Latest instruction supersedes cost-stress emphasis: "forget trading costs try to
hit mid price". Midpoint is the desired execution target, not a claimed fill.
Historical inputs contain daily OHLC/adjusted prices, not timestamped bid/ask
history. Live quote reads are ephemeral. Therefore the new evaluation is explicitly
**zero-cost next-open proxy**, not a verified midpoint backtest. No broker/order
configuration was changed; no real trades or new data downloads.

Ran fixed vol/vol_trend at0bps on sourcee71b906, same2016-01-04..2026-09-18,
NAV1/next-open/zero cash yield, explicit researchSPY eligibility; no fitting or
window/threshold changes. Both benchmarks also use0bps. CAGR/maxDD:
vol23.2805%/23.8314%; vol_trend18.0976%/14.9875%; SPY15.0857%/33.7173%;
QQQ20.0853%/35.1187%. Vol meets both full-window objectives and40.2294% of
overlapping252-session windows; vol_trend still failsQQQ return (rolling29.4551%).
Both trace checks clean. These remain reused survivor-biased history.

Artifacts on Spark1 `/tmp/codex-mac-zero-cost-20260922/zero-cost.json` plus
candidate arrays/traces, input/source/script hashes; script
`/tmp/codex-trading-zero-cost-20260922.py`. Earlier10/25bps artifacts preserved,
not relabeled. Future execution work should measure quote-midpoint limit fills
and unfilled orders rather than assume that every midpoint attempt executes.

## 2026-09-22 — Experimental trading checkpoint published; no adoption

Source checkpoint `e71b906d60709876c93f7fd177b64aad9ac8294e` is pushed on
`codex/trading-integration-20260922`. All six OpenCode workers finished. Spark1
checkout `/home/animallya96/codex-worktrees/trading-integration-20260922` has no
tracked modifications; only its local `MAC_CONTINUATION.md` is untracked.
Do not restart completed workers or repeat the fixed historical simulations.

VERIFIED: **374 focused tests passed**,5 existing warnings; exact tested tree
`245d9f126c8cff959ded113a4724c4fca6ddc6e8` retained through rebase. Broad relevant
validation:874 passed,2 skipped,2 failed. FAILED: both learned-ranker score-coverage
tests reproduce identically on untouchedbase2d89aa8 (34missing rows, first213).
Five Ruff findings in market.py also reproduce on that base; all other changed
Python files pass. Logs on Spark1: `/tmp/codex-mac-final-focused-20260922.log`,
`/tmp/codex-mac-trading-broad-20260922.log`,
`/tmp/codex-market-model-baseline-failures-20260922.log`.

Paper now preserves exclusions across save/load and scheduled refresh, uses the
same exclude-before-fallback order as simulation, and sizes from marked holdings
plus cash rather than stale external NAV. Whole-share risk/cap cuts cannot round
below an executable reduction. Next-open timing survives pending and dispatch.
UNVERIFIED: full deployment gates, live behavior, untouched strategy edge.
Nothing deployed/adopted; no orders, UI, model-service changes or real-data fitting.

At10bps, vol CAGR22.01%/DD24.59% passes both full-window benchmarks but only34.08%
of rolling windows. At predeclared25bps, CAGR20.13% barely exceedsQQQ20.06%, and
rolling success drops to25.44%. Vol_trend failsQQQ return. Reused survivor-biased
history does not justify adoption. Corrected primary-paper review specifies one
prospective10-session hypothesis with true PIT membership/inputs and overlap
purging; it authorizes no training or parameter sweep.

On the source branch, see `docs/research/trading-funded-validation-2026-09-22.md`
and `docs/research/trading-ml-path-2026-09-22.md`. Fixed artifacts remain under
`/tmp/codex-mac-evaluation-reviewed-20260922/` and
`/tmp/codex-mac-cost-stress-20260922/`. Next adoption decision requires genuinely
untouched evidence and the normal gates; do not promote on the backtest aggregate.
Diagram impact: NONE. Main receives this handoff only, not experimental source.

## 2026-09-22 — Mac owns trading continuation; implementation before dashboard

Windows is powered off. User transferred supervision to Mac task
`01a0c73c-000d-7d13-bc6b-2b884f639dec`, requested efficiency, no dashboard work
before the implementation is established, and six parallel OpenCode sessions
overnight. Direct SSH `animallya96@172.16.8.3`/`.5` verified from Mac.
Mac heartbeat `continue-trading-implementation-on-mac` is active hourly.
Do not resume the old Windows supervisor or its old worker PIDs concurrently.

Root continues in Spark1 `/home/animallya96/codex-worktrees/trading-integration-20260922`,
branch `codex/trading-integration-20260922`, base `2d89aa8`. Source is UNCOMMITTED
and NOT DEPLOYED. Read its `MAC_CONTINUATION.md` for exact ownership and next steps.
Current six isolated worker PIDs/logs/paths: `/tmp/codex-trading-mac-20260922.json`.
Compact status: `/tmp/opencode/fv-venv/bin/python /tmp/codex-trading-mac-status.py`.
Workers write `MAC_HANDOFF.md`; integrate owned files only, never seeded dependencies.
Roles: paper correctness, funded order sizing, simulator, read-only policy review,
next-open benchmark controls, primary-paper HFT/ML research. No model/service changes,
training, paid data, real orders or dashboard changes authorized by these tasks.

VERIFIED: root integrated previous finish workers, corrected evaluator calendar,
actual-exposure, ledger checks and false-exit alignment. Found risk orders were
still sent to close/cancellable on a green open; fixed timing/persistence/dispatch
and preserved legacy defaults. Existing `finished` exits now reach funded planning.
**295 focused tests passed**, 5 existing numerical warnings; log
`/tmp/codex-mac-integrated-tests-20260922.log`. Model/live deployment acceptance
not implied. Root additionally owns paper.py, market_daily.py, market_balancer.py,
evaluator/CLI and test_funded_execution_dispatch.py; do not overwrite these.

Preliminary fixed 2016-01-04..2026-09-18 comparison, explicit research SPY eligibility,
NAV1/next-open/10bps/zero cash yield: vol CAGR22.01%, DD24.59%; vol_trend CAGR16.78%,
DD15.30%. Independent scorecard reproduces these. Vol meets both SPY/QQQ full-window
objectives but only34.08% of overlapping252-session windows; not proof of dominance.
Artifacts `/tmp/codex-mac-evaluation-preliminary-20260922`. Exposure-matched controls
remain UNVERIFIED (old evaluator used same-close fills); controls worker is correcting
them. No policy adoption or claim of a universally best strategy. Complete owned
reviews, corrected controls and final evaluation before considering deployment.
Diagram impact: NONE — execution/accounting corrections preserve architecture.

## 2026-09-22 02:20 UTC — Combined backend assembled; 97/99 tests pass

All six previous workers finished/exited. Root created isolated integration
checkout `/home/animallya96/codex-worktrees/trading-integration-20260922`, branch
codex/trading-integration-20260922, base2d89aa8. Copied OWNED simulator+paper+API
source/tests and acceptance test only; no UI/evaluator source imported. No commit
or deployment. Root tests with --runxfail: **97 passed,2 failed**, log
/tmp/codex-integrated-backend-tests-20260922.log. Exact reproductions now PASS
fees/post-fee NAV, index permission/no-add, canonical/populated API rows,
future-context rejection and pending-resolved retry.

Remaining test failures: ineligible heldSPY400/target200 sells400 (must sell200,
not force liquidation); raw legacy _Book.equity missing-price assertion bypasses
optional funded path's guards. Test the actual funded journey, retaining default
2693-session invariance. New real paper->API roundtrip FAILED projected total
0.999001: paper metadata still divides after-fee positions/cash by pre-fee NAV.

CURRENT five bounded finish workers (all predecessor exits confirmed):
simulator3713600, paper3713603, evaluation3713606, acceptance3713611, UI3713615.
Same per-role checkouts, each CODEX_FINISH_TASK.md; logs
/tmp/codex-opencode-finish-<role>-20260922.jsonl. role-current.tsv overrides and
compact status helper updated. API is finished/idle; don't resume original PIDs.
Simulator only fixes partial index reduction; PAPER immediate explicit company
exit plus post-fee metadata roundtrip; EVAL deletes duplicate strategy ledger
and calls integrated simulate.run; ACCEPTANCE removes truly resolved strictxfails
and tests funded missing NAV; UI executes queued chart cleanup. Expected existing
role handoffs revised (simulator PROJECTION_HANDOFF.md). No broad new work.

EVAL/PAPER/ACCEPTANCE received updated shared simulator dependencies from combined
tree; never import their seeded dependency copies as owned diffs. PAPER additionally
received reviewed allocation_view.py for real producer-consumer test, not ownership.
Paper projection addendum copied to CODEX_FINISH_TASK.md just after dispatch;
verify it was consumed. All five PIDs verified alive. Root owns integration tree;
do not let parallel workers write it. No strategy outcome claimed or deployed.
Unrelated changes preserved; diagram impact NONE for coordination evidence.

## 2026-09-22 01:15 UTC — Narrow remaining correction; reduce supervision cost

User reports57% credits consumed and insufficient results. Reduce repeated
supervision: hourly heartbeat, compact status only when all workers still active,
no repeated code reads/tests/doc commits for unchanged state. Focus existing
shared allocation, fixed comparison and accurate one-table/charts; no new research.

Simulator initial worker finished DAILY_EXECUTION_HANDOFF.md; PID3317369 exited.
Root independently ran funded-simulator/incumbent/allocation tests: **51 passed**.
Fee projection remains known failing boundary. CURRENT simulator **PID3617220**,
fresh narrow task, log `/tmp/codex-opencode-projection-only-20260922.jsonl`,
simulator-current.tsv override. Own only funded_execution.py plus projection
tests; exact cash84985/NAV99985 example supplied, no broad reread. Expected
**PROJECTION_HANDOFF.md**. Add projected amount/NAV fields compatibly; missing
valuation gives no invented projection. Other workers unchanged; do not restart.
Use current role overrides, not original PIDs. No source integrated/deployed yet.

All pending correction notes/chart follow-up below remain required. Default
2693-session invariance already proved; do not rerun without material change.
Diagram impact NONE, coordination/test evidence. Unrelated files preserved.

## 2026-09-22 00:50 UTC — API canonical schema improved, populated-row crash found

All six workers still active with unchanged PIDs; no replacement launched.
API consumed review and corrected canonical bucket handling: root's original4
reproductions now reject missing/legacy malformed inputs and preserve the valid
bucket example. **FAILED new actual populated-row reproduction:** valid AAA/SPY/
CASH detail raises KeyError('stock'). _rows_agree_with_buckets uses singular
kind stock/index against plural bucket keys stocks/indexes. Root expanded
check-parallel-api.py (remote /tmp/codex-check-parallel-api.py) and appended exact
correction to active API's CODEX_API_REVIEW.md. Reading this addendum UNVERIFIED;
verify actual populated HTTP payload after repair, not only empty-row examples.
Original requirements also include version/boolean-weight validation.

API additionally edits backend/api/v1/market.py to pass expected_account=user_id
to decision_view.build. This is necessary scope extension within its API role,
no competing writer in that file; root must review actual HTTP provenance path.
No new source integrated/deployed. Simulator is writing tests; paper/evaluation
still finishing initial tasks, UI/acceptance reviews continue. Do not repeat
unchanged tests or baseline while waiting. Starting main4457f458, pull up to date,
unrelated evaluations preserved. Diagram impact NONE, review evidence only.

## 2026-09-22 00:25 UTC — Real-data default-path compatibility independently verified

All current workers still active, same PIDs. API wrote initial handoff but stayed
running and READ CODEX_API_REVIEW.md plus root reproducer; let its correction
finish without a second writer. UI review session confirmed
ses_f39a8e475ffemADG036QT1NqCh, PID3463055. Its queued CODEX_CHART_FOLLOWUP.md must
be explicitly dispatched after current UI review finishes. PAPER/EVAL still
working; their queued boundary-review consumption remains unverified.

**VERIFIED real-data default invariance:** root ran changed simulate.run with
the exact incumbent arguments from prepare-common-window.py on the trusted
corrected report (no desk.run or new strategy scoring). All2693 dates match;
returns and NAV equal frozen common-window-reference to absolute1e-12. Source
hashes unchanged during check. Evidence remote
/tmp/codex-trading-evaluation-inputs-20260921/root-default-simulator-check.json;
external check-default-simulator.py. simulate SHA36ab2ad82f4831147b5aa9273935c217e109ed7ab5f063c8c92e3a9186a67ee1;
funded_execution94819af333fdaea97c77a3c1d0bf8635a7e50a1512281b58a8baf39bf1e30ef7;
paper20203bb838841621e0cac794911511ff0d4be9ccc8c4ff13d7ae795b7d1205f8.
Expected rolling-window empty-slice warnings occurred; evaluated output matched.

Root reran index/post-fee reproducer against new funded hash: index guard and
held-SPY exit still pass; post-fee cash fraction STILL FAILS. This does not accept
new allocation behavior. No new source integrated or deployed. Preserve pending
review tasks; no repeated baseline run unless source/default behavior changes.
Starting maine4ff2d00, pull up to date, unrelated evaluations preserved.
Diagram impact NONE — independent verification and coordination evidence.

## User clarification — legacy breakout chart overlays

User asks why charts still show breakouts and whether replacement removes them.
Source: TickerChart.tsx entryMarkers maps chart.entries to replayed price-only
upper20-day-band dots; these are not funded BUY records. Legacy paper policy
still uses graded breakouts. New allocation is not deployed or proven superior.
Chart legend's 'only exit' downgrade claim cannot describe risk-allocation exits.
Queued **CODEX_CHART_FOLLOWUP.md** in UI checkout (external chart-policy-followup.md)
for explicit dispatch AFTER current UI review handoff: remove default legacy
breakout dots/legend, only use actual dated/versioned decision or fill evidence
for trade markers, otherwise omit them honestly; fix exit description and browser
test no fabricated trades. Preserve historical decisions. No concurrent UI writer.
This chart follow-up is part of remaining UI acceptance before deployment.

## 2026-09-21 23:45 UTC — UI review dispatched; index-permission fix reproduced

UI initial worker finished PARALLEL_UI_HANDOFF.md and PID3264500 exited.
Worker reports7 allocation+33 desk browser checks and build passed on its own
checkout; root verified mount earlier, not those verdicts. Review REJECTED
integration: UI reads DeskPayload.portfolio_allocation while actual API/tests
return mine.decisions.portfolio_allocation. Existing DeskPanel has mine.decisions
state. Date-only rendering and malformed-version guard also remain incorrect.
CURRENT fresh UI **PID3463055**, same checkout, new session (discover via log),
`/tmp/codex-opencode-parallel-ui-review-20260921.jsonl`, ui-current.tsv override.
Task **CODEX_UI_FOLLOWUP.md** directs these three fixes and browser fixtures on
the real nested response path, plus refresh/stale response behavior. No second
writer; previous process exit confirmed. Other workers unchanged and active.

Simulator draft now contains scheduled stable composition and dated inputs.
**VERIFIED focused root reproduction:** index_eligible=False produces NO buys in
continuous/whole modes; True buys400 SPY atprice200 with100000cash, target0.8.
An existing400-share SPY position still exits with permissionFalse. **FAILED**
post-fee projection: AAA15% purchase still reports .cash=.85 from old complement,
expected84985/99985. Actual plan_funded source still divides holdings by original
equity and sets cash=1-sum, ignoring fees. External check-parallel-review.py now
asserts all these properties and fails the final projection assertion. This is
already required by contract; keep it open for simulator handoff review.
Tested funded_execution SHA256d344978a2b7d6211ce1d50ac79381c29e8b2020c4ebbf109001ae76cf428ed0c;
simulate36ab2ad82f4831147b5aa9273935c217e109ed7ab5f063c8c92e3a9186a67ee1.
No new source integrated/deployed; pending API/PAPER/EVAL reviews below remain.
Starting main56fb2572, pull up to date, unrelated evaluations preserved.
Diagram impact NONE — review/coordination evidence only.

## 2026-09-21 23:20 UTC — Acceptance follow-up launched; paper/evaluation review

ACCEPTANCE finished PARALLEL_ACCEPTANCE_HANDOFF.md, PID3264502 exited. Root
rejected its incorrect index-permission assertions and incomplete causal tests.
CURRENT acceptance **PID3427220**, NEW session **ses_f39bfb482ffeZkKypCJKIJTIAf**,
same checkout, log `/tmp/codex-opencode-parallel-acceptance-review-20260921.jsonl`.
Override `/tmp/codex-opencode-parallel-acceptance-current.tsv` is honored by
compact status helper. Fresh bounded task explicitly requires no ineligible SPY
buys in either quantity mode, consistent economic fixtures, explicit dates,
future-change tests, missing held NAV, full-exit trace and post-fee projections.
Actual product failures must remain strict xfail with evidence, never weakened
assertions or production edits. Revised handoff remains expected. Other five
workers still active, unchanged; do not launch another writer in their areas.

**FAILED actual paper.plan reproduction**, external check-paper-context.py:
requested2025-09-08 with context dated2025-10-27 generated AAA buy111/SPY buy629
and future as_of. Require session/context-date equality before using data or
marking a session. Pending block also marks sessions_seen; clearing pending then
retrying same date returns 'already planned', preventing action. Root isolated
that boundary; final proof must use actual settlement/journal and persistence.
Source review flags empty stable_desired fallback resurrecting caller selection,
and company exits delayed to next rebalance rather than explicit immediate removal.

EVALUATION wrote1237-line module including a second _FixedFundedLedger. Reject
that candidate-execution duplication: use reviewed integrated simulate.run and
shared plan_funded/_Book. Root independently checked useful metrics on frozen
reference (initial NAV row excluded, no missing evaluated returns): incumbent
CAGR43.56731585%/DD34.23146374%, SPY15.07488604%/33.71726769%,
QQQ20.07402717%/35.11871218%, exactly matching prior controls. This verifies
baseline metric arithmetic only, not candidate execution or strategy edge.

PAPER/EVALUATION review saved externally
parallel-paper-evaluation-review-20260921-2320.md and each checkout's
CODEX_BOUNDARY_REVIEW.md. Reading is UNVERIFIED while active; send corrections
explicitly when their current handoffs finish. Earlier API/UI review still open.
UI browser container shared-ui-dev mount independently verified to point at its
isolated frontend checkout, not deployed code; browser outcome not yet accepted.
No source integrated/deployed. Starting maina0468bb2, pull up to date, unrelated
evaluations preserved. Diagram impact NONE — review/coordination evidence only.

## 2026-09-21 22:50 UTC — API draft and acceptance assertions rejected

Six processes still active, same PIDs/sessions; no final handoffs. API now has
allocation_view.py and decision_view wiring, PAPER has state/order edits, UI
has98-line StockBoard diff, ACCEPTANCE has456-line/13-test suite. Simulator and
evaluation remain reading/generating without new owned source. No restarts this
check. No source integrated or deployed.

**FAILED root reproduction of actual API serializer** (external
check-parallel-api.py, remote /tmp/codex-check-parallel-api.py): as_of-only input
reports available/100%cash; .8+.8 weights reports available/160%stocks; SWVXX with
no capability becomes stock/eligibleTrue; agreed versioned bucket payload becomes
fictitious cash/indexes/stocks symbols and100%cash target. Serializer invented a
different input protocol than PARALLEL_CONTRACT. Reject until canonical payload,
missingness, totals and capabilities validated. Verify actual API caller passes
freshness/account evidence and rendered UI consumes exact resulting shape.

Root ran current independent-test draft: **13 passed**, but source review finds
test_spy_is_exempt_from_the_name_cap_only_when_index_eligible explicitly expects
the known permission bug (False merely capped) and lacks required benchmark
dates. Passing this suite does NOT validate the corrected contract. Require
economically consistent tests that actually fail the defects; do not weaken
assertions. Review also rejects cash-complement-only projection proof.

Corrections saved **parallel-api-review-20260921-2250.md** externally and as
**CODEX_API_REVIEW.md** in API/acceptance worktrees. Consumption UNVERIFIED while
active; explicitly send review after handoffs, preserving one writer per file.
Earlier CODEX_REVIEW_NOTES.md still applies (index execution/date rendering).
Starting main387d4ddb, pull up to date, tracked tree clean; unrelated evaluations
preserved. Diagram impact NONE — independent review/coordination evidence only.

## 2026-09-21 22:25 UTC — Independent review findings queued for parallel workers

All six current processes alive; simulator session is now confirmed
**ses_f3a04173dffe1lupkL9jg0F7mo**, PID3317369. Others unchanged. UI has actual
types/DeskPanel/StockBoard edits; other workers are still inspecting/prototyping,
without final owned source or handoffs. No completed patch to integrate yet.
No workers interrupted this check. vLLM6 running/0 queued, services unchanged.

**FAILED independent reproduction on seeded draft:** with cash=equity100000,
SPYprice200 and desiredSPY0.8, index_eligible=False still buys400 continuous
shares or75 whole shares. True buys400. Current execution incorrectly changes
the cap instead of enforcing index permission. This is already required in
simulator contract; retain until corrected. External check-parallel-review.py,
remote `/tmp/codex-check-parallel-review.py`, exercised real plan_funded.

**FAILED date rendering reproduction in partial UI:** date-only as_of2026-09-18
through the banner's new Date/toLocaleString NY expression displaysSep17,8PM.
Session dates must remain dates; convert actual timestamps only. Browser proof
required after correction. Hardcoded practice-account label also needs actual
account provenance or a neutral label; do not invent account identity.

Acceptance worker's prototype index test used cash90/equity100,SPYprice200 and
whole shares: both eligible/ineligible round to zero, hiding the defect. Its
exit fixture values positions200+cash50 but equity100. Root recorded corrected
economic fixtures; do not count prototype prints as passing acceptance tests.
Root replayed prototypes (500 conservation baskets/229-session trace) but their
missing-price-as-zero accounting cannot validate unavailable NAV behavior.

Review saved externally **parallel-review-20260921-2225.md**, copied to
simulator/acceptance/UI checkouts as **CODEX_REVIEW_NOTES.md**. Their reading it
is **UNVERIFIED** while active; explicitly send these corrections after their
handoffs, without starting concurrent writers. Other roles continue unchanged.
No source accepted/deployed and no candidate performance scored. Starting
mainf5fb335c, pull up to date, tracked tree clean; unrelated evaluations intact.
Diagram impact NONE — review/coordination evidence only.

## 2026-09-21 22:00 UTC — Parallel roles progressing; stalled simulator replaced

Objective remains reviewed funded allocation, real comparison, one-table API/UI
and deployment acceptance. **VERIFIED:** all six workers consumed their role
contracts; API/acceptance explicitly read shared contract, UI began actual type
and DeskPanel wiring edits. Other roles inspected relevant code; acceptance ran
a synthetic actual-simulator prototype. No role handoff is complete yet and no
new implementation is accepted, tested by root or deployed. All source changes
remain isolated. Do not promote a partial UI/type diff.

**FAILED worker progress:** simulator3264497 had not edited source after22min;
last finished step had124134 context tokens and the current step had made no
tool progress for about20min. Only that process was terminated; exit confirmed.
Fresh simulator **PID3317369**, SAME checkout and preserved draft, NEW session
(discover from current log), current log
`/tmp/codex-opencode-parallel-simulator-fresh-20260921.jsonl`.
`/tmp/codex-opencode-parallel-simulator-current.tsv` overrides original manifest
for this role; compact status helper now honors that override. Do NOT resume
ses_f3a31cf89ffeD66z4gDLxfOJ5l or PID3264497. Narrow fresh prompt directs the
three existing corrections, without another architecture/history reread.
Other five processes/ownership remain unchanged and must not be restarted.

Fresh role sessions now discovered: paper ses_f3a1911fcffeJKVlnN8nIRY4hG;
API ses_f3a191207ffejDR5uyk9DffAX2; UI ses_f3a1911d6ffecQU2lZ2DIp3UhZ;
evaluation ses_f3a191206ffe3OrRdVPlEqgXTu;
acceptance ses_f3a1911fcffeMzcQTm1Xkp8BjR.
vLLM at this check6 running/0 queued; no service configuration changes.
Starting maine3d8ef84, pull up to date, tracked tree clean; unrelated untracked
evaluations preserved. Diagram impact NONE, coordination evidence only.

## 2026-09-21 — Six isolated OpenCode roles explicitly authorized and launched

**CURRENT coordination supersedes all single-worker instructions below.** User
asked for parallel OpenCode sessions, noting model concurrency6. Keep one writer
per owned file, with six isolated checkouts and a shared interface contract.
Old daily worker PID3237467 was stopped and exit confirmed before seeding.
Simulator resumes its existing session; five other sessions are fresh. All use
spark/deepseek-v4-flash. No runtime configuration or live deployment changed.

| Role | PID | Checkout suffix under /home/animallya96/codex-worktrees/ | Owned implementation |
| --- | --- | --- | --- |
| simulator | 3264497 | trading-funded-allocation-20260921 | funded_execution.py, simulate.py, ledger/simulator tests |
| paper | 3264498 | trading-parallel-paper-20260921 | paper.py, optional paper_allocation.py, paper tests |
| api | 3264499 | trading-parallel-api-20260921 | allocation_view.py, decision_view.py, API tests |
| ui | 3264500 | trading-parallel-ui-20260921 | DeskPanel frontend/types, own browser spec |
| evaluation | 3264501 | trading-parallel-evaluation-20260921 | allocation_evaluation.py, market_allocation_compare CLI, tests |
| acceptance | 3264502 | trading-parallel-acceptance-20260921 | ONLY independent test_allocation_acceptance.py and notes |

Manifest: `/tmp/codex-opencode-parallel-20260921.tsv`.
Logs: `/tmp/codex-opencode-parallel-<role>-20260921.jsonl`.
Each checkout has **PARALLEL_TASK.md** and **PARALLEL_CONTRACT.md**. Source copies
are in external `E:/AgentWorkspace/entry-timing-pilot-20260920/parallel-*.md`.
Simulator session remains **ses_f3a31cf89ffeD66z4gDLxfOJ5l**; API session observed
**ses_f3a191207ffejDR5uyk9DffAX2**. Discover remaining session IDs from logs using
`/tmp/opencode/fv-venv/bin/python /tmp/codex-parallel-status.py`.
Expected results: DAILY_EXECUTION_HANDOFF.md for simulator, otherwise
PARALLEL_<ROLE>_HANDOFF.md (uppercase role). Do not resume previous workers.

**VERIFIED launch:** all six PIDs alive; read-only vLLM metrics reported6 running
requests and5 queued. This establishes concurrency, not sixfold speedup or
implementation acceptance. At initial check only simulator had completed a tool
call; full contract consumption and role outputs remain **UNVERIFIED**. Supervise
progress with compact logs. Preserve serving configuration and model services.

All new worktrees basea8674511 and contain seeded unaccepted draft dependencies
from the stopped simulator checkout (funded_execution.py, simulate.py, paper.py,
test_ledger_fix.py). **Integrate ONLY owned diffs, never wholesale seeded trees.**
Workers cannot commit/push/deploy/trade/train. Root owns review, cross-role fixes,
actual ledger tests, final real-data comparison and normal deployment acceptance.

Shared interfaces fix benchmark dates, stable unscaled stock composition,
fee-aware plan quantities, optional paper allocation_context, and snapshot
allocation_plan -> API portfolio_allocation -> existing single stock table.
Unadopted preview cannot replace incumbent actions. Missing capability/evidence
must remain explicit; no invented SWVXX fills or automatic policy promotion.
UI task includes actual browser fixtures against its own source checkout.

Evaluation inputs uploaded to `/tmp/codex-trading-evaluation-inputs-20260921`:
trusted corrected report pickle, benchmark prices, common-window references,
independent benchmark reference, scorecard and acceptance protocol. Pickle SHA256
matches local/remote **d6f8fe0cbf74e7318352b8e9c02910cae00164a2a4900be6a8e24a9960401c26**.
Evaluation worker builds runner and verifies controls now; final strategy scoring
waits for reviewed integrated execution. Fixed windows/costs/objective still apply.

Live remainsa89bba40, no new allocation source accepted/deployed. Earlier ledger
evidence and remaining integration risks below remain applicable. User's newest
request resolves optional coding preference: use parallel OpenCode, not blocked.
Starting local maine6248c16, pull up to date; unrelated untracked evaluation files
preserved. Diagram impact: NONE — coordination/dispatch evidence only.

## 2026-09-21 — Ledger repairs independently verified; daily execution next

**VERIFIED within isolated draft:** sale1 at100 with10bps/no recycling now
credits99.9 cash, and whole-share held0.6 submits no sell and reports blocked
residual. Root reran11 ledger tests and64 focused trading/parity/paper tests,
all passed. External **check-ledger-conservation.py** additionally passed100
deterministic mixed buy/sell baskets across0/5/10/20bps and both recycling modes:
ending cash+positions+fees equals starting value, no negative shares/cash,
non-recycling buys never spend sale proceeds. Worker reports110 broader tests;
root independently verified64, not110. Remaining full-draft Ruff C901 in
_continuous_orders and malformed economic test fixtures are deferred explicitly.
Full execution is not accepted, committed or deployed from this partial proof.

Ledger worker finished **LEDGER_FIX_HANDOFF.md** and PID3173728 exited.
CURRENT **NEW session ses_f3a31cf89ffeD66z4gDLxfOJ5l**, **PID3237467**, same
`trading-funded-allocation-20260921` checkout/basea8674511 with repaired draft.
Current log `/tmp/codex-opencode-daily-execution-20260921.jsonl`, contract
**CODEX_DAILY_EXECUTION_TASK.md**, result **DAILY_EXECUTION_HANDOFF.md**.
Scope NOW: scheduled stable stock composition/daily risk decisions, explicitly
dated causal SPY/QQQ context, complete truthful execution trace and focused
actual-simulator tests. Preserve ledger fixes/default behavior. Full paper.plan
pending/reservation/settlement, stock-entry/company-exit parity, real comparisons,
one-table UI and deployment remain NEXT. No concurrent worker or old-session
resume. Fresh task also requires fixing the lingering lint and unrealistic
1.4-weight/overvalued-holdings test fixtures without weakening their checks.

External post-ledger snapshots preserve reviewed boundary:
funded-simulate-ledger-fixed-snapshot.py and
funded-execution-ledger-fixed-snapshot.py. New contract/launch copies:
daily-execution-task.md and start-daily-execution.sh. Original full task and
review still govern later integration. Live remainsa89bba40.

Asked optional user preference whether to prioritize faster direct Codex coding
or conserve usage with OpenCode, given observed30-minute small fixes. No reply
yet; continue existing OpenCode preference, not blocked. Honor any later answer.
Starting main12741f63, pull up to date; no local production source imported,
unrelated untracked evaluations preserved. Diagram impact: NONE — review and
coordination evidence only.

## 2026-09-21 — Stalled execution review split into immediate ledger repair

At20:31, both independent account failures below still reproduced unchanged;
worker had read the review but produced no correction for22 minutes. Read-only
runtime metrics showed1 active request,0 waiting, not an infrastructure outage.
Stopped only PID3151214, confirmed exit. No model/service configuration changes.

CURRENT **fresh session ses_f3a53b602ffeeYnSiQe8WiZaXi**, **PID3173728**, SAME
`trading-funded-allocation-20260921` checkout, basea8674511 and existing draft.
Log `/tmp/codex-opencode-ledger-fix-20260921.jsonl`, contract
**CODEX_LEDGER_FIX_TASK.md**, expected **LEDGER_FIX_HANDOFF.md**.
Worker read contract. Scope NOW: only sale-proceeds conservation, bounded
whole-share sells/quantity validation and focused real-ledger tests. Exact
formulas and reproductions supplied. Do not start another writer or resume old
ses_f3a93c45affeaITi1eHsm9kTDO. Full shared paper/simulator integration remains
NEXT, not cancelled; retain original contracts and five-group review for it.
Do not call this narrow repair the finished allocation feature.

Existing draft includes9 lines in paper.py but no completed paper path/tests;
no new source accepted or deployed. External launch start-ledger-fix.sh and
funded-ledger-fix-task.md record dispatch. Live remainsa89bba40. Starting
mainb4d549c4, pull up to date, unrelated untracked evaluations preserved.
Diagram impact: NONE — coordination and reproduced failure evidence only.

## 2026-09-21 — Funded draft rejected on actual ledger failures

First execution draft now exists: new funded_execution.py and modified
simulate.py in worker checkout, not imported. **FAILED independent in-memory
account reproduction** (`reproduce-funded-draft.py` external, executed against
worker source): _Book sells1 share at100 with10bps and recycle_sells=False;
expected ending cash99.9, actual0, shares0. Draft excluded proceeds from buy
budget AND from ending cash. Whole-share plan for heldAAA0.6,price100,equity60,
cash0, all-cash target submitted sellqty1. No broker or production writes.

Source review also found daily stock reselection instead of stable scheduled
composition, whole-history benchmark availability checks/no date alignment,
full exits omitted from trace deltas, fee-free projected cash and missing-price
NAV omissions. Sent **CODEX_FUNDED_EXECUTION_REVIEW.md** with5 bounded correction
groups and required ledger tests, retaining original paper/simulator scope.

Stopped only PID3078917 and confirmed exit, resumed SAME session
**ses_f3a93c45affeaITi1eHsm9kTDO**, CURRENT **PID3151214**, same
`trading-funded-allocation-20260921` checkout/basea8674511. CURRENT log:
`/tmp/codex-opencode-funded-review-20260921.jsonl`.
Expected **FUNDED_ALLOCATION_HANDOFF.md**; original task + new review remain
the contract. Single writer; do not start a competing worker. Review actual
patch and independently replay failures before integration or comparisons.

External snapshots `funded-execution-first-snapshot.py` and
`funded-simulate-first-snapshot.py`, review `funded-execution-first-review.md`,
reproducer and resume script preserve evidence. No current candidate results;
do not score a simulator that destroys proceeds. Live remains a89bba40,
accepted pure modulea8674511 stays inactive. Latest main before handoff26ddf3bb,
tracked tree clean; existing untracked evaluations preserved. No deploy or fit.
Diagram impact: NONE — review evidence and worker coordination only.

## 2026-09-21 — Common-window comparison harness prepared during execution work

Funded worker remains **ses_f3a93c45affeaITi1eHsm9kTDO**, PID3078917,
same checkout/log/contracts below. At this check it completed relevant source
reads and baseline tests but has not yet written implementation files. Keep
single-writer isolation and allow current generation to finish; no restart or
service change this turn. Execution remains **UNVERIFIED**, no new deployment.

Root prepared external **allocation-scorecard.py**, exercised on immutable
common-window-reference.npz. **VERIFIED** exact reproduction of frozen incumbent
CAGR43.5673% and drawdown34.2315% (assertions1e-12); three independent metric
boundary checks pass, including first-return loss measured against initial NAV.
Output **allocation-scorecard-incumbent.json** includes each calendar year,
2023-through-end, separate benchmark upside/downside capture, and2441
overlapping252-return windows. Both return/drawdown objectives met in35.9689%
of windows; SPY alone37.2798%, QQQ48.1770%. These overlapping retrospective
windows are not independent evidence or a probability of future success.

When execution candidate artifacts exist, run
`allocation-scorecard.py vol=<npz> vol_trend=<npz>` with each NPZ containing
dates, returns and equity. Harness rejects different calendars, incorrect
initial NAV, missing evaluated returns or return/NAV mismatches. No strategy
fitting or threshold changes; fixed metrics/protocol remain in external
allocation-evaluation-acceptance.md. Only baseline scored so far; trace-derived
fill/turnover/recovery and exposure-matched accounts still require the worker.

Starting main0955d4e0, pulled up to date, tracked tree clean before handoff.
Unrelated untracked evaluations preserved. Diagram impact: NONE — standalone
evaluation harness and evidence only; no runtime component changes.

## 2026-09-21 — Funded allocation worker dispatched from reviewed module

Pure allocation checkpoint **a8674511** pushed:36 repository tests and14
independent checks passed; Ruff check/format clean. allocation.py SHA256
`1a35cc5a18b75b20f179fd795ab27e8e1f5cc7233e3d65f5796f0ac7c05fc616`.
Not deployed; no runtime caller selects it yet. No strategy performance claim.

CURRENT **NEW session ses_f3a93c45affeaITi1eHsm9kTDO**, PID3078917,
isolated `/home/animallya96/codex-worktrees/trading-funded-allocation-20260921`,
branch `codex/trading-funded-allocation-20260921`, base **a8674511**.
Contract **CODEX_FUNDED_ALLOCATION_TASK.md**, **CODEX_EXECUTION_NOTES.md**;
expected **FUNDED_ALLOCATION_HANDOFF.md**; current log
`/tmp/codex-opencode-funded-allocation-20260921.jsonl`.
Previous pure-math worker completed; do not resume it. Single writer.
New task integrates optional shared daily allocation/quantity planning in actual
paper.plan and simulate.run using _Book, stable composition, separate QQQ data,
current-cash/fee funding, pending/conflicts, priority cuts and daily recovery.
Simulation starts NAV1 with continuous shares; do not floor its orders to zero.
Whole-share paper adapter must preserve cash/name bounds after rounding.
An unavailable diagnostic can still contain an executable known-risk cut;
missing held valuation must not silently shrink NAV and resize other assets.

External full contract `funded-allocation-task.md`, launch
`start-funded-allocation.sh`. Compact progress tool on Spark:
`python3 /tmp/codex-compact-opencode-status.py <current-log>` avoids replaying
large source outputs. Review actual diffs and ledger tests before adoption.
External **allocation-evaluation-acceptance.md** now fixes metrics/episode
definitions and common window before candidate outcomes. Use existing cached
report, controls and aligned benchmark prices; no model rerun. Compare BOTH
SPY/QQQ, downside participation, false exits, recovery, turnover/concentration
and exposure-matched diagnostics. Binding one-table UI and normal deployment
follow acceptance; not complete at another module/unit-pass checkpoint.

Live remains a89bba40 with previously verified fixes. No orders, training,
production writes or new deployment this turn. Tracked local tree clean after
a8674511 before this handoff update; unrelated untracked evaluations preserved.

## 2026-09-21 — Pure allocation accepted; funded execution is next

Worker ses_f3ab2cd27ffebDtYOXhZIrQYhB finished and PID3043917 exited.
Reviewed actual allocation.py and8 worker tests, independently reran14 external
arithmetic/boundary checks: **14 passed**, including both missing-data defects.
Imported only allocation.py, test_portfolio_allocation.py and protocol. Root
added missing function comments, explicit complexity annotations (worker's two
lint failures were not an acceptable clean result), corrected availability and
empty-candidate documentation. **36 local tests**, **14 independent checks**,
Ruff check/format and diff check pass on final local source. No orders, training
or production writes. Pure arithmetic is verified; execution/performance and
deployment remain **UNVERIFIED**. No live policy change yet.

NEXT: fresh isolated OpenCode execution task based on this accepted module,
following external allocation-execution-review-notes.md and full allocation
contract. Must actually integrate shared funded paper/simulator orders, stable
composition, separate QQQ history, pending/fills, priority cuts and re-entry;
then root evaluates fixed candidates/common window and binds the one-table UI.
Do not resume previous worker sessions. Check latest entry for execution worker
identity before starting any writer. Existing live remains a89bba40.

User challenged the inference that ML is unhelpful. Clarified that narrow
timing/context experiments do not reject ML generally. ML remains in scope
for distinct stock-relative-return, risk and execution hypotheses with adequate
point-in-time data and independent evidence; no retuning reused holdout or new
fit before the funded evaluation path is correct. Several-days/weeks objective
and both SPY/QQQ benchmarks unchanged.

Starting main ee6588e6, pulled up to date; only these task files staged.
Diagram impact: NONE — pure module within existing desk; no new component flow.

## 2026-09-21 — Second independent math check; fresh bounded worker

First review corrections now pass **12 of14 independent checks** in external
`test_allocation_independent.py`, against `allocation-corrected-snapshot.py`.
Price-level trend, joint covariance calculation, absolute caps, unknown-stock
event cuts, invalid price rejection, index eligibility and causality passed.
**FAILED**: empty candidate still retains stock if benchmark history is missing;
vol_trend permits risk increases with missing200-price trend history. These
are concrete input-policy defects, not evidence about strategy profitability.
Sent exact failures in **CODEX_ALLOCATION_SECOND_REVIEW.md**.

Previous session had grown to173k context and spent another12 minutes without
writing tests. Stopped PID2993948 and confirmed exit. **CURRENT fresh session
ses_f3ab2cd27ffebDtYOXhZIrQYhB**, PID3043917, same isolated
`trading-allocation-path-20260921` checkout. CURRENT log
`/tmp/codex-opencode-allocation-finish-20260921.jsonl`.
It has read the second-review contract and existing module with21k context.
Task: two fixes, compact focused tests, Ruff, **ALLOCATION_DECISION_HANDOFF.md**,
then stop for review. No concurrent writer, integration or deployment yet.
DO NOT resume old ses_f3b027cf5ffeGAwFUe1w4JTDkC while this worker is active.

Additional **VERIFIED** data boundary: trusted cached stock panel2945x95 has
SPY but NO QQQ. Root created external **allocation-benchmark-prices.npz/.json**
using `prepare-allocation-benchmarks.py`:2945 finite positive adjusted prices
for EACH benchmark from immutable Sep18 snapshot; SPY exactly equals original
panel. Pass these separately to optional execution context; do not append QQQ
to frozen report matrices and misalign its scores/grades/ledger. No model rerun.
Updated external `allocation-execution-review-notes.md` with this requirement.
Common-window controls and all live acceptance remain as recorded below.

Local start HEAD917c2cc3, main pulled up to date, existing untracked evaluations
preserved. Handoff-only change; allocation remains **UNVERIFIED / not shipped**.
Diagram impact: NONE — review evidence and task coordination only.

## 2026-09-21 — Independent allocation review rejected first draft

Objective remains shared stock/index/cash allocation, funded daily execution,
both benchmark comparisons and one-table UI acceptance. **FAILED first pure
allocation draft**: independent external `reproduce-allocation-review.py` loaded
an exact snapshot of worker allocation.py and showed a rising price series
above its 200-price SMA produced trend ceiling0 instead of1 (returns were
passed to the price trend function). Explicit empty equity target with index
ineligible retained15% AAA and reported unavailable. Zero/negative adjusted
prices were also accepted as return evidence. No draft code was integrated.

Stopped only worker PID2968035, confirmed exit, resumed SAME session
**ses_f3b027cf5ffeGAwFUe1w4JTDkC** in the same allocation-path checkout.
CURRENT **PID2993948**, log
`/tmp/codex-opencode-allocation-math-review-20260921.jsonl`.
Worker **read CODEX_ALLOCATION_MATH_REVIEW.md**, covering the above defects,
stock-only desired symbols, explicit index eligibility, missing input handling
and truthful binding reasons. Expected **ALLOCATION_DECISION_HANDOFF.md**.
No concurrent writer. Module and protocol exist, tests/corrections remain
**UNVERIFIED**. Review actual arithmetic before importing anything.

External artifacts in `E:/AgentWorkspace/entry-timing-pilot-20260920/`:
`allocation-review-snapshot.py`, `reproduce-allocation-review.py`,
`allocation-math-review.md`; `allocation-execution-review-notes.md` records
source-reviewed next milestone hazards. In particular, simulate._targets
already applies regime.exposure, so it is not an unscaled composition;
paper.bound_orders applies company cap to every symbol and excludes fees;
_Book.equity omits unpriced holdings; SimTrade does not trace partial cuts.
The optional execution path needs explicit treatment without changing defaults.
These notes are not another worker task yet; first finish current math review.

**VERIFIED live remains a89bba40**, benchmark/fundamental/account-label fixes
and browser acceptance documented below. No new deployment, model fit, broker
order or production record write. Heartbeat updated to current worker/review.
Starting repository HEAD3be84cac on main, pull up to date; only existing
untracked evaluation files were present. This checkpoint changes handoff only.
Diagram impact: NONE — review evidence and task coordination only.

## 2026-09-21 — Allocation worker narrowed to first concrete implementation

At 18:01 UTC, worker had spent 39 minutes reading and produced no code.
Stopped only PID2894536 and confirmed exit; resumed SAME session
**ses_f3b027cf5ffeGAwFUe1w4JTDkC**, same allocation-path checkout, with a
bounded pure-decision milestone. CURRENT log:
`/tmp/codex-opencode-allocation-decision-20260921.jsonl`, PID2968035.
Contract **CODEX_ALLOCATION_FIRST.md**, result **ALLOCATION_DECISION_HANDOFF.md**.
Implement only allocation.py, focused tests and short formula protocol now;
paper/simulator integration remains the NEXT milestone, not cancelled. Do not
start another writer. Worker has consumed this exact contract. Runtime metrics
confirm active generation and no queued model requests; do not change services.
External contract copy `allocation-first-milestone.md` in acceptance folder.

Prepared common-window controls using the cached report, no model recomputation:
external **common-window-reference.npz/.json**, generated by
`prepare-common-window.py`. All accounts start at NAV1 on **2016-01-04**, first
next-open entry, through 2026-09-18; identical252-session warmup and10bps cost.
Initial harness accidentally sliced simulator output twice (it already applies
since); the alignment assertion caught this before any artifact was written.
Corrected harness asserts exact dates and complete evaluated returns.
Incumbent CAGR43.57%, drawdown34.23%; SPY15.07%/33.72%; QQQ20.07%/35.12%.
Thus incumbent fails SPY's drawdown objective on this frozen common window.
Metrics also include worst day/week, longest underwater interval and separate
up/down capture versus both. These remain retrospective survivor-biased results.
Use these fixed references for upcoming candidates, without changing the window
or thresholds after results. No allocation change is accepted or deployed yet.

## 2026-09-21 — Benchmark deployed and accepted; allocation worker still active

**VERIFIED deployed a89bba40**, containing benchmark backend 703e3ac3.
Normal backend deploy: **3843 unit tests, 30 skips; 100 real-model routing
tests** passed. Backend and subsequent frontend-only deploy cheap checks passed;
latest verdict `2026-09-21T17:37:32Z a89bba40 ok (cheap)`.
Logs `/tmp/codex-trading-benchmark-deploy-20260921.log` and
`/tmp/codex-trading-benchmark-ui-deploy-20260921.log`.
Read-only deployed runtime check (`check-benchmark-runtime.py`, external folder)
loaded both controls over 2945 sessions through Sep18; exact match to independent
desktop accounting. benchmarks.py SHA256
a990da09ebd162e77252907c3faf19e7d2e9e38cbc568e28f744eaed70acb1c2 matches source.
No comparison records or trades written.

Actual deployed browser passed: 93 real stock rows, each action equals API,
one table, desktop/mobile and no blocking errors. Additional missing-QQQ and
legacy-accounting cases used response fixtures in that same headless browser
against deployed assets; no production data changed. Both labels rendered as
expected. `run-live-desk-check.py` now includes these separate fixture checks.

Important diagnostic: incumbent's since-2023 drawdown is 32.01%, versus SPY
18.76% and QQQ22.77%, despite better full-period historical returns. These
fixed regime comparisons motivate the allocation work; they are not new
holdout evidence or parameters to tune against.

NEW worker remains active as recorded below (PID2894536). As of this check it
has read relevant code but has not written implementation files. Leave single
writer isolation; check bounded progress rather than mistaking a process for
completion. Additional **CODEX_ALLOCATION_REVIEW.md** supplied: missing stock
volatility cannot disable an independently known regime/FOMC/trend ceiling;
withhold risk increases but execute established risk cuts on priced holdings.
It also freezes the common evaluation start at panel.dates[252] after common
warmup, before any candidate results, with every strategy/index account using
that initial NAV and next-open execution. No per-candidate start selection.
External contract copy `allocation-acceptance-clarification.md`.
Review must confirm worker has consumed this clarification. No allocation
policy is implemented, accepted or promoted yet. Continue this original task.

## 2026-09-21 17:27 UTC — NEW allocation worker active; benchmark deploy running

CURRENT worker is **ses_f3b027cf5ffeGAwFUe1w4JTDkC**, isolated checkout
`/home/animallya96/codex-worktrees/trading-allocation-path-20260921`, base
**703e3ac3**, contract CODEX_ALLOCATION_TASK.md, result ALLOCATION_HANDOFF.md,
log `/tmp/codex-opencode-allocation-path-20260921.jsonl`. Single writer.
Old benchmark session is STOPPED. Fresh worker has read relevant implementation
and tests; it must implement optional shared daily allocation/priority execution
in paper and simulator, preserve defaults, and stop for review. Contract copy:
external `opencode-allocation-path-task.md`. Fixed volatility/residual-SPY and
trend candidates, coordinated regime/FOMC absolute caps, explicit instrument
capabilities, no invented SWVXX fills. Root supplies review and cached real-data
evaluation before adoption; no fitting or broker calls authorized in worker.

Benchmark source **703e3ac3** pushed, normal deployment underway in
`/tmp/codex-trading-benchmark-deploy-20260921.log`. Finish gates and exact-source
read-only runtime benchmark acceptance. Do not overwrite old comparison files.
UI companion now explains unavailable benchmark rows and identifies older
accounting. Two local browser journeys and TypeScript/Vite build passed;
frontend-only deploy must follow the current backend deploy, then actual browser
acceptance. Primary stock table remains unchanged. Do not run concurrent deploys.

## 2026-09-21 17:23 UTC — Benchmark source accepted; allocation implementation next

Stopped only OpenCode PID2785653 after its corrected patch passed 56 tests but
the 230k-token session stalled while preparing handoff. Confirmed process exit.
Session ses_f3b57ff60ffeZdI3U3ov3bGq40 is finished; DO NOT resume it. Reviewed and
imported exactly four benchmark files. Root closed remaining validation gaps,
fixed the dividend test to model an actual ex-dividend price drop, added legacy
roundtrip coverage and missing helper comments. **61 tests and Ruff passed.**

Independently exercised actual market_strategy_bench.main with the trusted
cached desk report and real stored bars, redirecting ONLY its output writer
to external memory/file. `verify-benchmark-integration.py` confirms SPY/QQQ
returns, drawdowns and terminal NAV match independently hand-accounted values
to rtol 1e-12 over 2945 sessions; incumbent values unchanged. Output is external
`reviewed-strategy-bench-v2.json`. CLI's printed default write path is misleading
in this harness because save was intercepted: NO production or frozen store
records were written. No strategy promotion. Source acceptance is complete;
normal deployment/runtime confirmation remains separately recorded below.

Next: fresh compact OpenCode session for optional shared allocation and execution
path. Use the existing CODEX_EXPOSURE_TASK.md protocol plus explicit existing
regime-cap coordination; do not let residual index allocation refill a broad
equity risk cap, or multiply absolute exposure caps twice. Preserve incumbent
default and risk services; evaluate only the fixed predeclared alternatives.

## 2026-09-21 16:52 UTC — Funded live desk fixed and verified; benchmark review active

**VERIFIED deployed 07f59af6**, exact running decision_view SHA256
23333a5341df63b5b351f3ea2183d0acbb597ac513cf27da9941437af08b7517 matches source.
Normal deploy: 3816 unit tests (30 skips), 100 real-model routing tests,
cheap post checks passed at 16:49 UTC. Local targeted tests: 111 passed.
Live authenticated browser: `/desk/mine` 200, 93 stock rows, one table,
BUY/HOLD/SELL only, every rendered action equals its actual API decision,
desktop/mobile layout and no blocking errors/failed market requests.
Screenshots and `run-live-desk-check.py` live in external acceptance folder
`E:/AgentWorkspace/entry-timing-pilot-20260920/`.
The historical Sep18 record is still honestly labelled untagged; do not
overwrite it or claim that stored decision has corrected inputs.

Visual inspection found misleading empty-account notices while displaying
the recorded funded desk plan. **VERIFIED deployed 7d510d20** corrects these
notices to distinguish missing personal positions from the desk account.
TypeScript/Vite build and single-table fixture journey passed. Normal script
used its frontend-only path; cheap post checks passed at 16:54:34 UTC.
Live browser rechecked all 93 enum actions against their API rows, one table,
desktop/mobile, absence of the misleading wording and presence of corrected
wording; no page errors or failed market requests. Thus 7d510d20 is the
verified deployed checkpoint, including backend fix 07f59af6.

OpenCode SAME session/checkout/log as below, still active. It found and READ
**CODEX_BENCHMARK_REVIEW.md** at 16:48 UTC, so no second writer or resume is
needed. Review requests: exact funded cost convention capital/(1+cost), reject
missing early/regime returns rather than shortening periods, calendar and
capital validation, and unavailable metadata even for short samples. Await
BENCHMARK_HANDOFF.md, inspect actual patch, run tests independently and compare
real-data output to the independent reference. Then proceed to exposure
milestone from CODEX_EXPOSURE_TASK.md, followed by one-table UI integration.
No draft benchmark or exposure changes have been imported or promoted.
16:55 UTC: worker process still alive, last log event is reading the review
followed by step_start at 16:48. No correction edits or final handoff yet;
do not mistake a live process for successful review completion. Check bounded
progress next; if it stays stalled, stop only this worker before resuming with
a compact correction task. Heartbeat updated with current logs and acceptance.

Root computed and saved the corrected incumbent once on immutable Sep18 data:
`corrected-exposure-report.pickle` (trusted local cache, do not load arbitrary
pickles), `corrected-exposure-baseline.npz/.json`, and independent SPY/QQQ
accounting `independent-benchmark-reference.json`. Avoid repeating desk.run;
use cached report for fixed, predeclared exposure candidates. Exact calendar:
2015-01-02 initial NAV, first fill Jan5, through 2026-09-18, 2944 return sessions.
Ten-basis-point one-way cost, no terminal liquidation, zero cash interest.
Incumbent retrospective CAGR 44.56%, max drawdown 32.01%; SPY 13.77%/33.72%,
QQQ 19.03%/35.12%. **These survivor-biased, reused historical results do not
prove the objective achieved or future outperformance.** Incumbent maximum
single-name holding drift reached 31.74%; target caps do not imply a held-weight
cap. Full paths are saved for downside participation, re-entry and regime
comparisons. No new model fitting experiment or production records written.

## 2026-09-21 — Live acceptance found funded-preview failure; correction pending deploy

The fundamental correction deployed as **c36f4a4b** at 16:03 UTC through
scripts/deploy.sh: 3815 unit tests passed (30 skips), 100 real-model routing
tests passed, cheap post-deploy smoke passed. Main afac6045 differs only in
test formatting. Read-only deployed runtime check confirmed the corrected
fundamental source, September 18 input session, 94 stock columns and 88 scored
names; module hash matches the independently compared source. No records written.
The frozen September 18 record remains legacy/untagged until the next nightly.

Actual browser acceptance FAILED: funded `/desk/mine` returns HTTP 500 when
fresh live grades exist. `apply_account_plan` reads `grade`, but
`holdings.live_grades` returns `grade_live`. Reproduced in the funded HTTP
regression before changing production code. Fix the consumer, keep the public
live-grade contract; test both funded and unfunded accounts with a consistent
clock. Re-run normal deploy and external `run-live-desk-check.py`; the prior
unit pass and healthy endpoints do not establish a working dashboard.

OpenCode exposure worker was interrupted after excessive reading and resumed
in the SAME session **ses_f3b57ff60ffeZdI3U3ov3bGq40**, same isolated checkout.
CURRENT log `/tmp/codex-opencode-portfolio-benchmarks-20260921.jsonl`.
First bounded milestone: strict SPY+QQQ benchmark loader, strategy-bench
integration and tests; write **BENCHMARK_HANDOFF.md** and stop for review.
Code edits now observed. No allocation promotion or training. The broader
exposure contract remains the next milestone after benchmark review.

## 2026-09-21 — User clarified the actual allocation objective

Additional user requirement: defensive allocation during bear markets or
unusual shocks (COVID example), including bonds or SWVXX. SWVXX verified as
a money-market mutual fund, so treat it separately from duration-bearing
bonds. Expand the allocation contract to cash/money-market/bonds, respecting
broker eligibility, settlement, income and credit/duration risks. No
hindsight crash-date triggers or promise to avoid every gap. See the updated
portfolio objective for stress scenarios and re-entry acceptance.

Latest user constraint: **SPY and QQQ are the benchmarks for gains and
drawdown limits**. Objective: higher net compounded returns with no larger
drawdowns than each benchmark separately over identical periods. This replaces
the request for an arbitrary 10/15/20% absolute drawdown preference. Do not
pick the easier benchmark or a hindsight blend, and never use future benchmark
drawdown as a decision input. Details in the objective document below.

Read `docs/research/portfolio-exposure-objective-2026-09-21.md`. User wants
stocks at attractive prices, cash/indexes ahead of deteriorating conditions,
and prompt participation in recoveries; volatile-stock red days are the key
problem. They answered "I'm not sure" about drawdown tolerance. Do not invent
a personal risk limit; compare return/downside trade-offs. After current live
fundamental correction, prioritize a shared stock/index/cash exposure layer,
including re-entry and execution priority, rather than another small entry-
timing model. No claim of perfect downturn foresight or zero lag. Continue
supervision beyond the input fix; that alone is not this clarified objective.

## 2026-09-21 — User rejected stopping; live correctness migration active

15:58 UTC: retry deployment has passed **3815 unit tests, 30 skips**; the
100-case real-model routing gate is still running. No gate bypass. Retry log
`/tmp/codex-trading-fundamentals-deploy-retry-20260921.log`; checkout used
c36f4a4b. Main afac6045 only wraps one long test line; Ruff passes there.
Do not mutate deploy checkout while its gate runs. After cutover verify the
actual container hashes and source/date output using external read-only
`E:/AgentWorkspace/entry-timing-pilot-20260920/check-fundamental-runtime.py`
(pipe to deployed backend python), and run `run-live-desk-check.py` through
existing SSH tunnel localhost:18080. The latter now verifies the actual
fundamental source label, one table, enum cells and desktop/mobile behavior.
New screenshots use `live-fundamentals-desktop/mobile.png` names.
Nightly is `/home/animallya96/desk_daily.sh`; it pulls main into ~/anios when
the nightly lock is free and runs ~/research-venv/bin/python market_daily.
Do NOT run this script manually: it includes paper-trade. The already stored
September 18 record remains immutable; current displayed input source can
remain unrecorded until the next nightly, honestly labelled by the new UI.

NEXT WORKER ACTIVE (old fundamental session finished): fresh OpenCode session
`ses_f3b57ff60ffeZdI3U3ov3bGq40`, base afac6045, isolated checkout
`/home/animallya96/codex-worktrees/trading-portfolio-exposure-20260921`.
Contract CODEX_EXPOSURE_TASK.md, result EXPOSURE_HANDOFF.md, log
`/tmp/codex-opencode-portfolio-exposure-20260921.jsonl`.
Contract copy is external `opencode-portfolio-exposure-task.md` in the same
desktop acceptance folder. Scope: strict mandatory SPY+QQQ benchmarks and
optional shared stock/index/cash allocation plus priority execution in paper
preview and simulator. Fixed transparent volatility/trend diagnostics, no
tuning/training/automatic promotion. Instrument eligibility must distinguish
cash, mutual funds and duration; no fabricated SWVXX fills. Full causal/funding
parity tests and actual portfolio evaluation required before adoption, then
bind accepted exposure payload to existing one-table UI. Worker cannot deploy
or submit orders. Heartbeat prompt updated with this new worker and acceptance
state; do not continue the older research or fundamental sessions by mistake.

15:47 UTC: correction checkpoint 1c28ce80 pushed; local 102 tests, two actual
browser journeys, production build, Ruff and all 32 diagram checks passed.
First normal deploy FAILED at collection of earlier research test_entry_context
(missing optional joblib in gate image); deployed marker remains 8c17e72a.
No service cutover occurred. Targeted test-fixture fix loads optional research
CLI dependencies only for its six CLI tests, retaining seven pure context
tests in the ordinary gate. All 13 pass on desktop research environment.
Rerun normal deploy after committing this isolated gate fix; never skip gate.
Deployment log: `/tmp/codex-trading-fundamentals-deploy-20260921.log`.

15:44 UTC: independent current-data comparison COMPLETED successfully:
exact legacy grades/scores/targets replay; valuation scores unchanged;
8 grade changes, 7 target changes, 2.84556% one-way target turnover; scored
names 90 -> 88 among 94 non-SPY columns on September 18. Two hypothetical
funded account previews pass cash bounds; no broker calls. Full artifact:
`E:/AgentWorkspace/entry-timing-pilot-20260920/live-migration-comparison.json`.
OpenCode UI correction finished; independently reviewed/imported ONLY its
three frontend files. Root reran both named Playwright journeys: 2 passed;
production TypeScript/Vite build passed (existing CSS/chunk warnings).
Original worker no longer active. Patch is ready for normal deploy gate after
diagram synchronization check. Preserve local backend cleanup when creating
the checkpoint. Do not rewrite old live records or claim current served
grades use corrected inputs until a new nightly record is actually produced.

15:08 UTC: original worker finished; LIVE_HANDOFF reports 221 tests passed,
but no frontend build/browser run. Independently reviewed and imported ONLY
the nine changed backend files into desktop main (now 95e55e4a, documentation
checkpoint pushed). Production patch remains uncommitted and undeployed.
Root ran 102 focused tests (desk/daily/features/asof/shadow/paper/funding),
all passed, no skips; Ruff clean. Fixed misleading comments about inputs vs
execution policy, comments above new test helpers, and one test filing dated
before its quarter end. The 19 feature tests pass after that fixture fix.

Current-data comparison is RUNNING as desktop exec session 83773, process
started 15:04:30 UTC, external `compare-live-fundamentals.py`; log
`live-migration-comparison.log`, final `live-migration-comparison.json`.
Do not rerun while active. It evaluates the full incumbent expectation-gap
path twice, hence takes minutes. No live writes or broker calls.

Sent bounded FRONTEND-ONLY correction to SAME OpenCode session
`ses_f3c0be438ffePE3J3uOAcb1tVZ`; current log now
`/tmp/codex-opencode-live-fundamentals-ui-20260921.jsonl`.
Worker must remove notice from unused EveryGrade, render concise source on
actual StockBoard area, fix test selector, and run browser/build against its
own served tree (shared node_modules exists at ~/anios/frontend/node_modules).
No backend edits by worker: root comment/fixture cleanup is now local and
must not be overwritten by copying remote backend again. Import/review only
frontend files after worker finishes; old LIVE_HANDOFF exists, so check log
completion rather than treating its existence as proof the new pass ended.

14:33 UTC: worker PID 2523627 still running, now wrote analyst/run-mode/source
guard/metadata tests in test_fundamental_features, test_trading_desk and
test_market_daily. Worker reports a separate 76-test execution regression run
passed; root has NOT independently run the patch. No LIVE_HANDOFF yet. Root
review found its new browser test still looks for `Stock rankings` in unused
EveryGrade before checking SummaryStrip, so that test must exercise the
actual `Ranked stocks and cash` table and rendered summary. Verify or correct
before acceptance; do not accept a browser test merely because it exists.
Worker is inspecting final diffs/imports, so allow this active pass to finish.
QQQ omission confirmed on captured real inputs: QQQ absent from the stock
panel, so current `_index_series` cannot emit that required comparison.

14:08 UTC supervision: review worker PID 2523627 remains active in the same
session, about 33 minutes into the correction. Source now rejects unknown run
modes, checks actual feature availability at the decision session, removes
the nightly legacy option, and renders source identity in SummaryStrip.
Tests/handoff are not complete; no import or deployment yet. The redundant
notice in unused EveryGrade remains and source/policy comments conflate
`inputs` with execution policy; review cleanup with final patch.

Incumbent capture FINISHED on copied current inputs: `live-baseline.log`
and `live-migration-baseline.json/.npz`, session 2026-09-18, 94 non-SPY
columns, expectations-gap active. This differs from the previously served
93-row report; do not assume identical universe without comparing names.
Prepared independent acceptance runner (NOT run until reviewed source is
imported): `E:/AgentWorkspace/entry-timing-pilot-20260920/compare-live-fundamentals.py`.
It checks exact legacy grades/scores/targets against the incumbent capture,
unchanged valuation scores, corrected changes, and identical hypothetical
100k funded account order previews. The accounts are synthetic, not the
user's actual positions. Writes only external comparison JSON, no broker.

Allocation-path inspection for NEXT atomic task: `risk.desk_targets` sizes
stocks; `simulate._targets` explicitly zeroes SPY. Its allocator hook runs
only on scheduled rebalance days. Broad risk reductions therefore require
a shared priority path for held exposure, including recovery and actual-fill
state, not only another sizing multiplier. Existing event lifecycle is FOMC-
specific and must not conflict or repeatedly compound cuts. Also inspect
`market_strategy_bench._index_series`: it skips indexes absent from the stock
panel, while `book_panel` requests book names plus SPY only. This can omit QQQ
silently and does not satisfy the user's two-benchmark requirement. Load both
controls independently, align and fail explicitly on missing coverage. Read
the objective document before specifying the next OpenCode task.
`strategy_bench.stats` additionally turns every nonfinite daily return into
zero: required benchmark gaps must fail coverage before reaching this
function, rather than becoming apparent cash performance. Distinguish the
deliberately initial zero-return NAV point from a missing market session.
14:09 UTC: worker has begun analyst-level tests in
`backend/tests/test_fundamental_features.py`; it is progressing, do not start
another writer. Independent comparison runner compiles successfully.

13:14 UTC in-progress review: worker active, 8 tracked files edited, still
building tests. Do not import/deploy yet. Recheck these concrete findings in
the final patch before acceptance: `_fundamental_opinion` treats any mode
except "legacy" as corrected while `_fundamental_source_id` labels an unknown
mode legacy; reject unsupported modes. Source coverage currently counts keys
even for empty/no-available versions; test actual absence at the last session.
The added UI source notice is inside `EveryGrade`, a component no longer
rendered on the one-table page, while SummaryStrip still identifies a curve
only by execution policy. Test the actual rendered source/older-curve label.
`market_daily --fundamentals legacy` claims read-only but `_run` can still
write records or paper-trade; constrain that option to the read-only CLI or
enforce its no-write/no-trade contract structurally. Metadata on assembled
value shadow reports must preserve the fundamental-source identity too.

13:35 UTC: after 20 minutes with the same patch and repeated fixture reading,
interrupted own worker PID 2434809 cleanly and resumed SAME session with the
five specific review corrections above plus a request to write/run tests now.
Current log is `/tmp/codex-opencode-live-fundamentals-review-20260921.jsonl`.
No concurrent writer. Original log remains available. Follow the new log and
LIVE_HANDOFF.md; do not mistake the existing unfinished patch for acceptance.
Root started read-only incumbent capture on copied current inputs via
`E:/AgentWorkspace/entry-timing-pilot-20260920/capture-live-baseline.py`, output
`live-baseline.log`, then `live-migration-baseline.json/.npz` in that folder.
It runs the full existing expectations-gap desk with four CPU threads; no
broker calls/writes. Check completion before any production-source import;
the incumbent snapshot is the comparator for corrected grades and targets.

User: "ugh so are we leaving it like this or are we going to make it better?"
Codex acknowledged stopping prematurely. Continue actual product work, not
another research-only conclusion. Fresh OpenCode worker implements the live
fundamental analyst input correction, starting main 83ae9753 in isolated
`/home/animallya96/codex-worktrees/trading-live-fundamentals-20260921`.
Contract `CODEX_LIVE_TASK.md`, result `LIVE_HANDOFF.md`, current log
`/tmp/codex-opencode-live-fundamentals-20260921.jsonl`. Read log/session ID
before sending follow-ups; this is a NEW session, not the earlier worker.
New session ID: `ses_f3c0be438ffePE3J3uOAcb1tVZ`; worker PID 2434809.
Read-only input snapshot exported for local actual-data comparison to
`E:/AgentWorkspace/entry-timing-pilot-20260920/live-inputs-20260921/`:
550 bar histories and actions, 531 event/fact histories, 93 versioned
fundamentals, 266 tone histories, latest partition per ticker through Sep21.
Archive sibling `live-inputs-20260921.tar.gz`. Public market inputs only;
no paper accounts, credentials or live desk records copied. Keep this separate
from local Sep4 research data and never write its outputs back to production.

Scope: scored fundamental legs use the reviewed versioned adapter by default,
NaN stays unavailable, minimum two actual inputs; explicit legacy comparison;
total source failure stops assembly rather than manufacturing a report;
data-source identity in report/record/curve. Value analyst and its existing
shadow stay unchanged in this atomic correction. Preserve frozen opportunity
fingerprints and all prior records. No order submission by worker. Codex must
inspect and run actual corrected-vs-legacy grades/weights/order preview on
stored data, focused tests, required deploy gate and live acceptance. Do not
stop merely because worker wrote a patch or tests passed.

Runtime read-only audit: live Sept 15–18 value-shadow blocks all cover 93/93
names; 4,5,5,6 grades differ, hypothetical turnover about 2.98%,5.38%,2.99%,
5.53%. These are VALUE-shadow comparisons, not proof of new fundamental-leg
behavior. Version partitions exist each of those nights. Local price history
ends Sep 4, so obtain the current read-only data for live-cutover comparisons
instead of overwriting any live record from stale local inputs.

## 2026-09-21 07:25 UTC — Supervised experiment completed; no promotion

Read `docs/research/entry-context-results-2026-09-21.md` for the morning
handoff, actual results and remaining production limitations. Fixed context
run at 48853b6e finished in 98 seconds, return code 0, all 54 account paths
replayed with artifact hashes, predictions, exact decisions and NAV 1e-10.
At 10 bps/side, pooled context-minus-price timing difference +0.072 bp/day,
95% interval [-0.130,+0.269]; later-window skip versus always-enter was
-22.803 [-40.577,-6.785]. No reliable incremental edge. No retuning, GPU
escalation or live promotion justified. Prior RTX5080 pilot is already done.
Results at `E:/AgentWorkspace/entry-timing-pilot-20260920/context-run-01/`.
OpenCode work is complete and no worker remains active. Disable the overnight
heartbeat after saving this handoff; the bounded supervised phase is done.
Do not claim the broad "best desk" objective is achieved: the live legacy
fundamental path and survivor bias remain unresolved, and fresh forward
evidence needs future observations. Production remains gateway 8c17e72a;
research additions are committed separately and have no deployment path.

## 2026-09-21 07:02 UTC — Context experiment accepted for one bounded run

OpenCode review corrections independently checked and imported: entry_context
helper, market_entry_context CLI, test_entry_context and protocol. Desktop
29 context/pilot tests pass with no skips; Ruff clean. No active OpenCode
writer remains. CLI now uses the actual intraday partition, verifies input
and model hashes before loading models, compares both controls and price-only,
and automatically checks exact decisions/NAV after fitting. Research only.

Next action: run external `run-context-bounded.py` with desktop venv. It writes
`context-run-status.json` and `context-run.log` under
`E:/AgentWorkspace/entry-timing-pilot-20260920/`; output `context-run-01`.
It enforces a two-hour process deadline and the CLI caps threads at four.
If status has started but no finished, inspect the existing process; never
launch a duplicate. On completion inspect results/summary, manifest and actual
return code; report negative findings as negative and do not tune. The fixed
ten-session study is retrospective; it cannot authorize live promotion.

## 2026-09-21 — Reviewed fundamental adapter accepted for research

Checkpoint `0a796a0c` pushed after the independent acceptance run. Next bounded
OpenCode task dispatched in the SAME isolated checkout/session, contract
`CODEX_CONTEXT_TASK.md`, log `/tmp/codex-opencode-entry-context-20260921.jsonl`,
result `HANDOFF_CONTEXT.md`. This is a pre-specified 10-session paired tree
ablation: 28 price features versus those plus 7 quarterly features, missingness
and fiscal ages, all fundamentals lagged to the previous session. No tuning,
no production promotion, no training on Spark. Review three new code/test
files plus its protocol; then run once on desktop with four CPU threads and
a two-hour runtime ceiling. Do not launch another writer until this one ends.
A GPU run is optional and must be justified by new information; the point is
to test the feature hypothesis cheaply before adding model complexity. All
2024–2026 measurements remain retrospective/reused, never a fresh holdout.
Full task copy: `E:/AgentWorkspace/entry-timing-pilot-20260920/opencode-ablation-task.md`.

05:08 UTC supervision: worker still active (PID 1806650), no context-code
files yet; it wrote the frozen protocol before fitting as requested. Last
tool activity was recent, so do not interrupt or start a second writer.
Review note for its eventual patch: protocol currently mentions only paired
comparisons versus always-enter. The task requires context versus price-only
and versus both baselines; verify the implementation includes these paired
comparisons before running. The resumed session has grown to roughly 230k
input tokens; for any later independent task use a fresh OpenCode session
with a compact handoff rather than continuing to accumulate this context.

05:29 UTC review of in-progress files: worker has written the CLI and helper,
is still active and writing tests; do not import unfinished code. Context was
compacted to ~73k so progress is moving. Concrete acceptance blockers in the
current draft (recheck final files before requesting corrections):
1. CLI main passes `store.root` into ep.build, but ep.build requires the
   selected intraday partition (see intraday.partition(root / "bars_15m"));
   this otherwise produces an empty dataset on the real store.
2. verify never checks its recorded dataset_sha256; context arrays and
   preprocessing need fingerprints too. A changed feature input must fail
   replay even when it does not cross a tree split. Include a tampering test.
3. evaluate_all has only paired_vs_enter; needs context versus same-mode
   price-only and versus always-wait, preserved in summaries.
4. main does not invoke verification after run; parent must explicitly run
   --verify regardless. Test the CLI data-path boundary, not only run(data).
No live or research training launched while these are unverified.

06:08 UTC: first context implementation finished (worker claims 8 tests
passed). Inspected final CLI: paired_vs_price was added, but wrong bar root,
unchecked dataset digest and missing context/preprocessor fingerprints remain.
Sent bounded correction in SAME OpenCode session; active log now
`/tmp/codex-opencode-entry-context-review-20260921.jsonl`. Requested CLI path
regression, input/model hashes checked before joblib loading, tampering tests,
paired_vs_wait, and automatic verify after run; exact corrected commands in
HANDOFF_CONTEXT.md. Do not copy/run the draft before this correction finishes.

OpenCode's second patch was independently inspected and imported: new
`backend/market/fundamental_features.py`, its tests and research note.
22 tests passed on desktop (no skips), Ruff clean. Stored-data acceptance:
2,936 sessions, 95 columns, 93 names with versions; removing future filings
left 2,264 pre-2024 feature rows and period dates identical. Finite features
and non-NaT dates agree. Module SHA256
`d364dce995936def72c78f2a97159535cc4fab25856ceaec8b43ff87108149fe`.
Artifacts in `E:/AgentWorkspace/entry-timing-pilot-20260920/`, including
`verify-fundamental-features.py` and `fundamental-feature-verification.json`.
This is corrected research input, not a new live strategy. No production
module or frozen fingerprint changed; deployment is not applicable.
Starting main fbc777ea; unrelated evaluation files and prior handoff preserved.

## 2026-09-20 — Implementation delegated to OpenCode on Spark

2026-09-21 overnight continuation: user explicitly asked Codex to supervise
the worker and finish handling the task while they sleep. Thread heartbeat
`supervise-trading-desk-implementation` is active every 20 minutes; inspect
current state before starting work and disable it on completion or a genuine
user-dependent blocker. Initial OpenCode patch completed (three new files,
reported 16 passed / 1 skipped). Codex inspected the module and sent a review
follow-up in the same session: deterministic nearest-quarter lag selection,
per-feature reference-period dates so old ratios are not mistaken for fresh
ones, numerical finite-output guards, and the return-type docstring. Current
worker log is `/tmp/codex-opencode-trading-review-20260921.jsonl`. Wait for
that run before importing the patch; independently test on the desktop venv
including the previously skipped CLI case if dependencies are available.
The initial module was copied outside the repository to
`E:/AgentWorkspace/entry-timing-pilot-20260920/fundamental_features-review.py`
for review only; do not mistake it for the revised patch. No integration yet.

User explicitly requested local OpenCode coding to reduce Codex usage, with
Codex retaining architecture and review. A bounded research feature task is
running under `spark/deepseek-v4-flash`; no model-server changes were made.
Isolated detached checkout on spark1:
`/home/animallya96/codex-worktrees/trading-fundamental-features-20260920`,
base `8c17e72aae2520fe46d69fe0e4dd5b0b317fdf5c`. Task contract is
`CODEX_TASK.md` there; OpenCode session `ses_f3e2a9abcffe1RqJ2eMMs4hriB`;
output `/tmp/codex-opencode-trading-20260920.jsonl`. Read `HANDOFF.md` when
ready, inspect the actual diff, and independently run acceptance tests before
integrating. No approval to deploy or promote its model/strategy was delegated.

Scope: a separate versioned quarterly fundamental feature adapter, retaining
NaN for unavailable inputs, aligned fiscal periods, as-of tag selection and
prospective revisions, with append-future-data invariance tests. Frozen
production/research fingerprints and existing shadow semantics must stay
unchanged. This prepares valid inputs; it does not establish trading edge.
Shared `~/anios` has unrelated AGENTS.md changes and scratch files: preserved.

Deployment VERIFIED: backend checkpoint e1f2a87c passed 3,779 unit tests
(24 skips) and all 100 routing tests through scripts/deploy.sh. Frontend
follow-up 8c17e72a deployed through the same script; cheap post checks passed.
Live authenticated Playwright against that gateway via an SSH loopback tunnel
rendered all 93 names in one table with only BUY/HOLD/SELL, no page/console
or required-market-response errors, and no page overflow at 390px. Screenshots
and read-only test scripts are under
`E:/AgentWorkspace/entry-timing-pilot-20260920/`. Direct LAN port 8080 is
intentionally loopback-bound; testing needs the tunnel. Mobile navigation
dismisses by tapping its backdrop, not the obscured header toggle.
Two local desk browser journeys and nine strategy parity tests pass.

Corrected historical simulation completed: 2,936 sessions through 2026-09-04,
policy cash-bounded-breakout-rotation/2. Artifact corrected-policy-curve.json
in the same external folder. Survivor-universe/data limits remain; the
retrospective curve does not prove a durable edge. Name weights can drift
above the entry cap after fills; a target cap is not a continuous risk limit.

## 2026-09-20 — Shared strategy planner and one-table dashboard

User requested implementation and dashboard repair, then explicitly asked to
minimize usage. Retained the incumbent screened breakout/grade rule; the RTX
5080 pilot did not justify a neural/RL promotion. No optimal-return claim.

Implemented `cash-bounded-breakout-rotation/2`: rotation and breakout orders
share name capacity, buy rounding cannot breach the decision-price cap, and
opening buys use existing cash rather than future close-sale proceeds. The
historical mid-cycle path and account-wide dashboard projection reuse the
paper planner. Experimental targets no longer overwrite adopted API targets.
Reset orders with known cash also receive joint funding and capacity checks.
Whole-share paper fills and fractional historical fills remain distinct;
prices/gaps, skipped sells and broker rejects can still change realized weights.

Dashboard: one stock table, all names rendered, three enum-only plan cells,
separate move/target weights, desk/personal positions and reasons. Removed
duplicate default entry/position/grade tables. Research sizing is explicitly
labelled and opt-in. Price-only chart circles say breakout, not buy. Older
curves are labelled as an older policy. Sharpe and initial-loss drawdown
definitions now agree between the simulator and comparison report.

Local verification: 152 focused strategy/API tests passed, then 85 affected
tests after the last account-cap changes. Eight new shared-planner/reporting
tests pass. Two Playwright journeys pass, including all-stock rendering,
enum enforcement, filtering, reload, row details, desktop/mobile layout,
console/page errors and required desk requests. Frontend production build
passes; existing CSS/chunk warnings remain. Ruff passes targeted modules.
The browser journeys use API fixtures, not a claim of live deployment.

Starting branch main at 09ee4a06, with one pre-existing local UI commit and
untracked routing evaluations preserved. Deployment and corrected full-history
curve checks are in progress; do not label them verified from this note.
Diagram impact: NONE — shared internal policy calculation and existing views;
no new service, datastore, model runtime or trust boundary.

## 2026-09-20 — Conditional entry timing pilot executed on desktop RTX 5080

User asked to audit Claude's latest buy/sell/hold and sizing work, then start
learning experiments for intraday entries held several days to weeks. Added
research-only `backend/market/entry_pilot.py`, CLI `market_entry_pilot`, and
16 tests. Full protocol, measurements, limits and reproduction are in
`docs/research/conditional-entry-pilot-2026-09-20.md`. No production policy or
broker changes. Starting HEAD `09ee4a06`, already one local commit ahead of
origin; unrelated untracked routing evaluations preserved. New work is not a
verified committed/deployed checkpoint.

VERIFIED: trained ridge, 8-/28-feature trees, and two GRU seeds on RTX 5080;
129,823 rows, 63,811 training; 420 retrospective evaluation sessions with
4,082 selected opportunities; all 66 CUDA account paths replay with exact
decisions and NAV atol 1e-10. 16 new tests and 130 existing focused tests
passed; new source Ruff clean. Full tree timing gain +0.234 bp/day versus
immediate entry, paired block CI [-0.289,+0.792]; GRU +0.142
[-0.570,+0.864]. No robust edge and no promotion. Source and dataset hashes
in `E:/AgentWorkspace/entry-timing-pilot-20260920/run-02/manifest.json`.

FAILED: initial data preflight found missing IEX execution bars, including
early-close afternoons; before any fit the protocol moved both decisions to
morning and records unquoted entries as unfilled cash slots. Strict CPU replay
of CUDA GRU predictions also fails (max 0.007436 percentage-log-return units),
although the selected test actions are unchanged. CUDA replay passes; do not
relax the CPU tolerance or call cross-device numerics verified.

Audit findings, not fixed in this atomic research task: the published curve
omits current price entries and grade rotations; price-only chart markers are
labelled buy; board requires a positive target that nightly entries do not;
combined rotation plus entry can exceed the 15% cap (14% -> 16% reproduced).
The sizing comment's hypothetical band=3 is impossible under the 20-observation
self-normalized band (bound sqrt(19)/2). Detailed review saved at
`E:/AgentWorkspace/entry-timing-pilot-20260920/strategy-audit.md`.

Next: repair policy/accounting parity before judging production; preregister
an event-conditioned entry study rather than tune against these reported test
years. Sizing, exit policies, new RL training and untouched forward performance
remain UNVERIFIED. Existing policy, sources and model services are unchanged.
Diagram impact: NONE — internal experiment on the existing isolated research
artifact path, no changed live architecture.

## 2026-09-20 — Within-batch near-duplicate suppression and repeat-fill recency guard deployed; Scout trimmed to jenos1 + ani.mallya

Deployed and verified 2026-09-20 22:25 UTC: commit `ca63c093` through
`scripts/deploy.sh` from `~/deploy/anios`. Gate: unit 3758 passed (was 3747;
11 new), routing gate passed. Post-deploy checks cheap-only
(`2026-09-20T22:25:19Z ca63c093 ok (cheap)`) — `backend/discovery/` is not in
`deploy.sh`'s `search_paths`, so the credit-consuming sweep/search harness was
correctly skipped, matching the user's "don't lose internet credits" constraint.
Backend container verified live: `REPEAT_RECENCY_DAYS` (feedback_loop.py:57),
`_near_any` (novelty.py:377), `last_send_dates` + `window` (runner.py:811-814).

Two Scout defects fixed, both diagnosed from live rows:

1. **Within-digest duplicates** (the "multiple recommendations of the same
   thing today"): ani.mallya's 09-20 19:00 UTC digest carried FRESHFARM x3 and
   Clarendon Day x2 in ONE message — the same happening surfaced from different
   Google URLs → different `external_id` → different digests → all passed
   novelty. Their embeddings were cosine distance 0.045/0.051, under
   `NEAR_DUPLICATE_DISTANCE = 0.08`. Root cause: `novel()` in
   `backend/discovery/novelty.py` deduped within-batch only by digest identity
   (`seen_in_batch`) and checked near-duplicates only against *history*
   (`has_near_duplicate`), never within the batch. Fix: `admitted_embeddings`
   tracking + `_near_any()` so a candidate within the near-duplicate distance
   of an already-admitted candidate in the same batch is skipped.
2. **`_repeat_fill` cross-day repeats**: jenos1's 09-19 20:00 UTC digest
   re-offered COLLECTIVE at The Light Horse (starts 2026-10-03) with
   `shortlist_rank: -1` (repeat-fill) — the cap (`MAX_REPEAT_SENDS = 3`)
   bounds how often, not how soon. Fix: `last_send_dates()` reads the most
   recent send per digest; `_repeat_fill` skips anything sent within
   `REPEAT_RECENCY_DAYS = 14`.

Tests: 20 in `test_discovery_novelty.py` (2 new for within-batch dedup, 2 new
for recency, stub `_StubEmbeddings` now prefers the longest matching key so two
distinct jazz events get distinct vectors — both events collapsed under the
identical `_vec(1.0)` before); 50 in feedback_loop/discovery_runs/delivery;
ruff clean on the test file (remaining runner.py E402/E501 pre-existing). The
previously-failing `test_market_desk_api.py::test_current_research_target_drives_action_over_http`
now passes (other agent's desk work since).

Scout recipients trimmed: disabled `enabled=False` on all `discovery_schedules`
except ani.mallya (daily 19:00 UTC) and jenos1 (daily 20:00 UTC). Disabled:
arsalon, ibraa, and 10 stale test/probe schedules (`del_*`, `api_del_*`,
`sch_7489b1d36309`, `scout_probe_v4`). Verified live: 14 rows, 2 enabled.

Note: ani.mallya's "multiple recommendations" were within-digest, not
cross-day; jenos1's COLLECTIVE was cross-day repeat-fill. jenos1's 09-20 digest
was empty (novel 0). The provider order stays `tavily,brave,google` per the
user's explicit instruction (Google credits are paid; wait for Tavily to
replenish) — no reorder was made.

Open: `_near_any` runs cosine distance in Python against the in-memory batch
(small, fine). A real-utterances phrasing check for the recency window could
be added but is not required for a structural guard. Watch ani.mallya's and
jenos1's next digests for the within-digest duplicate and repeat-fill
behaviour; if either misbehaves, `evaluate_discovery_ranking` is the judge.

## 2026-09-17 — Rolling discovery search window and non-US listing filter deployed and verified

Deployed and verified 2026-09-18 04:19 UTC: commit 8f2ff2a4 through
`scripts/deploy.sh` from `~/deploy/anios`. Gate: unit 3694 passed, routing
gate passed. Post-deploy checks all green on the deployed system:
`sweep_journeys OK` (70 traced turns, 47 routed journeys, no gaps) and
`exercise_search_scenarios OK`. `data/.post-deploy-status` = `8f2ff2a4 ok`.
Both `backend` and `discovery-worker` containers verified carrying the new
code: `WINDOW_STEP_DAYS` present, and both Bali directory pages now
rejected live by `looks_like_a_directory`. Next sweep (today's scheduled
digests) is the first that runs the rolling month window; watch whether
arsalon/ani.mallya/jenos1 digests stop being empty. Open follow-up:
11 `test_aiming_behaviour` failures are pre-existing model drift (model
elaborates no-fact interests against the prompt contract) — a separate
prompt/fix task, not this change.

## 2026-09-17 — Scout digests emptied because the search query never moved; deploy the rolling window

Committed and pushed as 7f170cc (discovery) + 3de021b (handoff), on top of
ecd5672; working tree clean, origin/main in sync at 3de021b. NOT yet
deployed (this handoff is written before deploy). Root cause of the
empty-digest streak: `backend/discovery/sources/web.py::_queries` named a
fixed month ("September 2026" all of September), so every sweep asked the
same question, the engine returned the same top pages, and the novelty
filter marked them all seen — arsalon's live sweeps ran 10-12 candidates
with 0 novel for days, and ani.mallya/jenos1 showed the same signature.
Fix: each interest query names a month a week further ahead than the last
(general stays current month), the sweep's `moment` is threaded into the
source so rehearsals are reproducible, and December rolls into January via
`timedelta`. Skeleton still `{subject} {place} {month year}` — the
measured phrasing. Also fixed `listing_filter.py` letting two Bali
directory pages through as happenings: `/d/indonesia--bali/` (rule only
matched US `/d/va--` slugs) and "The Events Calendar" plural (rule only
matched singular). Both are now labelled cases; `evaluate_discovery_ranking`
listing_recall 0.857→0.875, retention 1.0, no wrongly-rejected. Unit gate
passed 3694 (a first run had one flaky `test_agent_runs` failure that
passed in isolation and on rerun). Note: 11 `test_aiming_behaviour` cases
failed on the live runtime — pre-existing model drift (the model elaborates
no-fact interests like "Chess" → "chess clubs and tournaments" against the
prompt's contract); NOT caused by this change, which never touched the aim
prompt (`prompts/scout/aim` byte-identical). Next: deploy through
`scripts/deploy.sh` from `~/deploy/anios`, then verify with the sweep and
search harness.

Committed and pushed as 7f170cc (discovery) + 3de021b (handoff), on top of
ecd5672; working tree clean, origin/main in sync at 3de021b. NOT yet
deployed (this handoff is written before deploy). Root cause of the
empty-digest streak: `backend/discovery/sources/web.py::_queries` named a
fixed month ("September 2026" all of September), so every sweep asked the
same question, the engine returned the same top pages, and the novelty
filter marked them all seen — arsalon's live sweeps ran 10-12 candidates
with 0 novel for days, and ani.mallya/jenos1 showed the same signature.
Fix: each interest query names a month a week further ahead than the last
(general stays current month), the sweep's `moment` is threaded into the
source so rehearsals are reproducible, and December rolls into January via
`timedelta`. Skeleton still `{subject} {place} {month year}` — the
measured phrasing. Also fixed `listing_filter.py` letting two Bali
directory pages through as happenings: `/d/indonesia--bali/` (rule only
matched US `/d/va--` slugs) and "The Events Calendar" plural (rule only
matched singular). Both are now labelled cases; `evaluate_discovery_ranking`
listing_recall 0.857→0.875, retention 1.0, no wrongly-rejected. Unit gate
passed 3694 (a first run had one flaky `test_agent_runs` failure that
passed in isolation and on rerun). Note: 11 `test_aiming_behaviour` cases
failed on the live runtime — pre-existing model drift (the model elaborates
no-fact interests like "Chess" → "chess clubs and tournaments" against the
prompt's contract); NOT caused by this change, which never touched the aim
prompt (`prompts/scout/aim` byte-identical). Next: deploy through
`scripts/deploy.sh` from `~/deploy/anios`, then verify with the sweep and
search harness.

## 2026-09-17 — Board readability: opportunity, size and plan stay filled after the nightly decision

Deployed ecd56727 (after the other agent's ee0d115; pushed through a
worktree because the shared checkout held uncommitted discovery work).
The user reported the Opportunity column empty for every name, the Plan
column saying the wrong thing, Size % empty for all, and tickers like CRWV
with no opportunity score. Three root causes, all fixed and verified live:

- **Opportunity empty**: `backend/market/opportunity.py` dropped the score
  to None the moment the candle's deadline passed and again whenever one
  analyst had no rank (CRWV has no value rank, so four present analysts
  were discarded). `explain` now always returns the conviction index dated
  to its bar, renormalized over the analysts that have a reading; only a
  name with no analyst reading at all is unavailable. The board cell no
  longer blanks on `valid_until` (StockBoard `opportunity()`).
- **Plan wrong**: `backend/market/decision_view.py` required currency to
  be the session AFTER the record's own, so a decision written on the
  evening of its session (record session == today, offset 0) was labelled
  "Nightly decision outdated or calendar unavailable". `current_decision`
  now accepts offset 0 or 1. Live now: book names show "Wait · Market
  closed or clock unavailable" / "Invalid or empty quote" (honest) instead
  of the bogus outdated label.
- **Size % empty**: research (session 2026-09-16) lags a new nightly record
  (session 2026-09-17) until the candle run sizes it. StockBoard falls back
  to the adopted plan's target weights (`latest.book`) with the caption
  "Plan target weights · next rebalance"; cash row shows the unallocated
  remainder.

Verified: unit gate 3694 passed, routing gate 100 passed, ruff clean, tsc
clean, desk e2e 66/66 (2 new: plan-target fallback, opportunity after the
close; 1 updated to the new contract) on both the shared checkout (5174)
and the deployed build (5173). Live operator API: all 9 book names now
return opportunity scores (NTAP 8.66 … AAOI 7.25) and honest Wait reasons;
CRWV opportunity 3.44/10 (was None). CRWV's "weird score history" is the
data, not a rendering bug: 370 sessions all grade C, score -1.09, rule
backtest in_annualised -1.92. Post-deploy cheap checks green; the sweep
and search harness were correctly skipped (change does not touch the
search chain).

## 2026-09-17 — Plan cell cleaned to the trade line; allowlisted accounts get the Desk icon

Frontend-only, deployed after c898dbbf. (1) The collapsed Plan cell mixed
the planned trade, the analyst-conviction headline, and the execution gate
as a bare "Wait" that contradicted "buy 35 shares". The headline ("Own:
fundamental and value for, none against" — "Own" is an analyst name, which
is why it reads as English) and the "one vote from dropping to A" margin
note now live only in the row's expanded details and the name panel. The
compact decision cell shows the real reason inline — "Wait · Market closed
or clock unavailable" after close — and renders nothing for an eligible
buy (the badge + shares already say it), so "buy … Wait" no longer appears.
Frontend/src/components/DeskPanel/DeskPanel.tsx (TradeCell, DecisionCell
compact, expandRow). (2) The sidebar Desk button was gated on `is_admin`
alone while the page is granted by `auth.desk_access`; vjmallya
(allowlisted in the backend, `MARKET_DESK_USERS=vjmallya`, verified in the
running container) had no icon. Sidebar now takes `deskAccess`
(Sidebar.tsx, App.tsx) and shows the icon for `is_admin || desk_access`;
guests still see neither. Pinned by the desk e2e: plan-cell assertions plus
a new "Desk icon appears for an allowlisted account and stays hidden for a
guest". tsc clean, desk suite 64/64, hash-routing 2/2, theme 6/6.

## 2026-09-17 — The board always shows size, reaches every column on a phone, and a finished FOMC cycle no longer pauses it

The user's follow-ups after the FOMC/IEX deploy were: (1) the Plan column
still read as "unhelpful bullshit", (2) on a phone nothing right of "Size
%" was reachable, (3) sizes should always be visible and "stale" is never
the right word. Three stacked causes, all fixed and verified (tsc clean,
63/63 desk e2e, unit suite 3688, ruff clean).

- **Plan column "Wait · FOMC" returned**: `DeskPanel` computed
  `eventPaused` partly from the record's frozen
  `event_risk.execution_pending` (frontend/src/components/DeskPanel/
  DeskPanel.tsx:912); once `event_status` went stale after close the board
  fell back to the flag and paused every name again. It now reads
  `event_status.planning_paused` only (field added to the `DeskPayload`
  type in frontend/src/services/api.ts:2100). A stale observation is not a
  pause; the frozen nightly flag never is.
- **Mobile: columns beyond "Size %" unreachable**: the board table was
  `w-full`, so its cells shrank/clipped and there was nothing to pan. The
  table is `min-w-max` (frontend/src/components/DeskPanel/StockBoard.tsx),
  so the board's own `overflow-auto` box pans to the Record button while
  the page never scrolls sideways. E2e: the phone test now pans the box
  and asserts "Record purchase of AAPL" is visible.
- **Sizes blanked after close**: a failed/expired run overwrote
  `latest.json` with no `targets`. `intraday_research.publish` now carries
  the last collected allocation (session, bar, valid_until, targets,
  grades, record_sha256) forward on an unavailable run, and the frontend
  shows sizes when `research.session === latest.session && targets`
  exist — it never says "stale". Restored today's `latest.json` from the
  last archived decision (decision-498a7d..., session 2026-09-16, 93
  names); the deployed backend already serves it. New test
  `test_failed_run_keeps_the_last_collected_allocation`. Pinned by the
  desk e2e FOMC cases (mocks now carry `planning_paused: true`).

Open and unchanged: fresh overnight/pre/post prices need a SIP entitlement
(external); the board shows the last in-session allocation instead. The
strict whole-set freshness gate (one stale bar marks research
unavailable) still awaits the design decision below.

## 2026-09-17 — The board's blanket "Wait · FOMC cycle takes priority" is gone (backend fix deployed)

Deployed and live: main `6aab7204`, post-deploy
`2026-09-17T21:03:45Z 6aab7204 ok (cheap)`, backend image recreated
21:03Z; gateway probe reads 401 (auth boundary intact). Two stacked causes
made every plan row read "Wait" with a reason that contradicted reality.
(1) A nightly record written during the FOMC gate freezes
`event_risk.execution_pending = true`; `event_status.for_planning` only
ever SET that flag, never cleared it once the cycle ended, so
`decision_view` paused every name as "FOMC cycle takes priority" until the
next nightly record. `for_planning` now mirrors the live event state both
ways (backend/market/event_status.py:39). (2) The account has no SIP
entitlement (Alpaca 403 "subscription does not permit querying recent SIP
data"), so `execution_quotes.describe` rejected every quote as "IEX only;
consolidated quote required" and no name could ever be "Buy eligible";
IEX quotes now pass the gate with the feed labelled in the reason, age /
spread / size checks unchanged (backend/market/execution_quotes.py:93).
Pinned by `test_stale_execution_pending_clears_when_the_cycle_is_over`
and `test_iex_quote_passes_the_gate`; unit suite 3687 passed, routing gate
100 passed. VERIFIED live on the deployed container: `for_planning` returns
`execution_pending = False`; the "FOMC cycle takes priority" reason no
longer appears — after hours the rows read "No allocation in the adopted
plan" (research unavailable) / "Quote unavailable" (no fresh quote), which
are the genuine states. During market hours with research available and
fresh IEX quotes the plan should now show real actions.

Still open, diagnosed but not changed:
- **Intraday research availability flip-flops** ("Complete fresh price and
  technical coverage required"): `intraday_candidate.calculate` requires
  every tracked name's quote bar to be 15-30 min old at a candle boundary
  (`SNAPSHOT_SECONDS=900 <= age < BAR_SECONDS=1800`), so one name whose bar
  ages out (illiquid/halted) marks the whole set `unavailable`. Observed
  available 18:30, unavailable 18:45, available 19:30. This is why the
  "Intraday + macro research" button intermittently shows the amber reason.
  Needs a decision: is the strict whole-set gate the right design?
- **The technical score is trend-based, not day-based** (user felt it was
  "unreliable/late" because ORCL was up ~4.4% while its technical read was
  ~0.29). That read is correct: ORCL sits ~11% BELOW its 200-day EMA with
  daily/weekly trends down; a single green day does not move a trend model.
  No code change; the board's daily %-move column carries the "today" part.
- **Option walls** (user asked): the 09-16 "walls across expiries to sixty
  days" fix is deployed and correct across all 93 tracked tickers (0
  incoherent walls; ORCL put 140 @ 34,868 OI / call 170 @ 67,005 OI).
  They do NOT update every 15 min — open interest changes once a day
  (nightly fetch + weekday 08:45 ET cron; today's 08:45 run stored 0
  because the nightly already wrote the 09-17 partition, so the next fresh
  chain is 09-18). The 15-min cycle updates price/technical/grades and
  re-renders wall DISTANCES, not the wall levels.

## 2026-09-17 — Desk page split into a live trader dashboard + one Practice account section

Deployed and live: main `22b26f8`, post-deploy
`2026-09-17T17:33:05Z 22b26f82 ok (cheap)`, gateway bundle
`index-URP5vr5N.js`. The desk view is now purely the active trader's
dashboard: the board (with the search moved into the table header, directly
above the rows it filters), a new "Your positions" readout showing the
trader's OWN recorded holdings with live price, value and P/L vs entry plus
a total, the FOMC gate and the plan. All paper material moved into one
collapsible "Practice account" section at the bottom (summary strip, paper
execution, practice positions, track record), labelled "simulated funds ·
the desk's paper book, not your money". Removed "Paper cash" from the live
cash strip (now "Your planned cash"), the inline Paper execution and
Practice positions sections, and the research view's now-redundant
"Performance & practice account" block (its deep-dive "Show practice account
details" stays). FOMC section no longer says "Paper account only";
reworded to "executed in the practice account below". Board rows now show
each name's move against its last close beside the price (green/red arrow,
`↑ +2.0%`), and a held position stays visible even beyond the pagination
fold (the "held position is never invisible" invariant that paging broke).
VERIFIED: tsc clean, desk browser suite 63/63 in Chromium both against the
shared checkout (port 5174) and against the deployed frontend
(`anios_frontend` on 5173), one new test pins the %-change and the
held-past-the-fold behavior. This deploy also carried `d4eb1e8`
(market_event_recovery `after_decision`, grade-first sort) and `8bdc3a3`
(Opportunity column). The morning-after recovery fix only runs after the
recovery hash is re-activated on the deployed backend - the next task is to
verify the live FOMC restoration status on the deployed system once the
intraday run activates it.

## 2026-09-17 — Desk board: ticker search + paged top-10, and honest sizing reasons

Frontend-only, deployed and live: main `a031bba`, post-deploy
`2026-09-17T13:42:11Z a031bba9 ok (cheap)`, gateway bundle
`index-CK2euoze.js` (the gateway's served index.html references it, and the
bundle carries "Search a ticker"). VERIFIED: tsc clean, the desk browser
suite 62/62 in Chromium against this tree (three new tests: search and
paging, no-match state, refused-preview reason), and a live DOM walk shows
the "Search a ticker" box rendered above the ranked board. The board now
opens with the top ten names and pages on a Show more button (replacing the
grade-C fold); a search filters by ticker with a match count and a
no-match state. `getDeskFundingPreview` surfaces the backend's 422 detail
verbatim instead of a generic failure, and selecting "Intraday + macro
research" gives immediate feedback (ready, or the reason it is not). If the
search bar is not visible after this deploy, it is browser cache: hard
refresh. The intraday research allocation is currently unavailable (last
ran 2026-09-16 16:45), so intraday sizing legitimately waits for the next
market open; the page says so.

## 2026-09-17 — Desk page trading-UX fixes deployed and verified

Frontend-only, deployed and live: main `962def5`, post-deploy
`2026-09-17T12:56:47Z 962def51 ok (cheap)`, gateway bundle
`index-DzmiQsst.js` carries the new strings. VERIFIED: tsc clean and the
desk browser suite 60/60 in Chromium (two new tests pin the changed
behavior). The desk's positions editor rendered twice - the inline form in
the board's plan toolbar and the full-screen "Your positions" modal - so
editing showed two overlapping editors at once; the modal is now only the
no-record fallback. The "absent" prose status shows the block's own reason
("prose on file predates this decision") instead of a generic "have not
been written yet". The Today line's FOMC restoration wording no longer
reads "fill at the next fill" (open: "are being placed now", closed: "fill
at the open"). Header buttons are capitalized to match ("Analyze my
trading", "Hide the review"), and the name panel's "In short" price keeps
cents. The other agent's backend search/discovery work is committed
separately (`33e2618`).

## 2026-09-17 — System review fixes deployed (Scout, search pool, undo, tasks)

Deployed and live: main `33e2618c`, post-deploy `2026-09-17T07:00:43Z 33e2618c ok`
(full sweep + search harness, not cheap: the change touched the search chain and
the router prompt). One journey flaky on retry ("forget that (memory undo)"),
the rest green; search harness passed live: a what's-on question answered from
8 web sources, meter reads "Brave: 125 of 900 requests left this month".

**Scout root cause (verified): Tavily's free credits are exhausted — 1000/1000
spent, remaining 0 — so the chain falls to Brave, whose results are evergreen
club/blog/directory pages that novelty-suppression then drops → 0 finds for 3
days.** The tavily-first order is a deliberate 2026-08-29 decision (`.env` and
`.env.example` agree; do NOT revert it). In-code fixes now: a provider the meter
knows is spent is skipped when the chain is built (no wasted 432 probe first);
a last-rung 429 is attributed to the actual provider and only Tavily's own
refusal reconciles the shared pool spent (a Google rate limit can no longer
freeze everyone's search for the month); discovery search failures are logged
instead of swallowed. **To actually restore rich Scout finds: top up Tavily
credits (external).** jenos1's digest failure is separate and external too:
`channel_unreachable` on their iMessage number since 09-15 (bridge/contact).

Also fixed in this batch: undo of a freshly created reminder (was "nothing to
undo" or undid an older memory save); `prepare_context` guards every store read
(a failing store costs its part, not the whole reply); a failed preferences read
is logged (constraints never drop silently); a once-task whose only slot passed
while down is enqueued for an apology, not dropped forever; a delivered run is
never re-claimed (mark_delivered right after send); skill/task mutations report
what the datastore actually did; Deck calls run greedy + enforce the 3-8 slide
band; frugal_search crosses the MCP boundary explicitly; the turn prompt no
longer promises a same-turn retry the loop forbids. Pinned by unit tests.

Deferred (P3, feature-sized, not in this batch): episodic recall's keyword gate
+ recent-5 (needs embedding or a model-decided intent); `MemoryEntityRelation`
written via API but never read in recall; `_BUDGETED_KEYS` excludes working/
summaries from the shared context budget.

Note for the workspace: the other session (trading desk) has UNCOMMITTED edits
in `frontend/e2e/desk.spec.ts` and `frontend/src/components/DeskPanel/DeskPanel.tsx`;
they are not mine, were not committed or deployed here, and must not be swept
into another commit.

## 2026-09-16 evening — Operational state for the 09-17 morning check

Deployed and live: main 5e86b1dc (post-deploy `ok` 20:42 ET): the prose
branch merged (decision saved before prose), the desk layout
(Stocks / Plan / Research), the ML ledger continuation. The 09-16 record
was written 20:25 ET on 5d7a753; the ML observer continued the ledger
(sequence 2, policy_from 72162f00…). Nine FOMC restoration buys are
acknowledged by the broker (created 20:24 ET) for the 09-17 open: AAOI 15,
AMD 4, ANET 19, LITE 1, MDB 4, NTAP 20, NVDA 12, SMCI 60, SNDK 1; the
cycle `fomc-3-session-weakness/2:2026-09-16` is open until they fill.
Check after 09:45 ET: fills in `data/market/paper/state.json` and
`desk/execution.json`, `event-live.json` inactive, the gate's first row
complete. Option chains: `market_options --refresh` moved out of
`~/desk_daily.sh` (backup `.bak-20260916`) into a weekday 08:45 ET cron
writing `~/desk_options.log` (crontab backup `~/crontab.bak-20260916`).
Tonight's nightly fetch is labelled `asof=2026-09-17` (UTC date at
00:27Z), so the 09-17 morning fetch skips; the first morning-fresh chain is
09-18. Data revision still to name in the record: a tone re-score under a
new prompt version that moves a grade (PANW, 09-11 and 09-15). No strategy
or sizing change; the release-event vote stays unpromoted.

## 2026-09-16 — Persistence length closed; ticker panel; FOMC board; walls

The persistence study is closed (three sessions stays; see the research
note). The ticker panel now leads with the grade move; the board keeps
sizes during an FOMC cycle at the desk's exposure; walls sum open
interest across expiries to sixty days. Still to do on the 09-17
morning: move `market_options --refresh` out of `~/desk_daily.sh` into
a weekday 08:45 ET cron (the nightly's fetch is labelled with the next
UTC date and would make the morning fetch skip); verify the FOMC
restoration fills and the cycle closing; name prompt-version tone
re-scores as a data revision in the record when they move a grade.

## Deployment handoff

All requested source changes are pushed for manual deployment. Research-only
dependencies (scikit-learn, joblib and threadpoolctl) are declared in the existing
research extra; they are not added to the production image. Install .[research]
only in an isolated training environment. Run bash scripts/deploy.sh on the
deployment host; its gates and post-checks still determine live verification.
Deployment does not activate an ML trading policy or reset any paper account.

## 2026-09-16 — Desk page word-and-word fixes verified and deployed

Frontend-only change, `5d871d2a`, deployed through `scripts/deploy.sh`; marker
`2026-09-16T16:53:19Z 5d871d2a ok (cheap)`, post-deploy checks green, gateway
bundle `index-DcAt9SFH.js` carries the new strings. VERIFIED: `tsc --noEmit`
clean and all 52 desk Playwright tests passing in Chromium (four new tests pin
the changed behavior). A user-perspective review of the desk page fixed four
readings that would mislead: `Trend`/`TrendUsd` drew a green up arrow on a $0
day P/L, so zero read as a gain (flat now keeps a neutral mark); the board's
Action column collapsed four different conditions into the single word "Wait"
(now "Wait · expired", "Wait · no size shown", "Wait · unavailable" on the
compact board); one stale quote disabled sizing for the whole board (a name
whose live quote does not share the research bar now gets a dash, the header
names how many sizes are current, and the cash row plus weight ranking stay
all-or-nothing so no incomplete figure is shown); a failed holdings read left
the simple view's Positions button silently dead (the board's alert now carries
the real error and the button explains itself). The OpportunityCard guards a
zero-weight part from rendering "NaN%". The plan row's "record fill" stays
gated to due rebalances on purpose - the board's discretionary Record buttons
cover off-schedule purchases, and browser tests assert that separation.
## 2026-09-15 — Prose beside the decision (branch prose-beside-decision)

Held off main until the 2026-09-16 nightly has verified the previous
day's changes on a real run. Once merged, `desk.json` carries empty
`briefs` and null `read`s by design; the model prose is `prose.json` in
the same folder (with `prose-job.json` and `prose-results.jsonl` as the
child's working files), merged on read with `prose_status`. The first
nightly after merge is the acceptance path: check that `prose.json`
exists beside the record, its status, and that the Desk view shows the
briefs. `--prose-budget-minutes` (45) terminates the child at the wall
clock; size it from the observed elapsed time in the block. Merge and
deploy together: the API container merges the prose on read, so until it
is rebuilt the page shows a decision with no briefs.

## 2026-09-15 — Reversal shadows (branch reversal)

Both registered forms failed their bar; both record forward from the
09-16 decision. The page does not yet show `reversal_shadow`; add a
details section when the first cycle has an entry. No retune on these
events; a new specification is a new registration.

## 2026-09-15 — FOMC gate (branch fomc-gate)

The overlay's gate is registered and priced nightly; nothing to decide
until six meetings are complete (about mid-2027). Restoration for the
September cycle is due at the 09-17 open; the gate block will show the
completed row after it. Do not tune the policy: a change restarts the count.

## 2026-09-15 — Nightly hardening (branch nightly-hardening) and the roadmap

The nightly now holds a lock, budgets the tone step at three hours and
writes the ML observer's receipt into the record. `docs/TRADING_ROADMAP.md`
is the order of work: data correctness first (as-of fundamentals, stage
two after a week of recorded blocks), a nightly that always ends with a
record (next: a red dashboard status when a session has no record or no
observation by a deadline), measurement on untouched sessions, execution
measured, strategy last and only through a named shadow with a gate
written before its first session.

## 2026-09-15 — As-of fundamentals, stage one (branch fundamentals-asof-shadow)

Every nightly record now carries `fundamentals_asof`: the plain rule on
the stored filing versions against the frozen path, grade, score and
weight differences named. Review a week of those blocks before stage
two (the value analyst reading `fundamentals_asof.levels`); the switch
changes grades and is a correction of an input, not a strategy change.
The nightly's tone step is the book's alone again; breadth tone runs
separately. The valuation-increment and price-candidate lines are
closed: insufficient evidence to advance.

## 2026-09-14 — Observer ordering fix (main)

The nightly's ML observation now runs after bars and filings and before
release-tone scoring (`observe_ml_forward`, `refresh(after_filings=...)`).
Fingerprint unchanged; no ledger reset. VERIFIED: 25 nightly and shadow
tests, ruff, black. The nightly script pulls main before it runs, so the
next 19:30 ET run carries the fix without a deploy; the API container does
not run the nightly. First observation and next-session fill: pending
until a run completes with the fix in place.
## 2026-09-14 — Corrected-data rerun (branch research/fundamentals-asof)

The ladder was rerun once on the as-of fundamentals with the original
configuration; the comparison with the frozen-data run is in
`docs/research/opportunity-learning-asof-2026-09-14.md`, every figure
retrospective. VERIFIED: nine selector tests and one comparison test, ruff,
black; price fingerprint identical between runs; artifacts at
`E:/AgentWorkspace/opportunity-learning-asof-20260914`. UNVERIFIED:
nothing deployed; production fingerprint unchanged. Next: nothing to tune.
The frozen production ledger accumulates untouched sessions; a decision to
export the corrected-data network as a second shadow policy is the
operator's, and would run beside the frozen one, never replace it.

## 2026-09-14 — As-of fundamentals correction (branch research/fundamentals-asof)

The research path now has a versioned, as-of fundamental selector
(`backend/market/fundamentals_asof.py`), its store kind
`edgar_facts_versions`, a refresh/audit CLI and six regression tests. The
frozen production experiment is untouched: fingerprint 0e175165d972a1ab,
no edit to edgar, levels_pit, opportunity_learning, growth_pilot, calendar
or opportunity_shadow. Nothing retrained.

VERIFIED on the desktop: the six tests, ruff, black; versions fetched for
all 93 bundle names (no failures); the audit run and its numbers in the
changelog entry above this one. UNVERIFIED: nothing deployed from this
branch; production reads none of it.

Next atomic task, when the operator chooses: a retrain of the supervised
ladder on the as-of path with the same splits, purging and selection as
the 2026-09-14 run, as a new run directory, compared against the frozen
bundle only on untouched sessions. Not before the forward ledger has its
first fills verified. No parameter search.

## 2026-09-14 — Frozen ML forward-paper checkpoint (this branch)

Branch `research/growth-gpu-audit` carries the finished forward-paper
implementation. The architecture is: dated market data and filed
fundamentals → frozen features and the training normalizer → frozen
NumPy scorer → portfolio targets → separate paper ledger → dashboard
comparison. Boundaries that must survive any later change:

- Research and production are separate. Training and model selection
  happened offline; production loads `opportunity_neural_v1.npz` with
  `allow_pickle=False` and needs neither Torch nor a GPU. The export CLI
  (`market_opportunity_export`) refuses any run whose validation winner
  is not the neural model and verifies NumPy inference and every
  historical basket against the Torch model before writing.
- Five policies keep independent records at two cost assumptions
  (`neural`, `valuation_rule`, `momentum20`, `SPY`, `USD` × 10/30 bp).
  Nothing shares cash or holdings with the Alpaca paper account, the
  board paper account or the person's positions.
- Decisions are recorded before simulated fills and filled at the next
  session's close. A missed daily run cancels the intent; stale history
  cannot generate a historical trade; a missing held mark fails closed.
- Integrity: the record's `policy` is the SHA-256 of the bundle plus the
  feature, execution, filing, level and calendar modules; a changed model
  or changed execution code refuses to continue an existing ledger and
  must use a separate directory. Ledger entries are append-only.
- Promotion needs paper evidence. The network has no demonstrated
  prospective advantage and does not control the deployed allocation.

Entry points: `python -m backend.cli.market_opportunity_forward
--data-dir data/market` observes once and prints the receipt; the
nightly `market_daily` calls the same observer before grading when run
for the current date. The desk route's `ml_forward` field and the
board's "ML paper comparison" panel read the latest record only.

VERIFIED on the desktop (Windows): `test_opportunity_shadow` (7),
`test_market_daily` (16), ruff, black, `tsc`, the ML-comparison
Playwright test, `docs:diagram:check` (32 diagrams and the page). Five
desk-API tests fail here for lack of `fcntl`, identically on origin/main;
they are Linux tests and passed in the Linux run of the previous entry.
UNVERIFIED: deployment. The user runs `scripts/deploy.sh` on the
deployment host manually; the first ledger record is written by the first
nightly run for a current date after 16:00 ET, and the panel shows
"awaiting first close" until then.

Next atomic task: none of code. Let the accounts accumulate untouched
results for a season, then compare the five policies at both costs on
the same real sessions. Do not retrain, add RL, change the live
allocation, or promote the network before that record exists.

## 2026-09-14 — Price-sensitive ML comparison and paper fixes

User authorized proceeding with supervised ML and fixing the two paper defects.
Source b92ca4ff trained ridge, boosted trees and one small CUDA neural network
using price and filed-financial features. Neural epoch 10 won 2024 validation;
2025+ net return was 63.72% versus trees 121.07%, fixed valuation 255.52%, and
momentum20 419.01% at 10 bp. All are biased retrospective results; none promoted.
Six frozen learned-model cost paths replayed. Artifacts and exact evidence:
docs/research/opportunity-learning-2026-09-14.{md,json}.

Paper v2 reads current corporate actions independently of completed daily bars
and uses the selected intraday allocation for direction and size. HTTP decision
targets match current research too. VERIFIED: 75 targeted Linux tests, 16 Windows
research/accounting tests (four overlap), lint, real AAPL action-adapter call,
32 diagrams and architecture page synchronized. Diagram impact: NONE.
UNVERIFIED deployment: desktop SSH to spark1 denied. Do not claim the live site
contains these fixes; deploy through scripts/deploy.sh from an authorized host.
No new ML forward record or production model promotion occurred.

## 2026-09-14 — Bounded desktop GPU replication

Research source checkpoint bd2816c2 adds explicit CPU/CUDA selection, default CPU,
with fail-closed unavailable CUDA and portable saved weights. VERIFIED: one-seed
two-epoch/two-episode CUDA smoke completed on RTX 5080 in 4.88 seconds; four saved
cost curves replayed on both CPU and CUDA; 17 focused tests and lint passed.
VERIFIED: exact original tensors exported from Spark passed the unchanged price
and feature hash checks; all 12 original curves replayed on CPU and all 12 on
CUDA, with exact decisions/dates and NAV tolerance 1e-10. Desktop recomputation
differs in 7,633 finite feature elements by at most 2.220446049250313e-16;
an isolated NumPy 2.5.2 retry did not resolve that raw hash difference.
Frozen replay receipt: desktop growth-pilot-transfer-3dcce629/frozen-replay.json.
Original artifacts preserved; no strategy promotion, live deploy or Spark change.
Evidence: docs/research/growth-gpu-replication-2026-09-14.md. No broader work is
part of this checkpoint. Diagram impact: NONE — internal device selection only.

## 2026-09-14 — Neural/RL growth pilot completed, not adopted

User authorized trying neural and RL models and requested distinct evaluation
after Warsh's guidance change. Official June 17 statement already omitted forward
guidance; August 28 Jackson Hole speech elaborated on the position. Both boundaries
are reported, with event days separate from full post-event sessions. Do not assert
a statistically established permanent break or causal explanation of stock losses.

New isolated CPU CLI market_growth_pilot trains a small supervised return network
and sequential categorical policy-gradient allocator with cash/partial exposure.
2018–2023 training, 2024 selection, 2025+ retrospective evaluation; labels purged
at boundaries. The NN is not an in-sample input to RL. Reward is undiscounted
net log wealth. Trades delayed to next close, holdings drift, fees are funded,
held-price gaps invalidate the run. Costs 10 and 30 bp per traded dollar.
Current-book membership and adjusted fractional prices are explicit limitations;
this pilot does not replay the full desk, intraday quotes or adopted FOMC overlay.
No promotion or production deployment is intended for a research-only CLI.

VERIFIED: training at 3dcce629 completed: three neural scorers, three sequential
RL policies, 22 account paths (five baselines plus six learned policies, two
cost settings). Saved model replay reproduced all 12 learned-model cost curves,
exact decisions/dates and NAV within 1e-10, after price/feature hash checks.
Twelve targeted accounting/causality/objective tests and lint passed. All 32
diagrams and the architecture page synchronized; both changed views inspected.

Test initial NAV January 2, 2025 through September 11, 2026, 423 transitions.
At 10 bp, NN total returns 114.75/163.09/183.59%, RL 9.00/99.47/201.58%, versus
momentum20 357.27%, momentum120 396.68%, SPY 31.19%. Current thematic membership
creates material survivorship/selection bias: these are not investable forecasts.
NN drawdowns 48–53%; RL seeds unstable. No contender beat the momentum baselines.
After Jackson Hole, NN +6.73–13.18%, RL 0–2.81%, but only nine sessions and no
FOMC decision. June 18–August 27: 49 sessions, one decision. September 14 is
outside the completed daily history. No permanent/causal regime inference.

Artifacts: /home/animallya96/research/growth-pilot-20260914-3dcce629 on spark1;
report and machine summary: docs/research/growth-pilot-2026-09-14.{md,json}.
UNVERIFIED: full desk/DeepSeek features, historical membership/delistings,
intraday execution realism, adopted FOMC overlay comparison and superiority.
Only CPU research ran; live dashboard revision remains 2cc8ebff. Nothing trained
here is read by a production trading decision. No research-only deploy needed.
Diagram impact: UPDATED — market-data, agent-trading-desk.

## Latest verified live checkpoint — 2cc8ebff

Supersedes the pending deployment statements below. Normal scripts/deploy.sh
passed 3570 unit tests (19 skipped, 143.70s) and 100 real routing tests (477.77s).
Backup/restart completed; post marker: 2026-09-14T19:51:02Z 2cc8ebff ok (cheap).
Public browser asset index-C6vOi0E9.js verified numeric opportunity score,
nightly-valuation and recorded-vote disclosures, one 94-row board, USD first,
FOMC Wait, cancelled manual Buy, 25 recommendation rows and paper USD 100%.
Mobile board width 364/364px; zero page, console or required network errors.
Final targeted opportunity browser case passed (4.8s); TypeScript passed.
Evidence: /private/tmp/desk-opportunity-public.log and public browser screenshots.
Final source changes are pushed; follow-up documentation records this evidence.

UNVERIFIED: tonight's expanded 531-name refresh, broader adopted grading,
calibrated current-price return forecasts, and any trained growth RL policy.
The data inventory found 1,472,051 daily rows (531 stocks, 518 with >=750 rows),
but 438 histories lag at September 4. Only 93 are current through September 11.
No intraday Parquet or .pt model artifacts were found in the inspected store;
historical experiment corpora elsewhere remain unverified. See research report.

## Latest verified live checkpoint — 413447fa

Deployed through scripts/deploy.sh: 3563 unit tests passed, 19 skipped (149.83s),
100 real routing tests passed (476.58s), backup/restart and cheap post-check
`2026-09-14T19:26:29Z 413447fa ok (cheap)`. Public browser asset DTSbP3wX:
94 rows in one table, USD first, FOMC Wait, Buy cancelled with no write, 23 ticker
history rows, paper USD 100%, mobile 364/364px, zero browser/network errors.
All 32 diagrams and the published architecture page checked; changed SVG inspected.

New synthetic run initialized at 19:27:47 UTC with $100,000 USD, no positions or
fills. All 93 shared-planner actions were Wait. Existing Alpaca paper state and
personal holdings hashes unchanged. First 19:30 cron paper observation FAILED:
container-root initialization made the new folder unwritable by the host user.
Fixed ownership of ONLY desk/board-paper to match intraday-research. An observation
as the host UID then persisted sequence 2 at 19:32:01 UTC, unchanged $100,000 cash
and no fills. VERIFIED unattended scheduler acceptance: sequence 3 persisted at
19:45:29 UTC with $100,000 cash/equity, no positions and no fills.

Current follow-up implements a transparent 0–10 analyst evidence index, its
component weights/dates/reasons, current-score stock ordering, and prospective
score archiving. It is explicitly NOT a calibrated return forecast and discloses
nightly valuation. Scores disappear when price evidence expires. The existing
daily refresh is widened to all 531 tracked stocks for bars, filings and new
DeepSeek release scores, retaining the 93-name adopted strategy until broader
grading is evaluated. UI states graded versus tracked scope; no claim all 531
already receive valid grades. Neither a 13% drop nor a cheap-looking stock is
automatically a high-quality opportunity.

VERIFIED locally: 91 targeted backend tests (1.68s), 44 browser workflows (1.3m),
TypeScript/Vite and lint. Follow-up checkpoint/deploy/public score acceptance pending.
User clarified cumulative gain, NOT Sharpe. Added a tested net-log-NAV objective;
no volatility division or hidden risk penalty. Read the existing historical ML/RL
experiments but do not treat their old reward results as a rerun for this objective.
No new trained growth policy or broader-universe strategy has been promoted.

Real-input scoring caught a FAILED boundary before promotion: a92b7b64 required
a stored rotation percentile, but all current records have only its vote. Stopped
that deployment before backup/restart, fixed the explicit recorded-vote fallback
and added a regression test. At 19:37:20 UTC on the real 19:15 bar, 79/93 names
had complete scores; 14 were correctly withheld for missing evidence. Top index:
SNDK 9.297 at $1560, NTAP 8.630 at $190.80, LITE 8.076 at $835.50. These are
indicative analyst indices with nightly valuation, not learned returns. All 93
actions stayed Wait; account files were unchanged. Restart the full deployment
gate for the fix; do not reuse the interrupted gate as passing evidence.

## 2026-09-14 — USD, ticker history, separate forward paper and RL audit

Started on main f6f6758a with seven unfinished ticker-history files. Pull --rebase
refused the dirty tree; fetch confirmed origin/main is exactly f6f6758a. All
changes in this task are authorized; old paper account and manual holdings remain
untouched. f6f6758a was already live (18:50:32 UTC; public asset DV8D3zOx).
The prior handoff's "not deployed" line below is superseded.

Implemented original recommendation timeline on the existing ticker route,
including grades, allocation changes, policy provenance and validated stock moves.
No stock move is called strategy profit. Recent display is bounded to 200 rows
from 1000 archives; originals remain on disk. USD replaces Cash. Empty recorded
accounts show 100% recorded cash; during an FOMC pause their cash size is 100%.
Outside a pause the Size column remains model target allocation, while recorded
cash stays separately labelled. Analysis date is now separate from intraday bar
date: September 11 is the nightly basis, not evidence the quote collector stopped.

The new board-paper ledger is an opt-in local forward simulation, not an Alpaca
reset. It starts only through explicit initialize(), preserves existing history,
uses shared dashboard action gates and research sizes, and observes the ordinary
collector. It delays fills until a later observation, revalidates quotes/actions,
uses whole shares, displayed size caps, bid/ask plus 10 bp per side, and cannot
borrow. Same-observation sales cannot fund purchases. Each immutable observation
contains resulting cash, positions, fills and original decisions. Policy changes
clear pending intents. Overnight valuation waits for complete action coverage;
unknown-pay-date dividends are receivables, not spendable cash. These are model
limitations, not a proven brokerage execution replica. SIP remains unavailable;
exact dashboard eligibility therefore blocks new simulated buys too.

RL audit counts independent dates, quote feeds and actual feature snapshots.
New public state snapshots are archived prospectively; old ones are never
reconstructed using current information. No trained RL policy is promoted.
Remaining: final verification, checkpoint/push/deploy, initialize the separate
run, live browser acceptance, real-data RL audit and research report.

VERIFIED so far: 53 focused backend tests (1.70s), TypeScript/Vite; 42 existing
browser workflows passed and the corrected timeline plus USD/paper workflows
passed (2 tests, 8.1s). Final expanded tests and deployment still pending.
Diagram impact: UPDATED — agent-trading-desk.

Further steering: best current-price opportunity first, GLW as an example, and
systematic stock coverage beyond user-supplied names. Actual universe has 531
members but book_sides admits 93; GLW is excluded by that theme filter. Live
expectations value vote is nightly (SNDK rank .949), technical updates intraday.
Do not call the existing rank a current fair-value forecast. Broad-universe and
compatible intraday expectations work remains. RL audit: 22 observations, one
session, 0 full state snapshots, 19 missing quote records and 3 IEX. See
docs/research/desk-rl-readiness-2026-09-14.md.

## User steering — one board, cash ranked, ticker recommendation history

The user rejected multiple default sections and asked for one table of every
stock, rank, dynamic percentage sizing, plan action and Buy. Buy records a
confirmed manual brokerage fill; it never places a real order. Cash is an
explicit allocation, ranked alongside stocks; FOMC keeps stock actions at Wait
and cash first without inventing a 100% cash balance. The default frontend now
uses StockBoard; the prior detailed view remains behind Details and the deep
link `?deskDetails=1#desk`. When current research sizing is available, allocation
weight determines priority, then existing grade/conviction breaks ties. The
main view identifies model sizing as experimental; adopted action controls
remain in force. The recorded expectations-model vote is still nightly.

VERIFIED locally: 41 dashboard workflows passed (1.6m), including cash changing
rank at the next candle, FOMC pauses, mobile width, and a confirmed Buy whose
shares/cost persist after reload. TypeScript passed. This single-board UI is
not deployed yet. The user also requested per-ticker recommendation/size history
and asked whether the dataset could support RL. Ticker timeline implementation
is in progress. No RL training or promotion is authorized as a completed result.

## 2026-09-14 — Plan actions and forward evidence (deployment pending)

User authorized all five enhancements. Started clean on main `3e0337d3`, pulled
origin/main (current). Added dated plan actions, SIP/IEX quote checks, entry/wait
archives, grade outcomes with sample limits, and a correlation-cap research arm.
Adopted FOMC and paper order logic are unchanged. Detailed methodology and
limitations: `docs/research/desk-forward-evidence-2026-09-14.md`.

VERIFIED pre-deploy checkpoint `135e5d31`: 63 focused backend tests passed
(1.81s), including HTTP preview with unchanged files; lint passed. TypeScript
and Vite passed (existing CSS/chunk warnings). All 32 diagrams and the published
architecture page are synchronized; changed diagram visually inspected.
38 dashboard browser workflows passed (1.4m); quote expiry and empty
outcomes included. The browser caught and fixed the API client's dropped
`decisions` field. Initial focused backend run: 62 passed (1.92s), including
split/dividend accounting. The later 63-test run includes HTTP context coverage.
UNVERIFIED: current-turn deployment and public browser acceptance still pending.
Current provider evidence: SIP 403, IEX 200; no subscription was purchased.
Do not call IEX execution-qualified or claim mature forward performance.
Diagram impact: UPDATED — agent-trading-desk.

Follow-up verified before final deployment: `6e090ba9` makes 30-second quote
deadlines visible to the second, labels cohort averages, and shows missing
outcome counts. Two relevant browser workflows passed (11.5s), TypeScript/Vite
passed. A version-boundary regression then exposed that old signals lacked later
price observations after a policy change. The evaluator now shares observed
prices without mixing original grades/policy groups: 41 focused tests passed
(1.89s). This requires the normal backend gate again; do not skip it.

Read-only live-input candidate check at 18:20:57 UTC: 93 grades and 93 IEX quotes,
12 breakout / 16 dip / 65 wait states; correlation calculation available with
no caps binding on the current small weights. Paper state file hash unchanged.
These are current input checks, not evidence of profitable timing.

## 2026-09-14 — Recover missed FOMC reductions

Started clean on main `0aa70861`; pulled origin/main, already current. The user
requested continuation through the remaining execution gap. Implemented regular-
session paper-only recovery of an already-qualified FOMC reduction. It rebuilds
the policy from the exact prior-session panel, requires fresh completed prices
and the broker's open-session clock, journals before submitting, and retries an
uncertain acknowledgment with the same client ID. Partial fills reduce only the
remaining quantity. Unknown event receipts no longer disappear during nightly
reconciliation. Lower actual holdings block an unsafe retry. Recovery never buys,
extends an expired event, advances the rebalance clock, or cancels other orders.

Nightly execution and the green-day cancellation path share a POSIX file lock
with recovery. A code-hash activation written only by gated deployment prevents
the independent cron Git pull from activating new order logic early. API/UI show
current event evidence separately from the archived decision and pause planning
against durable event intent. FOMC restoration retains the adopted rule after
the measured comparison in `docs/research/fomc-restoration-2026-09-14.md`: the
trend gate raised historical drawdown and has no distinguishing result in the
newer period, which contains only one completed meeting.

VERIFIED pre-deploy: 60 focused backend tests (1.33s), 35 browser workflows
(53.7s), TypeScript/Vite and lint. A current-account dry run through the actual
broker reads proposed nine sell orders and persisted all nine intents in a
temporary state copy; every broker write was intercepted. It touched no real
paper state or broker orders. The final stale-event browser case reproduced a
misleading "decision missing" heading over a durable active cycle. Checkpoint
`49e62285` fixes the heading and fallback explanation; all five FOMC browser
cases passed (9.3s), as did TypeScript.

VERIFIED live trading checkpoint `49e62285`; backend execution content is
unchanged from `2ead7c49`. The initial deploy passed 3523 unit tests (19 skipped,
141.43s) and 100 routing cases (493.67s), but its already-running older script
did not execute the newly pulled activation hook. Recovery remained off. The
updated script was rerun normally: 3523 unit tests (19 skipped, 139.79s), 100
routing cases (490.94s), backup, restart, and successful activation at
16:47:00 UTC. No gate was bypassed. The final frontend-only deployment shipped
`49e62285`, with marker `2026-09-14T16:47:51Z 49e62285 ok (cheap)`.

VERIFIED real paper recovery through the normal host collector: nine sell
orders filled in 14 executions between 16:48:16 and 16:48:18 UTC on September
14. Total 136 shares: AAOI 15, AMD 4, ANET 19, LITE 1, MDB 4, NTAP 20, NVDA 12,
SMCI 60, SNDK 1. Paper cash moved from 58.81% before recovery to 78.85% at
16:48:26 UTC (78.83% at the next price observation). A second collector run
settled all nine journal entries, left zero pending/open orders, and preserved
the same fills, positions, order sequence 9 and ordinary rebalance clock:
last rebalance September 10, sessions since rebalance 1. The event cycle
remains active, so ordinary allocation previews stay paused until restoration.
This verifies paper execution, not real-account execution or strategy returns.
The unattended 13:00 ET cron tick refreshed event status at 17:00:25 UTC with
the same nine-order sequence, fills, zero pending/open orders and unchanged
rebalance clock. This confirms operation on the configured 15-minute schedule.

VERIFIED authenticated public Chrome desktop/mobile workflow: asset
`/assets/index-DJFyec85.js`, 18 successful API responses, all 93 grades, five
economic rows, zero-cash preview, manual-buy cancellation, actual 14 execution
records, current "reduction settled" status and zero event receipts awaiting
reconciliation. The review returned HTTP 200 with the correct no-trading-docs
message. Zero page, console or network errors; desktop board 958/958px, mobile
1376/1376px, account width 356/356px. API, broker adapter and recovery module
SHA256 hashes match source exactly; activation matches the deployed execution
hash. Temporary browser credentials were removed from Mac, host and container.

Evidence on Mac: `/private/tmp/desk-event-{before,submitted,settled}.json`,
`/private/tmp/desk-event-public-proof.log`. Deployment logs on Spark:
`/tmp/desk-event-{recovery,activation,final-ui}-deploy.log`. The repeat deployment
also triggered the full general application sweep and search harness because
its source diff was empty. VERIFIED final post-deploy verdict at 17:13:53 UTC:
50 journeys passed, zero gaps, 70 persisted traces for 47 routed journeys;
all six search-harness checks passed. Both harness accounts were cleaned up.
UNVERIFIED outside trading scope: five image journeys were skipped because the
picture service was unreachable; 19 unit-suite skips likewise are not passes.
The full post-check marker names backend checkpoint `98597484`; the deployed
application marker remains the newer, browser-verified UI `49e62285`.

## 2026-09-14 — Trading review, allocation percentages and execution evidence

Started on main `42b928b9` with three unfinished task files. Pull initially
refused the dirty tree; fetch confirmed origin/main was the same revision.
Objective: repair the actual review HTTP 500, distinguish current research
percentages from nightly portfolio targets, and show broker execution evidence.
FAILED boundary: autopsy called nonexistent `AgentMemoryManager.search`.
It now uses the owner's `knowledge.search`; regression tests instantiate the
real facade instead of inventing its interface. The browser offers cancel,
timeout and retry, and avoids duplicate development-effect requests.

Rankings show fresh research target percentages without cash input; session,
bar, pause and expiry checks withhold unavailable targets. The page reloads
allocations each minute. Cash-funded share arithmetic expands on demand.
Nightly analysis/risk/portfolio targets are dated. Paper execution reads actual
FILL activity by execution date, keeps partial executions and identifies a
truncated 100-row page. Missing history does not erase the account or imply
no fills. Archived receipts omit missing timing/drift fields.

VERIFIED pre-deploy: 29 focused backend tests (1.28s), 33 browser workflows (57.4s),
6 real DeepSeek autopsy tests (117.22s), TypeScript and Vite build.
The browser tests cover independent target expiry, zero versus missing targets,
empty versus unavailable broker history, document review and manual recording.
The final precision change also passed two expiry/percentage browser cases
(6.2s) and TypeScript. Tiny positive weights display <0.1%, not zero.
No broker mutations were performed. FOMC catch-up remains unresolved; restoration
still follows calendar/cash, not a fresh technical all-clear. The UI says so.
Research allocations have no demonstrated superiority in forward net returns.

VERIFIED deployed application checkpoint `17d9f8d9` (backend `a3661769`).
The first deploy was stopped before shipping to include the network-timeout
case; the final normal backend deploy passed 3504 unit tests (19 skipped,
140.16s) and 100 real routing cases (507.65s), then backed up and restarted.
The precision-only deploy used the script's frontend path. Final marker:
`2026-09-14T15:00:18Z 17d9f8d9 ok (cheap)`. No gate was bypassed.
Running market API and broker-adapter hashes exactly match the source.

Public Chrome acceptance: asset `/assets/index-Bz7YdVN7.js`, 18 successful
API responses, all 93 grades, five inflation rows, zero-cash preview, review
HTTP 200 with the no-trading-documents response, known/missing receipt metadata,
current percentages and manual-buy cancellation. No page, console or network
errors. Board content fits on desktop (958/958px) and mobile (1376/1376px);
account width 356/356px. Paper execution showed zero open orders and no fills
for September 14 at the observed snapshot. The prior 10:58 ET public screenshot
also shows actual nonzero research percentages alongside dated nightly analysis.
Temporary credentials were removed from Mac, host and container after acceptance.
Logs: `/tmp/desk-finish-final-deploy.log`, `/tmp/desk-precision-deploy.log`
on Spark; `/private/tmp/desk-precision-public-proof.log` on Mac.

## 2026-09-14 — Compact trading dashboard and FOMC diagnosis

Started clean on `main` at `cce79a11`; pulled origin/main, already current.
The user requested fewer words and clearer decisions. Stock rankings now lead;
actual paper cash and cash implied by scheduled targets are separately labelled.
Setup is one line. Methodology, inflation and performance expand on demand.
"Portfolio plan" replaces "Targets for the next rebalance", with the existing
countdown and execution status retained. Research sizing remains explicit.

VERIFIED before deployment: 30 browser workflows passed (1.2m), TypeScript and
Vite passed. A styled same-fixture before/after comparison measured 811 → 326
visible words (60% fewer) and ranking-heading position 604px → 298px at
1440×1000. The compact test also checks mobile overflow and distinguishes actual
paper cash from target-implied cash. Initial failures were old wording/hidden
performance expectations; the removed footer's countdown was restored in the
plan header so due trades retain their date context.

Live inspection prompted a final row cleanup: unchanged votes no longer repeat
"no change" and an explanation on every stock; one common bar timestamp and
one thesis column label replace repeated row labels. Final settled comparison
(after initial network requests finish) is 934 → 369 visible words, still 60%
fewer, with the same 604px → 298px ranking position. These settled counts
supersede the early-loading counts above. Final full browser run: 30 passed
(1.2m); settled density/cash/mobile workflow: 1 passed (5.5s).

VERIFIED deployed UI checkpoint `d42b1fd0` (initial compact commit `062bd6d6`).
Both shipped through normal `scripts/deploy.sh --wait-post`; frontend-only
selection rebuilt the gateway and ran the cheap post check without rerunning
unchanged backend/model gates. Final marker:
`2026-09-14T14:00:31Z d42b1fd0 ok (cheap)`. Public asset `index-D7Q0e5rY.js`:
17 successful API responses, 93 grades, five inflation rows, zero-cash preview,
cash values loaded, missing FOMC status, source details and manual-buy cancellation
verified. No console/page/network errors. Target content is fully visible on
desktop (934/934px) and mobile (1320/1320px); account width 356/356px. The default
desktop screenshot shows all ten leading names in its first 1100px-high viewport.
Temporary browser credentials and remote diagnostic helpers were removed.
Logs: `/tmp/desk-compact-final-deploy.log` on Spark and
`/private/tmp/desk-compact-final-public-proof.log` on Mac. No trading code or
broker positions changed; the FOMC catch-up gap below remains unresolved.

The user's market observation prompted a read-only exposure audit. At
2026-09-14T13:49:50Z, paper cash was 58.87%, the paper account was down 1.92%
on the day, and the evening weights implied 76.40% cash. These are different
states, not contradictory numbers. Friday's saved record has no `event_risk`;
paper state has no event cycle or outcomes. Replaying the current FOMC policy on
the Friday point-in-time panel returns factor 0.5, with SPY five-session return
-1.1485% and three sessions to the September 16 decision. The policy execution
path is nightly; it was deployed after that stored record. This confirms an
execution/rollout gap, not proof that an order was placed or filled. The UI now
says "FOMC decision missing". No broker mutations were performed in this turn.
**UNRESOLVED:** policy catch-up before the next nightly execution; this UI change
does not execute a missed reduction or alter the strategy. Do not report it fixed.

The research collector did successfully archive its first actual fresh decision
at 13:45:29Z from the 13:30 bar: all 93 grades, building inflation, daily SPY
neutral, weekly positive, 0.5 base budget, no additional macro cut, total targets
23.34%. This resolves the prior fresh-collection uncertainty, not the absence of
forward performance evidence. Diagnosis file: `/private/tmp/desk-market-diagnosis.json`.

## 2026-09-14 — Intraday sizing and macro research

Started clean on main `36cf40f9dbf9a1880fc0597e324b6b1a97c56b4d`;
`git pull --rebase origin main` was already current. Implemented the separate
automatic candidate, immutable decisions, cash preview selector/reductions,
expiry and a forward funded target evaluator. The scheduled broker policy is
unchanged. No broker actions were run manually.

VERIFIED pre-deploy: 51 candidate/storage/evaluation/funding/API/balancer tests
passed (1.40s), 29 dashboard browser tests passed (45.7s), TS/Vite and Ruff passed.
The authenticated API test checks persisted state is unchanged and expired
research requests are rejected. The actual safe research CLI on Spark withheld
Friday prices before Monday's open; both cost arms reported zero observations.
The funded daily-cadence proxy favored the existing holding cadence; see
`research/retail-decision-workflow.md` and its raw JSON artifact.

VERIFIED deployed application checkpoint:
`ddabcd7708719bae682385bb6bbbd06d832f73c5` (implementation `704f7431`, followed by
the observation-gap accounting correction). The first deployment was stopped
during its unit gate to make that correction before shipping. The final normal
`scripts/deploy.sh --wait-post` run passed 3499 unit tests (19 skipped,
140.46s) and 100 real routing cases (483.83s), then backed up, migrated and
rebuilt. Marker: `2026-09-14T13:31:22Z ddabcd77 ok (cheap)`.
Both deployment and cron checkouts carry this application revision; all three
research implementation hashes match the running backend. The final focused
backend run passed 51 tests (1.33s); the last UI wording change passed its
targeted browser workflow (1 passed, 3.7s).

Public Chrome acceptance used actual authenticated responses with all writes
blocked except the read-only cash preview: asset `/assets/index-B5SQJDHt.js`,
20 successful API responses, 93 grades, five inflation rows, zero-cash preview,
research selection/stale-data message and policy-change clearing verified.
No console/page/network errors. Board heights match content on desktop
(1364/1364) and mobile (2618/2618); practice account width 340/340.
The deployed safe CLI also correctly withheld stale Friday inputs during the
unfinished Monday opening candle. No manual broker operations occurred.
Temporary browser credentials were removed from Mac, remote host and container.

UNVERIFIED: a successful current-session research allocation from live completed
prices (first regular candle was not complete at acceptance time), and superior
net returns. The preview is not a validated replacement strategy. Its next
normal collector run can archive fresh decisions without manual broker calls.
Use `backend.cli.evaluate_intraday_research` after observations accumulate;
the target trackers deliberately do not claim to reproduce all scheduled exits.
Logs: `/tmp/desk-intraday-final-deploy.log` on Spark and
`/private/tmp/desk-intraday-public-proof.log` on Mac.

## 2026-09-14 — cash preview and economic evidence

Started clean on main `04c4a0af`, pulled origin main (already current).
Cash preview checkpoint `5d814fa0` is pushed: shared budget, whole-share floors,
existing holdings deducted, no projected sale proceeds or paper cash, explicit
confirmation after context changes. It previews evening targets, not intraday
allocation. New economic context collects five public inflation indexes and uses
the agent-owned economist prompt for a research-only DeepSeek classification.
It archives collection-time evidence; release timestamps/consensus are unknown.

VERIFIED before deployment: 35 backend funding/economics/API tests (1.12s),
28 dashboard browser tests (45.7s), 3 real DeepSeek economist tests (6.71s),
TypeScript, Vite build and Ruff. Real collection and disk readback under
`/tmp/desk-economic-acceptance` on Spark: five series, content hash
`84b838230e3a9f38988155fbcb259edf3ce9996a898274b09c37daf4f685577b`,
observed `2026-09-14T12:28:26.921414+00:00`, model `deepseek-v4-flash`.
Initial model tests exposed unsupported `uniqueItems` grammar (HTTP 400);
deduplication now happens in code. Browser reload fixture required clearing its
nonexistent saved conversation identity; desk storage remains intact in the test.

VERIFIED live application checkpoint: `83a20599d535196d35d88f33dcb91c6b54cead9f`.
Both the deploy and nightly checkouts carry this application revision. The first
deployment attempt was stopped before shipping when the actual nightly host
revealed stale default model settings. `market_daily` now forwards its explicit
model URL/name into economics. Actual host collection with the nightly job's
`--llm-url http://127.0.0.1:8000 --llm-model deepseek-v4-flash` succeeded and wrote
the live snapshot at `2026-09-14T12:36:37.332942+00:00`.

Deployment used `scripts/deploy.sh --wait-post`: 3485 unit tests passed,
19 skipped (137.60s), 100 real routing cases passed (508.51s), backup/migration,
build and restart succeeded. Post-deploy marker:
`2026-09-14T12:49:24Z 83a20599 ok (cheap)`. No gate was bypassed.
Final frontend acceptance: 28 browser tests passed (48.2s), TS/Vite passed.
Real public Chrome session: asset `/assets/index-CGpcYSvF.js`, 20 successful
API responses, 93 grade rows, 5 inflation rows, zero-cash preview cost $0,
zero console/page/network errors. Board content fits its height on desktop
(1637/1637) and mobile (3211/3211); practice account width 340/340.
The public harness allowed GETs plus only the read-only funding-preview POST;
no holdings saves or brokerage orders. Its first read-scope credential was
correctly refused for POST (403), which uses the existing memory:write scope.
Operator-scope rerun passed; the API regression now sets AUTH_REQUIRED=true
and tests the scope rejection explicitly (23 passed, 1.26s). All temporary
credentials were removed from Mac, remote host and backend container.
Funding/economics/economist source hashes match the running backend exactly.
Logs: `/tmp/desk-economic-final-deploy.log` and `/tmp/desk-economist-proof.log`
on Spark; `/private/tmp/desk-economic-public-proof-final.log` and
`/private/tmp/desk-economics-browser-final.log` on Mac.

UNVERIFIED: improvements in returns, economic allocation policy,
dynamic intraday share targets and executable quotes. The
economic assessment intentionally has no effect on sizes or orders. Continue
with the funded comparison in `docs/research/retail-decision-workflow.md` before
promoting a new trading policy. No real brokerage orders were placed.

Verified state as of 2026-09-14. `deep-matter.com` serves from spark1.
Verification labels distinguish observed behavior, source findings and remaining work.

## 2026-09-14 — manual purchases and valuation-model consistency

Started from checkpoint `fb8335d3` on main after pulling and pushing the cash
and clipping fixes. User clarified the desired workflow: current opportunities,
variable share recommendations and manual recording after brokerage execution.
They also asked for macro/bear-market coverage without competing on submillisecond
economic-release reactions. Design and known gaps:
`docs/research/retail-decision-workflow.md`.

FAILED then fixed: a no-price-change test became B instead of A+ because the
intraday plain-value reader replaced the evening expectations-gap valuation.
Both manual-board and all-grade paths now retain the recorded growth-model
valuation. Compatible technical updates continue. The UI identifies the model
from saved provenance and names refreshed inputs. This is a consistency repair,
not implementation of live expectations-gap valuation.

The main rankings now provide Record buy for covered names regardless of the
rebalance schedule. Blank share/price inputs, actual fill date, explicit manual
tracker wording, and saved holdings after reload separate executed positions
from recommendations. Existing positions are preserved and holdings-read failure
disables the action. No live broker orders were submitted in validation.

VERIFIED locally: 26 browser tests passed in 1.7 minutes, including an off-schedule
buy outside the target book, preserved other holdings and persistence after
reload. Market/trading suite: 487 passed, 8 skipped in 6.87s. Two real ASGI HTTP
cases against temporary persisted records passed in 1.51s, covering plain and
growth-model decisions. TypeScript, Vite build and Ruff passed.
Four focused browser checks passed after the final wording changes in 30.7s.
Final real-DeepSeek run on the matching test image: 13 passed, 1 xpassed in
165.70s. The XPASS is the intermittently failing repeatability assertion, not
evidence that repeatability is fixed. Runtime hashes of the narrator, both
changed prompts and the release test matched the checkout.

VERIFIED checkpoint `a76976a18641d74bfa41960d0f57bbc5a00314d5` deployed through
`scripts/deploy.sh --wait-post`, exit zero: 3472 unit tests passed, 19 skipped
in 156.55s; 100 real-model routing tests passed in 497.43s. Post marker:
`2026-09-14T04:05:18Z a76976a1 ok (cheap)`. The preceding cash checkpoint
`fb8335d3` also deployed with 3470 unit passes, 19 skips and 100 routing passes.
Live holdings and simulator hashes match the tested source and funding report.

Authenticated public browser on `/assets/index-BVtAeYHD.js`: top ten and all 93
grades, ranking methodology, manual-buy form open/cancel, all expanded theses,
receipts and AAOI history/earnings/technical read exercised with real GETs.
Nineteen API responses succeeded; zero browser/network errors. Target section
content/height: desktop 1153/1153, mobile 2299/2299; no vertical clipping.
Practice-account mobile content/width: 340/340. No position write or broker
order was performed in the public check; fixture tests prove write/reload flow.

That word audit found historical model prose incorrectly attributing position
size caps to participation and correlation warnings. A frontend follow-up now
leads with recorded analyst evidence and moves old model interpretations behind
an explicit, closed-by-default unverified archive control. The original records
are preserved. All 26 browser tests passed on the final tree in 39.0s, including
opening the archive; TypeScript and Vite passed. An earlier run overlapped a
layout edit and lost one dialog; the unchanged-tree rerun passed.
VERIFIED presentation checkpoint `f6b4cddf`, deployed by the script's normal
frontend-only path (TypeScript/build and post-deploy smoke, no backend change).
Marker: `2026-09-14T04:11:27Z f6b4cddf ok (cheap)`. Public asset
`/assets/index-cw7YwHWm.js` passed the same authenticated 93-grade workflow,
including opening the unverified archives: 19 API successes, zero errors,
unchanged unclipped section dimensions. Desktop/mobile screenshots were inspected.
Cron checkout `~/anios` was clean and fast-forwarded to `f6b4cddf`. All temporary
browser-token files were removed from the Mac, remote host and backend container.
No manual holdings or broker orders were changed during public acceptance.

UNVERIFIED/unimplemented: CPI/PPI/PCE allocation inputs, macro observation age
limits and missing-yield status, a validated intraday allocation/entry policy,
real-account available-cash tracking, and superior future net returns. The code
does not support claiming these are already done. Temperature-zero DeepSeek
release-score repeatability remains an evidenced functional xfail.

## 2026-09-13 — dashboard evidence and expiry audit

Follow-up checkpoint in progress: cash-at-fill-v1 funds buys from cash available
at their execution time, never a later closing sale. FOMC restoration records
an unaffordable remainder and releases the ordinary rebalance after settlement.
VERIFIED: 486 market/trading tests passed, 8 skipped; the former funding xfail
now passes. Frozen-input comparison and source hashes are in
`docs/research/cash-funding-audit-2026-09-13.md`: negative cash falls from
220/1429 sessions to zero; maximum gross exposure falls from 131.79% to 100%.
Historical total return also falls, as the old record benefited from borrowing.
Existing saved curves retain their legacy warning until genuinely recomputed.

FAILED then fixed: the target board's 284-pixel contents were clipped inside
a 32-pixel flex item. Sections now retain their content height. Rankings are
visible in the main view, top ten with an expand-all control and dated IEX bars.
VERIFIED: 24 browser regressions passed in 1.5 minutes, including clipping,
grade expiry, record-fill persistence and the cash-limited FOMC outcome.

DeepSeek validation now requires affirmative consistency votes before a brief
can be published. Five real-model brief tests passed; the final live-read prompt
passed two tests after removing a numerical example the model copied into its
answer. FAILED: release-tone repeated scores differed (1.0 versus 0.8) at
temperature zero; its property assertion remains as an evidenced xfail.
The initial combined functional run had 14 passes and that one failure. This is bounded evidence,
not proof that every generated claim is correct. These changes are not yet live.

User's next requested workflow: prominent current opportunities with changing
recommended share counts, then a manual Record buy after an actual brokerage
fill. Current implementation does not offer a validated intraday buy-now policy:
only technical/value grades update intraday; allocations remain evening targets.
Analyst weights are F/T/S/V=1 each, rotation=0.5; bearish core votes cap at B.
LightGBM predicts revenue growth and blends its expectations gap into valuation;
it does not directly predict a target share price. Preserve that distinction.

Started clean on `main` at `f82b5e4b`; origin was already current. Objective:
make displayed grades, prices, allocation instructions and performance labels
match their dated evidence before further timing research. Acceptance includes
expiry on an open page, completed bars only, correct decision association,
explicit target/fill distinction, browser interactions and deployed checks.

FAILED then fixed: an intraday grade stayed current indefinitely in an open
page; a forming/future candle could set the displayed price and grade. The API
now publishes per-stock expiry deadlines, the client preserves them and returns
to the evening grade at expiry, and both quote ingestion and grade eligibility
exclude unfinished bars. The board re-sorts when grades expire.

VERIFIED locally: 21 browser cases passed in 1.3 minutes (fixtures; includes
expiry, decision mismatch, fill persistence, details, earnings and FOMC);
480 market/trading tests passed, 8 skipped, 1 expected funding failure in 5.14s.
TypeScript, Vite production build and Ruff passed. Cron inspected on the EDT
host: intraday `*/15 9-16 * * 1-5`, evening `30 19 * * 1-5`. A scheduled run is
not a guarantee of fresh evidence. The browser now polls every minute.

Wording distinguishes session from publication, target move from entry/fill,
IEX bars from broker marks, and broker day P/L from calendar-day returns.
Initial grade sizing multipliers no longer claim to be final allocations.
Legacy simulation figures explicitly disclose unmodeled borrowing, and dated
model commentary is not presented as verified current trade instruction.
VERIFIED deployment of `3c7ebb8d` through `scripts/deploy.sh --wait-post`, exit
zero. Full unit gate: 3464 passed, 19 skipped, 1 known funding xfail in 148.49s;
real-model routing: 100 passed in 513.29s. Post marker:
`2026-09-14T03:20:13Z 3c7ebb8d ok (cheap)`.
Authenticated public browser: `/assets/index-BbcQG98q.js`, 93 grades, help,
receipts, AAOI details/earnings, 19 successful API responses, zero browser or
network errors, mobile content 340/340 pixels. Real read-only GETs, no fixtures,
no broker orders; all temporary tokens removed. This verifies the current UI,
not every factual assertion in old generated commentary.
Forecast accuracy, best-possible grades and improved future returns remain
UNVERIFIED. Cash-constrained simulation is the next approved atomic fix.

## 2026-09-13 — durable execution timing and honest receipt display

Started clean on `main` at `4490ee0a`, pulled/rebased origin (already current).
Reproduced two failures: reconciliation discarded broker timestamps, and a
delayed fill was compared with the close after its plan instead of its actual
completion date. Fixed both without changing trade selection or order sizing.

Pending intent now stores decision time, reference price, source and session
before submission. Broker acknowledgments and reconciled outcomes preserve
allowlisted timestamps through partial fills and restarts. The journal remains
one latest receipt per client order ID. Missing legacy timing remains unknown.
Comparison dates use exchange time and the broker's order completion date;
aggregate fill prices are not claimed to timestamp each partial execution.
Decision-price drift is positive when adverse and is not quote-based slippage.

Dashboard details expose receipts, exact times to the second, reference prices,
and missing-evidence labels. Historical submissions no longer claim to be
waiting at the open; planned rebalances no longer claim completed resizing.

VERIFIED before deployment: **477 market/trading tests passed, 8 skipped**
in 5.22s; **19 browser cases passed** in 49.6s; TypeScript, Vite build and Ruff
passed. Actual read-only broker acceptance reconciled **34 orders / 24 filled**
into a disposable state file and read all 34 back. All 24 fills used their
recorded completion dates. Old decision-price references stayed unknown.
No live paper state or broker order was modified by that check. The first
isolated run lacked prompt files; copying the matching prompts resolved the
environment failure. Runtime evidence is `/tmp/desk-execution-proof.json` in
the backend container, with SHA-256 hashes of all three production modules.

VERIFIED checkpoint `c43a1a382499ca4fa92bf121957fa080e2b413f4`: deployed through
`scripts/deploy.sh --wait-post`, exit zero. Full unit gate **3461 passed,
19 skipped, 82 warnings in 142.28s**; real-model routing **100 passed in
496.61s**. Marker: `2026-09-14T02:21:54Z c43a1a38 ok (cheap)`.
The deployed modules' hashes match the pre-deploy real-broker proof, which was
repeated successfully against `/app` in the new container (34 receipts, 24 fills).

VERIFIED authenticated public browser acceptance: asset
`/assets/index-1V3qTuNK.js`; real identity and API responses using a short-lived
read-only bearer, no response fixtures. All 93 grades, the receipt section,
AAOI history/technical/earnings requests and mobile layout passed. Fifteen API
responses were HTTP 200; zero page/console/network errors; practice-account
content 340/340 pixels on mobile. No account writes or broker orders occurred.
Temporary credentials were removed. Browser evidence is retained locally in
`/private/tmp/desk-authenticated-{desktop,mobile}.png` and
`/private/tmp/desk-authenticated-copy.txt`. This proves authenticated reading,
not the password-login workflow or future execution of newly planned orders.

**Next priority — FAILED cash-only funding constraint:** a minimal current
simulator fill spends $120.12 from $100. The unchanged 2021–September 11, 2026
current-policy replay ended with negative cash on **220/1429 sessions** and
maximum gross exposure **131.7917% of equity**, without financing costs.
The strict expected-failure regression in `test_trading_execution_funding.py`
keeps the defect visible (1 xfailed in 0.12s). The new test and evaluation plan
do not change production behavior and were added after the deployed checkpoint.
See [next evaluation protocol](research/technical-timing-next-evaluation.md).
Resolve and measure funding before promoting technical exit/re-entry rules;
the existing simulation must not be represented as cash-constrained performance.
Future return improvement remains UNVERIFIED.

## 2026-09-13 — audit actual pick publication, fills and technical timing

Research checkpoint `24c4f3db2340990299d4d3d38617d6593962aad7` is pushed.
Its evaluator file hashes match the isolated runtime artifact recorded in the
report; nine focused tests passed in 0.12s and Ruff passed. The read-only
acceptance path fetched saved grades, SIP candles and broker receipts without
submitting orders. This is a verified research checkpoint, not a claim that
the experimental timing rules improve funded live returns.

Read-only `market_pick_audit` evaluates saved grades, never regenerating the
past with current code. Five records, 34 A+ observations, 11 distinct names;
ten have post-publication prices. Five of ten rose from the first tradable
open to September 11. Mean +0.67% before costs, median −0.40%; matched SPY
−0.23%. Saturday's September 11 record has no forward outcome by the cutoff.

Fetched 22,616 historical SIP bars including warmup, with no unavailable names,
and 34 broker receipts. HPE's 201-share buy expired, missing its subsequent
18.74% move. AAOI filled Friday at 9:33:06 after a sharp opening move. NTAP's
Friday trim preceded a recovery; SMCI's later re-entry improved its outcome.
See [full audit](research/pick-timing-audit-2026-09-13.md) and companion JSON.

The user clarified that timing should depend on technical structure, not fixed
profit numbers. Added research-only daily/hourly/15-minute comparisons using
EMA21/50 trend alignment, EMA9/21 pullback recovery, prior-day-high retests,
Bollinger rejection, and confirmed EMA failure. Only completed candles enter
signals; fills use the following bar. Nine tests passed, including no future
repainting and unfinished-hour exclusion. These specific variants underperformed
the simple entry/hold comparison in this short sample and were not promoted.
They are per-position diagnostics, not funded portfolio simulations, and have
no re-entry after full exits. Next work needs re-entry/funding and an untouched
forward sample before changing live technical execution.

Production follow-ups supported by the audit: persist publication/submission/
fill timestamps together, measure opening drift against a named feed/quote,
and make allocation/entry eligibility distinct from the A+ selection grade.
The new research CLI runs from an isolated source tree against read-only data;
it is not a new live job and creates no orders.

## 2026-09-13 — FOMC deployment verified

Frontend follow-up `f13cbcfa` also deployed through the script, exit 0;
post marker `2026-09-14T01:53:26Z f13cbcfa ok (cheap)`. Public asset
`/assets/index-CtXHAenQ.js` passed the same 93-grade/AAOI/mobile browser replay
with zero errors. Two focused FOMC browser tests passed in 7.1s. The final
wording says orders are queued for the open and actual fills can differ.
The backend image remains the fully gated `84d07faf` implementation below.

Verified checkpoint `84d07faf`: deployed through `scripts/deploy.sh --wait-post`,
exit 0. Full unit gate **3450 passed, 19 skipped, 82 warnings in 141.85s**;
real-model routing **100 passed in 482.00s**. Post marker:
`2026-09-14T01:31:47Z 84d07faf ok (cheap)`. The cron checkout was fast-forwarded
to the same revision. No production broker order was used for testing.

The deployed policy reads September 11 SPY five-session return **−1.1485%**, a
known September 16 decision three sessions away, and requested factor **0.5**.
This is a verified decision, not a submitted or filled reduction. The next
scheduled daily job invokes the new paper lifecycle. No old record was rewritten.

The public API reports the enabled policy. Browser replay of public asset
`/assets/index-BD0xdKy0.js` shows the FOMC notice, 93 grades and AAOI's drawer;
zero page/console/network errors, mobile content 340/340 pixels. The replay
uses captured production GET responses and a mocked operator session; fully
authenticated browser acceptance remains unverified.

## 2026-09-13 — adopt provisional FOMC execution and separate evaluation eras

The user explicitly chose the three-session conditional de-risking policy and
asked to judge the post-guidance period separately. This supersedes the prior
decision below to leave automatic FOMC changes disabled.

Implemented `fomc-3-session-weakness/1`: negative five-session SPY performance
inside the window triggers a one-time 50% reduction of held shares. The signal
latches through decision day. Event sells bypass ordinary close/green-day rules.
Confirmed event fills alone authorize restoration, bounded by snapshot shares
and cash; failed/partial legs retry remaining quantities. Pending cancellations
block replacement. A cycle defers ordinary rebalances while their clock continues.
State writes are atomic, journal receipts retain event IDs, and legacy state loads.

The nightly simulation and scorecard use the same deferred-rebalance lifecycle,
with the overlay effective from June 18 for current-policy replay. `market_fomc
--selected` additionally stress-tests that lifecycle across older meetings.
The old scale-only research results below are a different execution variant.
Evaluation periods now partition a continuous account at the June 17 close;
they do not restart the account or rebalance clock at the regime boundary.

VERIFIED before final gate: market/trading suite 465 passed, 8 skipped;
18 browser cases passed in 50.9s; TypeScript and production build passed.
The new pipeline fixture reads pending intent from disk before broker submission
and confirms fills through the real settlement code. No real broker orders were
used for tests. Four selected-lifecycle research comparisons completed on pinned
September 11 inputs: June 18 inception, 10 bp costs, baseline -0.234% vs candidate
+1.522%, maximum drawdown 10.591% vs 7.293%. At 25 bp: -0.359% vs +1.298%.
One completed meeting plus September's incomplete lead-in is not conclusive.

UNVERIFIED until deployment: production execution and the public dashboard.
Enabled configuration takes effect on the next nightly run; old records are
not rewritten and do not prove a cut. Manual holdings have no event fill ledger:
the dashboard explicitly limits automation to paper, and withholds ordinary
target execution during active cycles. No automatic real-money orders are added.

Next requested investigation: audit every stored A+ pick from the last week
against its actual publication timestamp, subsequent daily/intraday prices and
broker fills. Distinguish selection, blocked entries, rebalance delay and fills.
Records exist Sep 4, 8, 9, 10, 11; the first three lack source revisions.
Do not use a grade's session close as an executable price when publication was later.

## 2026-09-13 — final dashboard deployment and FOMC evaluation

VERIFIED deployment: `e0b53de0`, through `scripts/deploy.sh --wait-post`, exit 0.
Unit gate **3439 passed, 19 skipped, 82 warnings in 141.87s**; real-model
routing gate **100 passed in 507.30s**. Marker:
`2026-09-14T00:53:20Z e0b53de0 ok (cheap)`. The deployed calendar and simulator
hashes match their source. Container probe returns `[5,4,3]` to September 16
and `[30,30,30]` to December 16 for September 9–11.

VERIFIED dashboard: public asset `/assets/index-B05YbQv6.js` renders 93 grades
and AAOI's drawer with captured production GET responses, no page/console/
network errors, and mobile content contained at 340/340 pixels. Operator
session is mocked in this replay; authenticated production browser behavior
remains UNVERIFIED. Confirmed-fill interactions and reload persistence passed
the 16-case local browser suite with a stateful API fixture, including partial
sells; a later oversized-sell assertion also passed. No real account writes
or orders were used for verification.

VERIFIED research: both pinned runs completed at source `35ebc0f9`, whose CLI,
event module and simulator hashes match the executed files. **48 unique
comparisons**, four windows, two trigger variants, two cost assumptions, and
three inception dates. See [full result and assumptions](research/fomc-window-evaluation-2026-09-13.md)
and the accompanying JSON. The asof-bound CLI is committed and was run from
the isolated research checkout; it is newer than the deployed backend image.
The dashboard source is identical in `e0b53de0` and `35ebc0f9`.

Judgment: the three-session conditional candidate improved the May 22–Sep 11
return by 0.35 pp at 10 bp costs and 0.25 pp at 25 bp, with a shallower
drawdown, but reduced return over 2021–2026. There are only two completed
meetings under Warsh, or one after the June guidance announcement. This is
not sufficient evidence of a superior automatic trading rule. Live FOMC
order execution is not enabled. No previous historical decision was rewritten.

Still open: publish corrected earnings only after resolving source/basis
validation; actual-model grade-change explanations need structural checks;
broader asof propagation and remaining same-candle retry/coverage gaps; a
proper fill ledger and live FOMC lifecycle would need additional implementation
and forward validation. The dashboard is improved and live, not perfect.

## 2026-09-13 — pin every FOMC research input to the requested date

The desk passes `asof` to its primary loaders, but the nested expectations-gap
loader omits it. Added a research-store boundary that bounds both bar and
generic-frame lookups even when nested readers ask for latest. Regression
test writes an earlier and later tone partition, then proves both an omitted
and a too-late asof return the earlier value. Six event-risk tests pass in
0.30s, Ruff passes. The first 32-case output was exploratory and unpinned;
do not cite it as a September 11 snapshot. The pinned rerun is in progress.
This change is isolated to the research CLI; existing live loaders are not
changed, and their broader asof propagation remains an audit follow-up.

## 2026-09-13 — configurable FOMC research overlay

The user clarified that a selloff can begin any number of days before FOMC
and wants the strategy to account for it. Added `market_fomc`: a read-only
comparison of predeclared 1/3/5/10-session windows, 50% temporary exposure,
and unconditional versus negative-five-session-SPY variants. Weakness
latches until the event to avoid repeated trades on one-day rebounds.
Exposure is decided at a close and changes at the next open; the window
covers the specified pre-meeting sessions plus the decision session, then
restores at the following open. Event changes explicitly execute even on
a green open, with normal LIVE_POLICY behavior for other orders. The
existing simulator charges actual traded notional and preserves partial
positions; the scale is applied relatively between rebalances so it cannot
halve the book anew every day.

Research defaults to 2021 onward. The older calendar includes emergency 2020
actions and lacks point-in-time cancellation metadata, so using it for a
pre-event strategy would be lookahead. Each `since` starts a new cash account;
the post-June-17 slice is separate, with only one completed meeting as of
September 11. All variants are shown at 10 and 25 bp costs, not just a winner.
Current-universe and revised-input limitations remain explicit. There is no
live planner import or enabled exposure rule.

VERIFIED: market/trading suite 454 passed, 8 skipped in 6.51s before adding
the neutral-overlay invariant; the five event-risk tests also pass, including
exact equality to LIVE_POLICY when the scale stays at one. Ruff passes.
The actual 32-case comparison is running on the immutable September 11 input
cut; runtime results and profitable strategy qualification remain UNVERIFIED.
Command: `python -m backend.cli.market_fomc --asof 2026-09-11`.

Confirmed-fill checkpoint `55670719` pushed. Browser suite 16 passed; the
additional oversized partial-sell check passed in 4.9s. Public-asset replay
of earnings checkpoint `c68fb498` rendered 93 grade rows and AAOI details,
zero browser/network errors, mobile width 340/340. It uses captured real
GET responses with a mocked session and no account writes; it does not prove
an authenticated production browser session. Latest fill deployment pending.

## 2026-09-13 — confirmed fills instead of estimated "done" positions

The dashboard previously updated positions at its suggested quantity and
displayed price when a person said an order was placed, including deleting
the entire holding for a sell. It now requires actual filled shares and
average price in a blank form, makes no write on opening, retains partial
sells, rejects selling more shares than recorded, and preserves average-cost
precision on adds. The help and footer distinguish intended execution timing
from actual broker fills. Holdings-read failures now block editing rather
than allowing an unread account to be overwritten as an empty one.

VERIFIED: 16 dashboard browser cases passed in 40.1s, including add and
partial-sell persistence after reload and unavailable holdings; TypeScript
and production build pass. Persistence in these browser cases uses the
existing API contract with a stateful fixture, not writes to the user's
account. No broker order was placed. This remains manual position tracking,
not a broker-synchronized, idempotent fill ledger. Deployment pending.

## 2026-09-13 — FOMC boundary correction (after `c68fb498`)

The incoming implementation mapped every future decision to `len(panel)`;
September 16 and December 16 therefore both appeared one session after
September 11. Four acceptance cases failed against `5d05adfb`. Future
distances now count published NYSE sessions, excluding full-session holidays
and retaining early closes. The official 2026–2028 calendar is committed with
its source and bounded coverage; outside that coverage distance is unknown,
not an invented one-session warning. A decision before the first observed
session no longer becomes a false decision day at the panel's start.

VERIFIED: market/trading suite **450 passed, 8 skipped, 23 warnings in 4.82s**
against the candidate mounted in the functional-tests image; Ruff passes.
September 9–11 distances are `[5, 4, 3]` to September 16, versus `[30, 30, 30]`
to December 16. Thanksgiving and Good Friday cases pass. Deployment pending.
This corrects the calendar features; it does not add an FOMC exposure rule.
Historical research must still distinguish complete meetings from individual
days or names and test transaction costs before promoting a new strategy.

Earnings panel checkpoint `c68fb498` deployed through `scripts/deploy.sh
--wait-post` with exit 0. Its exact frontend passed 14 browser cases and the
production build. Production browser replay remains to be repeated.

## 2026-09-13 — earnings-panel evidence correction (after `5d05adfb`)

Started clean on main `5d05adfb` after pulling opencode's earnings panel.
The reaction date is an earliest date, potentially on a weekend after an
after-hours filing; it does not prove the release was published that day.
The panel now says "Market reaction on or after" with the full date and year.
Tone labels describe the stored scores, including zero's neutral-or-unstated
ambiguity, instead of claiming every positive outlook was raised. Financials
retain signed dollar precision and the exact quarter-end date. Known v2
loss-sign defects make those legacy financials unsuitable for display; they
are withheld pending corrected extraction. The reader version is visible.
Errors, no stored release, and loading are distinct, with a working retry and
15-minute refresh while the drill-down stays open.

VERIFIED: 14 browser tests passed in 39.0 seconds against the current main
checkout's Vite server on port 5187 with deterministic API fixtures; includes
legacy suppression, signed figures and failed-request recovery. TypeScript
and production Vite build pass. No prompt or strategy rule changed here.
Deployment pending. The original three new acceptance cases failed against
the incoming panel; the two sequential-response fixtures were then corrected
to tolerate React StrictMode's duplicate mount reads.

FOMC clarification: current main and the Spark research checkout both remain
at `5d05adfb` before these corrections. `regime.py` explicitly leaves calendar
effects out of position sizing. Opencode's entry below records the backtest
and says automatic FOMC de-risking was not adopted. The user's hypothesis is
being reviewed; the calendar boundary correction is a separate checkpoint.
Staging earnings rebuild is complete and UNPUBLISHED, not still running as
the older opencode entries say. Its 93-company completion was verified above.

## 2026-09-13 — dashboard caption accuracy (candidate after `6f9baa70`)

Objective: align captions with their data without changing trading decisions.
Started with clean main `6f9baa70`; its technical-text deployment is running.
Participation now describes trading activity rather than the number of rising
stocks; the exposure multiplier is a target rather than a claim about filled
positions. Paper positions are identified as practice positions and their
fetch timestamps include date and ET. Per-share prices retain cents.
Hypothetical stops explicitly remain inactive even when breached. Chart
timeframes no longer imply forecast horizons, stale candle ranks do not say
"now", empty states do not promise an overnight run, and missing historical
causality is not invented as a size cut. The S legend names earnings-release
tone; zero remains explicitly neutral-or-unavailable until coverage is separate.

VERIFIED: **11 desk browser tests passed in 17.5 seconds** against this checkout's
Vite server on port 5187 with deterministic API fixtures, including stop breach
and price precision. TypeScript and production Vite build pass (existing CSS
and large-chunk warnings). No prompt, strategy or execution rule changed.
Caption deployment pending; real authenticated browser session unverified.

Earnings staging integrity verified read-only: **93 frames, 3403 records,
3435 considered events, 32 without text**, every record v3, no duplicate
accessions or nonfinite financial values; known AAOI net loss **-22.8 million**.
There are 679 negative net-income values, including **574 positive-to-negative
changes** versus production. Production still reports **93 v2 frames**.
This is not proof of every extraction's semantic accuracy. Staging remains
unpublished; source-check more changed figures before promoting a new partition.

## 2026-09-13 — follow-up audit of `98785fb3`; technical text correction (candidate)

Started on clean main `98785fb3` after pulling the other operator's changes.
Preserved the initial regression-test patch outside the checkout at
`/private/tmp/desk-review-regressions-d220.patch`. Confirmed the deployed source
matches the incoming technical module and post-deploy marker
`2026-09-13T22:04:18Z 98785fb3 ok (cheap)`.

The incoming changes fixed log-percent conversion, resistance direction,
history labels, mobile table containment and premature done buttons. They did
not finish the audit. A deployed probe with price 100, support 80 and resistance
125 still read "20% above support" and "25% below resistance", using price as
the denominator while wording implied the level. The net EMA-stack count -1
was still described as one falling pair rather than two.

This candidate describes the level relative to price, preserves the simple
distance denominator, counts EMA pairs correctly, and names the 21-week average
in weeks. The incoming log conversion remains. No grading/execution rule or
prompt changed. VERIFIED: market/trading suite **445 passed, 8 skipped**;
real-model technical-read tests **2 passed in 32.91 seconds**, including the
actual feature formatter path; Ruff passes. Deployment is pending.

FAILED incoming calendar boundary: on a panel ending September 11,
`_fomc_distances` reports the same `[3, 2, 1]` distance for a September 16
meeting and a December 16 meeting. Keeping every future meeting at the array's
end makes any future meeting appear one session away. The incoming test pins
that wrong result. Calendar remains context-only; fix separately with actual
future session dates and a far-future negative case.

Earnings staging rebuild FINISHED: all **93 companies**, `failed={}`, reader
`release_tone/3`; result still says `production_published=false`. Validate
staging coverage and signed values before promotion. Historical decisions and
partitions must remain immutable. The process is no longer running.

## 2026-09-13 (opencode) — desk number fixes, an upcoming-FOMC visibility fix, and the earnings/FOMC backtests (DEPLOYED `29b579d3`, contains `bd486cb` + `29b579d`)

Fixes the trading-desk defects the codex review listed (the user asked me to
implement them), all committed on `main`, plus one real defect found by the
backtest. Deployed and VERIFIED end to end.

- **`bd486cb` — displayed numbers and level wording.** `_pct_word`
  (`backend/market/live_technical.py`) rendered `100·log(close/high)` as a
  percent (AAOI −0.796 → "79.6%" when the real drawdown is 54.9%); it now
  converts the log move to an arithmetic percent. `_level_lines` reversed the
  resistance direction (`levels.py:113` computes
  `resistance_distance=(resistance−close)/close`); each side now names its
  level correctly (a resistance above the price reads "below nearest
  resistance"). DeskPanel history labels read "Annualized mean while an A/not"
  and "Position changes" (the old labels described size changes and called a
  mean-daily-log×252 an annualized rule return); EveryGrade table gets an
  overflow wrapper (the whitespace-nowrap analysts column overflowed mobile);
  the "done" button is gated on `rebalance_due`, so a non-rebalance day reads
  "Targets for the next rebalance" without trade buttons. Pinned by
  `backend/tests/test_market_live_technical.py` + updated `e2e/desk.spec.ts`.
- **`29b579d` — the desk can see an upcoming FOMC meeting beyond the panel.**
  `calendar._fomc_distances` dropped any decision whose date fell past the
  panel's last session, so the sessions before the September 16 2026 meeting
  read "none within 30 sessions" and its pre-window flag never fired. The
  future decision is now kept as a mark at position `len(dates)`; the
  pre-window sessions read sessions-to-go 1..3 and flag correctly, and no
  session is mistaken for the future decision day. Pinned by
  `test_an_upcoming_meeting_beyond_the_panel_still_flags_the_pre_window`.
- **Backtest Q1 (FOMC selloff).** The policy change is real: Kevin Warsh's
  first FOMC meeting as chair was 2026-06-17, where forward guidance was
  scrapped ("forward guidance isn't the business we should be in"). Only one
  complete no-guidance cycle exists (2026-07-29): book pre-window
  −2.84/−0.16/−2.82%, decision day −4.02% (SPY flat pre-window, −1.55% on the
  day). Current Sept 16 pre-window (Sep 8–11): book 3-day cum −0.92%, SPY
  −0.22%. Full-history (2015–2026, 282 pre sessions): book pre-window −6.06%
  ann vs +26.53% ann overall; going flat pre-window has lost money recently.
  **n is too small to wire de-risk** — the regime entry's "FOMC context only,
  never changes a size" stays; re-measure after a few more meetings.
- **Backtest Q2 (earnings timing).** 3402 scored releases: bullish tone
  (guidance+demand+pricing ≥ 1, n=1746) beta-adj forward 1s +0.14% (t=1.6),
  5s +0.37% (t=2.2), 10s +0.67% (t=3.0), 20s +1.27% (t=4.4); neutral ~0;
  bearish (n=107) −0.36% 1s. **Edge is NOT front-loaded → intraday is not
  supported by the data**, so no intraday earnings change per the user's
  decision rule. The nightly grade update (next close) is the right hook.
- **Verification.** Backend 111 tests passed (calendar + live_technical +
  market/desk suites); `tsc` clean. E2E gap found and closed: the live
  `anios_frontend` dev server mounts the **deploy clone** (`~/deploy/anios`),
  not the workspace, so the first e2e run hit stale code (2 failures that were
  not regressions). After deploying, the desk suite passed **10/10** against
  the real system via `mcr.microsoft.com/playwright:v1.61.1-noble`
  (host `frontend` mounted, `--network host`, `PUPPETEER_SKIP_DOWNLOAD=true`).
  Deployed `29b579d3` from `~/deploy/anios`; post-deploy
  `2026-09-13T21:54:40Z 29b579d3 ok (cheap)` — search/router surfaces
  untouched, so the credit-consuming sweep correctly did not run; gateway 401,
  `/health` 200. Workspace HEAD == origin/main == `29b579d3`, tree clean.

**Next atomic task.** The backtest says intraday earnings is not worth
implementing; the remaining user-facing "I need to know" is surfacing a
same-day earnings read in the desk view (name drops an 8-K → show the release
reader's tone + financials the same day, ahead of the next-night grade). Not
started. The codex earnings rebuild (PID 1561834, `/tmp/desk-tone-rebuild-20260913.py`,
staging store `data/market-tone-v3-20260913`, ~5/93 companies) is still
running and remains theirs.

## 2026-09-13 (opencode) — same-day earnings read in the desk drill-down (DEPLOYED `141f5a43`, contains `3d5f5db` + `83fe9d0` + `141f5a4`)

Built the pending user-facing item above: the desk drill-down now shows a
name's newest earnings release read the day an 8-K lands, ahead of the next
nightly grade. `GET /market/{user}/desk/earnings/{symbol}` reads the newest
`edgar_tone` frame from the store the release reader writes (no new model
call, no analyst-consensus comparison — only what the release itself said)
and returns the tone (guidance / demand / pricing / capex), the numbers
(revenue, EPS, net income, gross margin, quarter end), the stored model
summary, and a `same_day` flag (reaction date == today in America/New_York).
`DeskPanel`'s `EarningsRead` renders the block in `NameDetail` with a
"released today" marker; `read: null` hides it.

VERIFIED: backend desk suite 21 passed (2 new: read reaches the drill-down,
no-release answers None); the combined tree with the other agent's `405943d`
(desk captions) and `6f9baa7` (technical denominators) rebased cleanly and
passes. Deployed 3 times: `3d5f5db`'s gateway build failed on a real TS parse
error my first "tsc clean" missed — the frontend dev container mounts the
deploy clone, so that tsc had checked the stale copy; the workspace copy has
no such blind spot (`const facts = ([` left the leading paren unclosed;
fixed in `83fe9d0`). E2E gap: `NameDetail`'s new fetch without a fixture hit
the real backend and logged a CORS console error that failed two tests; a
`desk/earnings/*` wildcard (read: null) covers every name, the AAPL route
overrides it. Desk browser suite **12 passed** against the deployed system
via the Playwright noble image. Live: the gateway answers 401 on
`/desk/earnings/ORCL` (protected, routed); the backend reads the real ORCL
frame (2026-09-11, guidance 1.0, demand 1.0, rev 19345M, EPS 1.56, NI 4679M).
Public gateway bundle `index-D17iAH4N.js` contains "Latest earnings read";
post-deploy `2026-09-13T23:57:26Z 141f5a43 ok (cheap)`. Workspace HEAD ==
origin/main == deploy clone == `141f5a4`, tree clean.

The codex earnings rebuild (PID 1561834, `/tmp/desk-tone-rebuild-20260913.py`,
staging store `data/market-tone-v3-20260913`, ~5/93 companies) is still
running and remains theirs.

## 2026-09-13 — explain intraday vote changes (deployed `6525f8d3`)

Starting branch `codex/desk-live-provenance`, HEAD `e98701da`; only the local
node_modules symlink was untracked. Every grade now shows observed vote
transitions against evening votes, labels the evening thesis, and explains
that analyst ranks are not probabilities of profit. Missing votes are not
interpreted as neutral. No grading or execution rules changed.

VERIFIED in this source tree: desk browser suite **10 passed** (41.7 seconds),
including the MSFT technical-vote transition, thesis label and rank explanation;
TypeScript and production Vite build passed. Existing CSS and chunk-size build
warnings remain. Deployment VERIFIED through `scripts/deploy.sh`'s automatic
frontend-only path; post-deploy marker
`2026-09-13T14:37:15Z 6525f8d3 ok (cheap)`. Gateway image
`sha256:b5c3f5c13bd49f98ab5b56b2acee3c637efa6f8e955a746044a716dec43419c2`
contains the new wording. The public gateway serves `index-CRB2_6CV.js`
(SHA256 `f8c3d597eee71c7bb575ffeec843f8e6e59144fabf08c571322dd3a1cbe4aa2a`).
Authenticated production browser acceptance remains UNVERIFIED; UI proof is
the automated local browser workflow against deterministic API fixtures.
Staging rebuild progress at this checkpoint: 2/93 companies complete
(AAOI 55 filings, AAPL 48); PID 1561834 is running, not paused.

## 2026-09-13 — earnings refresh version and retry boundaries (deployed `e98701da`)

Deployment VERIFIED through `scripts/deploy.sh`: 3421 unit tests passed,
19 skipped; all 100 real-model gate tests passed on retry. The first attempt
failed three routing/trajectory cases, including a model timeout and a Scout
floor miss; no floors or unrelated router code were changed. The staging
earnings rebuild was paused during the retry to remove our competing load.
Public gateway acceptance and deployed module hashes match `e98701da`;
post-deploy marker: `2026-09-13T14:34:32Z e98701da ok (cheap)`.
The separate host-cron checkout `~/anios` was fast-forwarded to this revision.

The staging rebuild was RESUMED after deployment. PID 1561834 on spark1 runs
`/tmp/desk-tone-rebuild-20260913.py`; log
`/tmp/desk-tone-rebuild-20260913.log`; staging store
`/home/animallya96/anios/data/market-tone-v3-20260913`.
It does not publish to production. Validate coverage, failures and record
versions before promotion; preserve historical decisions and partitions.
At resume only AAOI had completed (55 scored filings); the 93-name repair is
still IN PROGRESS, and corrected production-wide inputs remain UNVERIFIED.

Starting checkpoint `f131d35d`, isolated `codex/desk-live-provenance`; only the
local node_modules symlink was untracked. Objective: prevent old cached earnings
results being relabelled as v3 and make interrupted refreshes retryable without
rewriting historical partitions. Four regression cases reproduced before the
fix: old partial reuse, old record carry-forward under current metadata,
silent same-day incompatibility, and empty publication after model failure.

`market_tone` checks metadata and each record's prompt version, filters partial
records to the current reader, explicitly refuses incompatible same-day frames,
and retains partial results after fetch/model failures or refused publication.
A successfully fetched filing with no results exhibit is recorded as missing
coverage, separately from an outage. Historical frames remain immutable.

VERIFIED candidate: trading/market tests **437 passed, 8 skipped**, including
seven datastore assertions covering signed-loss persistence, retry, no-exhibit
coverage and refusal to overwrite history. Real-model release reader: **7 passed**
in 46.73 seconds, including signed losses. A real filing replay in temporary
storage rescored AAOI accession `0001683168-26-006055` from v2 to v3, persisted
net income of **-22.8 million**, removed its completed partial file, and left
the production store mounted read-only. Runtime module SHA256
`486d3e5df757ad56a5f1d9e0fb1393278152fbc0a1ede7c6870bdc510b616545`.
Ruff passes. Production-wide v3
backfill and resulting investment performance remain UNVERIFIED.

## 2026-09-12 — candle provenance and coherent intraday grades (deployed `f131d35d`)

Objective: make a fifteen-minute desk visit distinguish current market evidence,
the evening decision, and generated prose. Acceptance: stale/future/undated
candles and snapshots from a different decision cannot change the current
grade; the displayed analyst ranks and votes match that grade; candle and
explanation times are separately dated in Eastern time.

Starting point: isolated `codex/desk-live-provenance` at `d848095e`, clean before
editing. The shared main checkout was left untouched. Preserved the newer live
value analyst. A value-only reading now also updates the grade when technical
evidence is absent. Snapshots name their evening decision session; legacy
snapshots safely fall back to the evening grade. Old candle explanations use
deterministic evidence without making a new model call. The model-read cache
holds up to 64 symbol/candle/detail entries, rather than only the last name.

VERIFIED candidate: trading/market suite **430 passed, 8 skipped** (23 existing
numerical warnings), including route-level stale-data fallback; desk Playwright
**10 passed**, exercising candle refresh, separate evidence/prose timestamps,
indicative labels, drill-downs and unchanged holdings behavior, with no blocking
console errors or page exceptions. TypeScript, Ruff and diff checks pass;
production Vite build passes with existing CSS/chunk-size warnings. Browser
acceptance used this worktree's Vite server and deterministic API fixtures.

VERIFIED deployed on 2026-09-13 through `scripts/deploy.sh --wait-post`: unit
gate **3414 passed, 19 skipped**; post-deploy marker
`2026-09-13T03:26:40Z f131d35d ok (cheap)`. Public gateway acceptance returned
93 stale weekend quotes, zero indicative grades, nine covered board rows using
their evening grades, and a dated AAOI technical read with `read_at=null`.
Four deployed backend source hashes match the committed tree; gateway assets
contain the indicative-grade wording. The separate `~/anios` checkout used by
host market cron was fast-forwarded to the same checkpoint after deployment.

UNVERIFIED: authenticated production browser workflow, real-session feed
transitions, and any improvement in investment
returns. No broker orders were submitted. Earlier production inspection found
93/93 newest earnings-tone frames still labelled `release_tone/2`; repairing
partial/same-day caches and rebuilding v3 inputs remains separate work. Never
overwrite immutable historical partitions to perform that repair.

The user chose whichever horizon leads to the best overall gain. Research
objective: after-cost compounded returns, preserving current risk limits;
compare frozen candidates on unseen periods before changing the live rule.
The current five-session paper record cannot establish durable superiority.

## 2026-09-12 — the live grade re-reads the value analyst, the board warns when it contradicts the action, and "at risk" reads the candle (DEPLOYED `8df5a24`)

The live grade was re-made from the technical analyst alone. The value
analyst is price-derived — `valuation.multiples` uses the panel's close — so
a name that cheapened intraday changed its value rank while the filed levels
did not, yet its live grade never moved. The live read now carries the value
opinion beside the technical one (`_live_read` returns `"value"`), and
`value_now` mirrors `technical_now` (`{symbol: {"now", "close", "stance"}}`).
`holdings.board` and `live_grades` take the value read, `_live_grade` re-reads
both stances and carries the live grade's own margin
(`actions.grade_margin(votes, letter, release_bullish)`), so:

- the "at risk" marker reads `grade_margin_live` (falling back to the evening
  margin when the candle has not read the name), so it moves with the price;
- a row whose live grade is C while the action still says buy or add shows
  "grade C live: dropped at the next rebalance" in one line;
- the row's detail shows the value rank beside the technical one.

The dashboard copy was passed word by word: the footer now says the technical
and value reads re-check every 15 minutes, and "Money at work" reads as a
share of the practice account.

VERIFIED on spark1: changed-module tests 43 passed (added
`test_the_live_value_read_regrades_a_name`,
`test_the_live_grade_carries_its_own_margin`,
`test_value_now_reads_the_value_analyst_and_reports_the_stance`); unit suite
3357 passed, 19 skipped; routing gate 100 passed (3 unrelated functional
failures re-ran green — engine nondeterminism, not this change); desk
read/live-read/brief functional suites 7 passed; `npx tsc --noEmit` clean.
`value_now` exercised against the real store: 84 of 93 quoted names ranked
with stances. Deployed `8df5a240`, post-deploy cheap checks `ok (cheap)` —
search chain untouched, so the credit-consuming sweep correctly did not run.
## 2026-09-12 — why every Scout digest was the same five events (not deployed)

Reported as "crappy event recommendations, especially singles events even
though she said she is not single". Traced in the live database before any
edit. Four separate defects, three of them affecting every user.

**The digests were repeats, not recommendations.** `_repeat_fill` re-offers
still-upcoming finds so a quiet day is not silent. It had no bound. Novelty
suppresses everything already seen, so on any account with history the novel
side is empty most days and the fill supplies the whole digest. Live counts of
one find sent to one person: **arsalon 21, ibraa 13, ani.mallya 12, jenos1
11**. Every selected item in jenos1's last four digests carried
`shortlist_rank -1`, meaning nothing in them came from that day's sweep.
Capped at `MAX_REPEAT_SENDS = 3`, counted from `discovery_sent_finds` (the only
record of a *send*: a seen item's `announced_at` keeps its first timestamp, and
the label column is sealed per row so it cannot be grouped). There was no test
for `_repeat_fill` at all; there is one now.

**A stated audience was read by nothing.** jenos1 told the assistant on
2026-08-24 "I am not single and I am an adult"; it is stored, approved, and
does reach the sweep. Nothing acted on it, because ranking cannot: no embedding
of an interest is far from an event that excludes the person holding it, and
`reranking.py` records measuring the reranker refusing to exclude and, when
strengthened, over-excluding on a control with no relevant fact. Built the fix
that file names: `prompts/scout/audience.md`, a focused per-find call in the
shape of `scout/locate`, dropped in code in `_make_readable`.

The schema reads before it decides — `stated_audience` then `rules_out` — and
the caller refuses a verdict with no quoted evidence. That ordering is the fix,
not decoration: asked for the verdict alone, a wine festival stating no
restriction was ruled out **3/3** for someone whose fact was that they do not
drink. With the evidence gate, `functional/test_audience_behaviour.py` is
**7 passed** — the singles case excluded, and four keep cases held at 0/3
including the same page with no relevant fact on file.

**Ten ownerless schedules were being swept for real.** `discovery_schedules`
held enabled, due rows for `del_*`, `sch_*`, `api_del_*`, `scout_probe_v4` —
ids in no account table, left by tests run against this database. The worker
could not tell them from a person: 51 runs, 15 requests spent each, on a daily
and weekly cadence. `enqueue_due_runs` and `next_due_at` now require an active
`user_accounts` row, and the pass is bounded at 200. This makes existing
residue inert without deleting anything.

**Two smaller ones.** `discovery_seen_items.embedding` had no vector index
while every sibling embedding column has one, so both novelty queries were a
sequential scan per candidate over a table that only grows — migration
`20260912_0020`. And the hourly maintenance cycle ran without `--reembed`, so
it inventoried 180 stale vectors and fixed none, reporting `attention` forever
with `updated_total: 0`; the compose command now passes it.

VERIFIED in a probe clone of `7d8b7d8d` on spark1 with the changed files
mounted, against the live schema. Unit suite **3377 passed, 24 failed** against
a measured baseline of **3369 passed, 24 failed** on the unmodified tree — the
same 24 (access_requests, admin_boundary, model_gate, search_budget; missing
Redis mount, the documented gate trap), and 8 more passing, which are the new
tests. `functional/test_audience_behaviour.py` 7 passed.
`functional/test_prompt_behaviour.py` 22 passed, 2 failed:
`test_memory_capture_does_not_take_someone_elses_preference` fails identically
on the baseline tree, and the diagram case passed on re-run (model variance).

UNVERIFIED: deployment, and the migration against production. The index is
additive and safe under the running build, so apply it ahead of the deploy per
the additive-migration trap. Not deployed and not pushed — opencode held
uncommitted work in `~/anios` at the time.

## 2026-09-12 — desk cancellation, session-open, and text-bound fixes (not deployed)

Code commit `a0f1e5c9`, based on clean `73d6df9c`. The reviewed failures were
reproduced before editing. Cancellation now reads order status after Alpaca's
204 acknowledgement. The balancer saves `hold_requested` before cancellation;
reconciliation concludes a confirmed canceled sell as a deliberate hold while
preserving any partial fill. Pending cancellations stay pending and a full
fill stays a fill, including after a process restart. This prevents a
successful deliberate cancellation from resetting the rebalance clock.

Live quotes exclude extended hours and other dates, require the 09:30 New York
opening candle, and scope cache reuse to the requested session. The balancer
acts only from 09:30 to 11:00 with a current regular-session candle no older
than 30 minutes. Narrative cuts now use a sentence boundary inside the limit
or a fallback that fits, never a later boundary or a decimal point.

VERIFIED in an isolated copy of the candidate source mounted into
`anios-functional-tests` on spark1: trading/market tests **417 passed,
8 skipped**, 23 existing numeric warnings, 5.07 seconds. The new regression
module reads state back from disk after cancellation and reconciliation,
covering pending, partial, canceled, and filled outcomes, summer/winter session
opens, stale candles, cache date isolation, and strict text bounds. No real
broker traffic was sent. Desk brief/read/live-read functional tests against
the real `deepseek-v4-flash` runtime: **7 passed**, 78.90 seconds. Ruff on all
changed Python files and `git diff --check` passed.

UNVERIFIED: deployed broker/UI acceptance, full deployment gates, and
production earnings backfill. This was a fix-and-commit request; deployment
has not been performed. Ship only through `scripts/deploy.sh` and run its
required gates and deployed acceptance checks before claiming deployment.

## 2026-09-12 — the web vision upload fits an oversized screenshot instead of 413ing it (DEPLOYED `1b28dc0`)

A screenshot uploaded in the `ani.mallya` web chat on 2026-09-10 failed
with no artifact, no conversation turn and no stored evidence — because the
web vision path rejected it before anything could be recorded. The iMessage
path had a downscaling step (`_fit_for_vision`); the web path sent the raw
file and refused at read time, and its comment's claim that "the browser
picker downscales" is false. Reproduced exactly on the live system before
the fix: a 17.8 MB retina screenshot (3024×1964, 5.9 MP — under the 20 MP
pixel limit) returned **413 "Uploaded image is too large."** with no
artifact, because `IMAGE_MAX_UPLOAD_BYTES` is 10 MB and the byte cap was
enforced before any decode. The pixel limit (20 MP) and the byte limit
(10 MB) were inconsistent: a valid screenshot could pass one and fail the
other, and the failure left no trace anywhere.

Fixed in `1b28dc0`: `backend/artifacts/image.py` gained `fit_image_for_vision`
(downscale when the pixel count exceeds 90% of the pixel limit; re-encode to
JPEG when the bytes exceed the storage budget, stepping quality down and
halving pixels until the budget holds — the budget is a guarantee, since
`validate_image_bytes` enforces it next), and `backend/api/v1/vision.py`
reads the upload with a fetch cap derived from the pixel limit
(`max(2×upload, 3×pixels)`), fits the bytes to the budgets, and stores the
fitted image. Fitted output keeps its true decoded mime so the
declared-vs-content check still passes. Unit tests (`test_image_artifacts.py`):
pass-through unchanged, byte-budget re-encode, pixel-ceiling downscale, and
fitted-output-passes-validation. Verified live post-deploy: the same
17.8 MB screenshot now returns **201**, stored as a 4.95 MB JPEG at the same
3024×1964 dimensions; both synthetic verification artifacts were deleted
afterwards (today's `ani.mallya` artifact count back to 0). Unit gate
`3376 passed, 19 skipped`; routing gate `100 passed`; post-deploy
`2026-09-12T17:18:26Z 1b28dc0e ok (cheap)`. A 413 still exists only beyond
the pixel-derived fetch cap (~60 MB at 20 MP), which no legitimate screenshot
reaches.

## 2026-09-12 — the seventh desk review's remaining P1s and P2s, fixed and measured (DEPLOYED `1b28dc0`; contains `b706540`)

The seventh codex review returned more findings after `6f70007a`. All are
fixed in `b706540`, each pinned. The deploy was held because the unit gate
failed on an in-progress image test (`test_fit_image_for_vision_reencodes_an_over_byte_budget_image_to_jpeg`
had a 2,387-byte fixture asserting `> 50_000`); that fixture is fixed in
`1b28dc0` and the gate is green, so the combined tree deployed together.

- **P1 cancellation** — `cancel_orders` now returns the broker's outcome
  per order (`"cancelled"` / `"unconfirmed"` / `"already_gone"`), and the
  green-day rule journals a hold only on a confirmed cancel, so an
  unconfirmed or already-filled order can no longer be recorded as a
  zero-fill hold. Pins: `test_an_unconfirmed_cancel_is_not_journaled_as_a_hold`,
  `test_cancel_orders_reports_an_unconfirmed_cancel`,
  `test_cancel_orders_skips_an_order_that_is_already_gone`.
- **P1 earnings cache** — the corrected loss parsing ships under a bumped
  prompt version (`release_tone/3`), invalidating cached frames the faulty
  bounds clamped to zero, so the nightly run re-scores. `test_prior_tone_records_carry_forward`
  already pins version invalidation.
- **P1 backtest mismatch** — the green-day skip compares the session's
  open against the prior session's close (the same comparison the
  simulator makes) instead of the latest tick, so live execution no longer
  sells a name the backtest would hold.
- **P2 narrative** — the C-grade brief dropped when the writer generalised
  a mixed picture into one direction. `desk_brief.md` now requires the
  verdict to summarise only what the reasoning asserts and to state a
  signed measurement's direction as given; the retry passes the desk's
  clean fact contract to the rewrite. First-attempt success measured
  **12/12**, functional test passes repeatedly (5/5 on one run, 12/12 on
  another); the bounded retry remains a safety net.
- **P2 long reads** — a live read with no sentence boundary in the first
  window now falls back to the deterministic read instead of cutting
  mid-word.
- **P2 sell timing** — desk help text now says sells fill at the close of
  the session that *executes* them (the one after the session that decides
  them), matching `simulate`'s `exit_at_close` fill at `closes[t+1]`.

**Verification**: unit suite `3375 passed, 19 skipped` (the single failure
is the other agent's in-progress image test), routing gate `100 passed`
(~8m14s), desk read / live-read / brief functional suites `7/7`, frontend
`tsc` clean. Deploy pending as above.

## 2026-09-12 — the sixth desk review's four P1s and remaining P2s, fixed and measured (DEPLOYED `6f70007a`)

The sixth codex review of the trading desk returned four P1 findings and
several P2s. All are fixed, each with a regression pin; the standing P2s
are closed too. Full detail in the commit message; the short list:

- **P1 #1 cancellation** — `cancel_orders` now matches the broker's own
  order UUID and raises `AlpacaTradingError` on a genuine refusal, so the
  balancer's `except → continue` can no longer journal a cancellation that
  never happened. Three paper-trade tests pin it.
- **P1 #2 backtest parity** — `simulate.LIVE_POLICY` (`block_overbought`,
  `exit_at_close`, `green_day_skip`) now runs in the curve block and the
  scorecard, so the track record and the live strategy obey the same fills.
  Parity test in `test_market_daily.py`.
- **P1 #3 earnings losses** — `release_tone`'s schema bounds for net
  income / gross margin are now signed, so a reported loss is not rounded
  up to zero. Functional pin: `test_a_reported_loss_stays_negative`.
- **P1 #4 board blocker** — the board reports the band-reversal blocker's
  own verdict (`blocked` + reason) instead of asking the operator to place
  an order the strategy refuses. holdings + DeskPanel + API tests.
- **P2 #5 session time** — `live_technical` and the green-day skip derive
  the session date from `America/New_York` (was UTC / hard-coded −4h).
- **P2 #6 research units** — the dip signal's `band_position <= 0.20` (was
  `<= -0.80`, inside the band), and a trim's freed weight is not redeployed
  into the trimmed name.
- **P2 #7 missing data** — `index_returns` reads the store's
  `adjusted_close` (was a non-existent `adj_close` falling back to raw
  close); the desk chart's `line()` now closes a segment on a missing
  value instead of bridging the gap (the Sep 9 bridge).
- **P2 #8 wording** — sizing copy names A+ 100% / A 75% / B 50%, sells
  fill at the close of the deciding session, the "weekly 21-day average"
  is now the 21-week average (prompts, plainly, API comment), and the
  board table scrolls horizontally instead of clipping at 390px.

**Verification**: unit gate `3370 passed, 19 skipped` (~2m21s), routing
gate `100 passed` (~8m24s), ruff clean, `tsc` clean; the desk read /
live-read / brief functional suites pass against the real model (7 tests,
including the brief suite's five-of-five across repeated runs). Deployed
`6f70007a` from `~/deploy/anios`; post-deploy `2026-09-12T09:29:47Z
6f70007a ok (cheap)` — backend through the gateway 401, `/health` 200;
gateway + backend containers created 09:29:33Z.

**Carried forward, still true**: the C-brief checker stability work is in
this commit too — `_check_facts` includes regime lines and book status,
`_contradicts` drops only on a majority of three checks, and
`desk_brief.md` forbids position-sizing language for a name not in the
book. Nothing outstanding for the desk; the nightly 19:30 run is expected
to re-score the book's release financials with `release_tone/2` (the
mechanism from `c988172`).


## 2026-09-11 — the desk exits on the close and never into a name's own rally, the option walls reach the live drill-down, and the fundamental analyst reads an 8-K's own numbers (DEPLOYED `c988172`; contains `f003b27` + `bc7e9aa` + `c988172`)

Three changes shipped in one deploy, all backtested or functionally pinned:

**Exit on the close, never into the name's own rally** (`f003b27`). The
desk's exit was decided on one close and filled at the next open — that is
how ETN was sold at the day's low on the morning its rally began. Sells now
ride the market-on-close order (`time_in_force: cls`), buys still fill at
the next open, and the intraday balancer cancels a pending sell during the
opening hour when the name is trading up (`_green_day_skip`, 9–11 EDT
weekdays only), journaling the deliberate hold so the rebalance concludes.
The simulator walks both behaviours (`exit_at_close`: sells fill at
`closes[t+1]`; `green_day_skip`: hold when `opens[t+1] > closes[t]`), so
the change from the old all-at-the-open fills is measurable. Backtest over
the desk's 11.66-year history (2939 sessions, 94 names): baseline sell-at-
open CAGR 25.1% / vol 16.5% / Sharpe 1.440 / MaxDD −25.7%; exit-at-close
alone 24.3% / 16.8% / 1.379 / −25.5% (close fills are marginally worse than
opens here); exit-at-close + green-day-skip 36.0% / 25.6% / 1.332 / −28.4%
with 81 fewer trades (4.44 turnover). The combined rule is what went live:
absolute return up sharply at materially higher volatility and a lower
Sharpe — the behaviour was requested (don't sell ETN into its own rally),
and these numbers are the honest cost. Fills verified in
`backend/agents/trading/desk/simulate.py`, `paper.py`,
`backend/market/alpaca_trading.py` (`submit_market_on_close`),
`backend/cli/market_daily.py` (`_submit`: sells→close, buys→open),
`backend/cli/market_balancer.py`.

**Option walls in the live drill-down** (`bc7e9aa`). `live_technical.py`
`_walls_for` reads the newest stored `options` frame and carries the put
wall, call wall, their open interest, the net gamma and the distances
(relative to the panel's adjusted close, which is coherent with the frame's
reference price) into each name's `technical_detail`; `DeskPanel.tsx`
renders them under the rank line. Verified against the deployed container:
`technical_detail` for ADBE emits expiry 2026-09-18, put_wall 220, call_wall
300, net_gamma −46147, put_wall_distance −0.116 (at ~245) — coherent with
the stored frame's reference price 244.17. The deployed gateway bundle
contains the render (`index-CjEp7hyb.js`, image built 20:30Z after the
commit).

**An 8-K's own numbers reach the fundamental analyst** (`c988172`). The
release reader (`release_tone.py`, PROMPT_VERSION `release_tone/1` →
`release_tone/2`) now also reports the quarter end and the reported revenue,
EPS, net income and gross margin; the tone frames carry them; `edgar.release_facts`
turns them into `QuarterFacts`; and `model.load_edgar_features` merges them
into the fundamental record, so a fresh 8-K between 10-Qs advances revenue
and margin features immediately. Legacy frames without the new columns read
back as no financials. Functional tests pin extraction and the
null-when-unstated case against the real model (`test_release_tone_behaviour.py`,
6 passed); unit tests cover the round trip, the legacy frame, the release-
facts conversion and the merge. Deployed container verified carrying
`release_tone/2`, the financial `ToneRecord` fields, and `edgar.release_facts`.
**Post-deploy refresh done for ADBE**: `market_tone --refresh --tickers ADBE`
re-scored all 47 stored releases with v2 (4.9 min); all 47 now carry
financials, and the fresh 8-K (filed 2026-09-10, quarter end 2026-08-28)
reads revenue 6760M / EPS 4.62 / NI 1827M / GM 88.7%. `edgar.release_facts`
over the real frame yields that quarter (asserted), and
`load_edgar_features` over a real ADBE panel computes all 18 fundamental
features finite. **The nightly 19:30 run re-scores the rest of the book**
(~93 names × their release histories, one-time ~2h at concurrency 4) because
`market_tone.prior_records` drops frames on a prompt-version change — that
is the mechanism that folds release financials in for every name; ADBE is
already in the 2026-09-11 partition and will be skipped.

**Verification**: unit gate `3360 passed, 19 skipped` (incl. ruff); the six
functional release-tone tests passed against the real model (spark1:8000);
`tsc` + `vite build` clean; backtest numbers above. Deployed `c988172`;
post-deploy `2026-09-11T20:30:32Z c988172 ok (cheap)` — backend through the
gateway 401, `/health` 200.

## 2026-09-11 — the desk's eleven review findings are fixed and measured (DEPLOYED `7f3e313`), and the credit-consuming post-deploy checks now run only on search-affecting deploys (DEPLOYED `4e9f75a`)

The fifth codex review of the trading desk returned eleven findings; all
eleven were fixed, tested and shipped in one commit. Full detail in the
commit message; the short list is the entry-point clock in
`_forward_walk` (F1), per-row `rebalance_due` + "Targets for the next
rebalance" header + "Changes in target weights" wording (F2), held
out-of-book shares shown as `uncovered` review state with no done button
(F3), `PaperOrder.client_order_id` + `order_id()` + `cancel_orders(ids)`
(F4), `MARKET_INDICES = ("SPY", "QQQ")` + known-days-only scorecard
compounding + all-NaN benchmark guards (F5), CurveChart merged date axis
(F6), HowToUse copy (F7), `_cut` never leaving an unfinished sentence +
`narrative._contradicts` brief guard pinned by
`prompts/trading/desk_brief_check.md` + `functional/test_desk_brief_behaviour.py`
(F8), live grade in the `!row` path via `liveGrades` (F9), local-time
`shortDate` + `_pct_abs` removed (F10), `poll` at component scope (F11).
Verified: unit suite 3342 passed / 18 skipped, ruff clean,
coverage-completeness gate 69 passed, `tsc` + `vite build` clean, 9/9 desk
Playwright tests (3 new), 21 desk/API backend tests. Deployed `7f3e313`;
post-deploy all green (sweep_journeys OK, exercise_search_scenarios OK).

**Search credits are the constraint now.** That same sweep's harness
reported Tavily at 0 of its 1000 searches this billing period, with the
repeated questions served from the 30-minute SQLite cache — the whole
reason the policy below exists. On 2026-08-29 deploy sweeps accounted for
344 of the month's 403 searches.

**The post-deploy sweep no longer runs on every deploy.** `scripts/deploy.sh`
computes whether the `$before..$after` diff touched the search chain or the
router's tool choice (mcp, services, tools, core prompts, the
chat/reply/scout agents, `prompts/(routing|reply|search|scout|referent|refinement)/`,
the checks themselves, skills, bridges). Only then does it run the full
`post-deploy-checks.sh` sweep + search harness; any other deploy runs
`--cheap` (gateway→backend 401, backend `/health` 200), which still writes
`data/.post-deploy-status` and pages on red. `--run-post` forces the full
set; an empty diff is treated as full. Pinned by
`backend/tests/test_deploy_scripts.py::test_the_credit_consuming_checks_are_opt_in_by_diff`.
Validated on the deploy of `4e9f75a` itself (a scripts/tests-only diff):
the deploy printed "cheap checks running in the background" and the verdict
was `4e9f75af ok (cheap)` with the gateway answering 401 and `/health` 200.
This policy change takes effect on the next deploy's run of `deploy.sh`.

Next: nothing outstanding. Watch Tavily credit replenishment before trusting
a full sweep's live numbers.

## 2026-09-10 (evening) — the drill-down re-reads its analysis when the candle turns, and its timestamp is its own (DEPLOYED `9d5669e`)

The fourth codex review's one remaining P2: an open drill-down showed
stale analysis beside fresh prices. The live read was fetched once on open
(keyed `[userId, ticker]`), so a candle refresh updated the price,
timestamp and technical rank — all read from the live snapshot — while the
prose and horizon lines still described the older candle, and the header's
"live, HH:MM" was the candle's time, not the analysis's. Reproduced in the
code before fixing: `LiveTechnical` renders `quote.last` and
`detail?.now` from the fresh candle but `liveRead.read`/`lines` from the
on-open fetch, and `desk_live_read` never returned a timestamp.

The fetch is now keyed on `quote?.bar` — the same stable candle identifier
the backend's per-candle cache uses — so a new bar re-reads the analysis
and an unchanged bar never does; a name outside the snapshot has no bar and
still reads once on open. The backend returns `read_at` (cached with the
read, so a cache hit keeps its original time), and the header shows that
instead of the candle's `as_of`. Pinned by `e2e/desk.spec.ts` `a new candle
re-reads the analysis alongside the fresh price`, which drives one
fifteen-minute candle with `page.clock.fastForward` and asserts the prose,
horizon lines, price ($102→$110), rank (90→20) and header time all move
together and that the read endpoint is hit once for the new bar. Verified:
all 7 desk Playwright tests pass, `tsc` and `vite build` clean, ruff clean,
21 desk/API backend tests pass. Deployed `9d5669e`; the deployed backend
serves `read_at` (200 on `desk/live/read/AAPL`, `now 0.957`), the gateway
bundle contains the new code; post-deploy sweep was running at the time of
writing.

## 2026-09-10 (afternoon) — an in-flight cancel or replace stays pending, and a same-session re-run is refused before any trade (DEPLOYED `2e8dae0`)

Two P1 findings from the third codex review (a fresh session that pulled
`main` stale at `89a8211`; each claim was reproduced before fixing).

* **A partial reported `pending_cancel`/`pending_replace` was dropped and
  the rebalance clock rolled back while the original order was still
  live.** Those two statuses were outside `paper._WORKING`, so `settle`
  marked such a partial terminal — even though the cancel or replacement
  is in flight and the order can still fill. Both are now in the working
  set; only a broker-confirmed terminal outcome concludes the partial.
  Pinned by `test_an_in_flight_cancel_or_replace_keeps_the_partial_pending`
  (parametrized over both statuses), which asserts the partial stays
  pending and `unconfirmed_rebalance` is unchanged.
* **`market_daily.main()` ran `paper_trade()` before `save()` refused an
  existing record**, so a same-session re-run placed orders and persisted
  pending state, then printed "nothing was changed". The record-exists
  guard is now a `refuse_existing_record(root, session, force)` helper
  called before any brief, read, or trade, with an early return. Pinned by
  `test_a_same_session_rerun_submits_no_trade`, which monkeypatches
  `trading_desk.run` and `paper_trade`, pre-seeds a record, and asserts
  `paper_trade` is never reached and the stdout says "refusing to re-run
  the day". The briefs/reads block also moved into
  `_wanted_briefs_and_reads` to keep `main` under the complexity bound.

Verified: 54 desk/market tests pass, ruff clean (with `backend/` mounted —
the functional-tests image is stale by design and a bare `ruff` run
analyzes the baked-in copy). Deployed `2e8dae0`; unit and routing gates
passed; post-deploy sweep running.

## 2026-09-10 (afternoon) — the drill-down's live read works for any covered name, horizons beside the prose (DEPLOYED `73ca0c4`)

A covered name outside the book is graded every evening but was not in the
candle's live snapshot (the balancer covers `book ∪ held ∪ actions`), and
the drill-down skipped the whole technical block because it required a
board row — so a name like ORCL showed no live read at all, and when the
model prose read was present it replaced the short/medium/long columns.
The backend already computed the read on demand from a fresh quote; the
frontend never asked. `LiveTechnical` now always fetches on open and
renders for any covered name (`row` nullable), and the prose read leads
with the three horizon columns beside it instead of replacing them.
Pinned by `e2e/desk.spec.ts` `drills into a covered name outside the book
and sees its live horizons` (MSFT-grade fixture not in the board). Verified:
frontend `tsc` and `vite build` clean; all 6 desk Playwright tests pass;
the backend served ORCL's full live read on demand (short/medium/long
lines from a fresh quote); deployed `73ca0c4` with green post-deploy
sweeps and the horizon strings in the gateway bundle.

## 2026-09-10 (midday) — the desk record is immutable and carries provenance, a down market clock fails closed, the coverage gate sees ranked analysts, and the dashboard shows each thing once (DEPLOYED `26bebfc`; contains `41efede` + `26bebfc`)

The six findings from the second codex review (a fresh session that had no
context, so every claim was verified by reproduction before anything was
changed), plus the operator's dashboard review. Both deploys are live with
green post-deploy checks (`41efede6 ok`, `26bebfcb ok`).

* **Order lifecycle, paper book** (`paper.py`): a canceled/expired partial
  stayed pending forever and a rejected leg was forgotten when another
  filled later. `apply_settlements` now journals every settlement (latest
  wins), keeps only still-working pending, and concludes a rebalance only
  over the legs that are done — a canceled partial rolls the clock back and
  the journal survives the state file. Pinned by `test_a_canceled_partial_is_concluded_and_the_clock_goes_back`
  and `test_a_rejected_leg_is_not_forgotten_when_another_fills_later`.
* **A down market clock fails closed** (`market_daily._submit`): the old code
  caught the clock error and submitted market-on-open orders anyway. Now it
  refuses every order with "REFUSED: market clock unavailable". Pinned by
  `test_an_unavailable_market_clock_refuses_submission`.
* **The desk record is immutable and self-describing** (`market_daily.save`):
  saving a second record for the same session raised no error and silently
  replaced the first — the track record no longer said what was decided.
  `save()` now refuses to overwrite (an explicit `--force` rewrites), and
  every record carries `provenance` (code revision, data window, strategy
  cadence, model). Pinned by `test_save_refuses_to_overwrite_a_session_and_carries_provenance`.
* **The coverage gate saw ranked analysts as uncovered** (`narrative.py`):
  `_ANALYST_LINE` expected `stance +1;` but the ranked line carries
  `(rank 0.95 ...)` between the stance and the semicolon, so the analyst was
  never checked. The pattern now allows the rank; pinned by
  `test_the_coverage_gate_sees_a_ranked_analyst`.
* **Dashboard duplicates removed** (`DeskPanel.tsx`, operator review). "The
  desk is X% invested" appeared twice with two meanings (evening target vs
  live paper) — the header now keeps only the decision date and the strip
  owns the live figure. Today's move appeared twice (percent in the account
  cell, dollars in its own) — now one "Today" cell with both. Every buy
  appeared twice — "Best buys right now" and the board's buy rows with two
  buttons that did the same thing — the board now owns the single buy list
  and its header carries the "Since the last plan" note. The practice
  account's positions appeared twice — the live section moves below the
  board and the behind-the-fold panel shows the table only when the broker
  is away. Pinned by `e2e/desk.spec.ts` `shows each thing once, not twice`.
* **"Best buys" ranking verified against the live 15-minute candle.** The
  balancer rewrites `intraday.json` on the candle and the order actually
  moves (13:45 run re-ranked SNDK/NTAP/LRCX/ANET/ADBE and flipped NVDA
  B→A, ETN A→B); the rank key is the technical analyst re-read at the live
  price (`holdings._live_grade`). Caveat: ranked by the read *at* the price,
  not raw price move; falls back to the evening grade if the live read is
  down. The fair-universe gap (`universe.py:23-28`, ~19 pts/year) was
  confirmed as a documented limitation, not a bug.

**Verified:** 43 desk/market unit tests pass + ruff clean (`41efede`);
frontend `tsc` clean, `vite build` clean, all 5 `desk.spec.ts` Playwright
tests pass including the new dedupe test (`26bebfc`); post-deploy sweeps
green on both (two flaky journeys and the search harness re-checked on the
second deploy). The gateway bundle no longer contains "Best buys right now"
and does contain "Since the last plan"; the gateway proxies the desk API
(401, not 502). Git: `main` at `26bebfc`, `~/anios` clean.

**Next atomic task.** Watch the first real desk record written under the
immutable `save()` — the nightly `market_daily` must not hit the new
`FileExistsError` on a same-session re-run (it would now refuse loudly,
which is correct, but confirm nothing re-runs the same session). Then let
the 19:30 nightly write records under the new tracker before judging the
rule's live track record, and re-run `market_scorecard` to refresh the
module docstring's history table (the tracker fix changed forward numbers).

## 2026-09-10 — the record tracker sizes like the desk, the network purges whole sessions, partial fills stay pending, and named extra accounts read the desk (DEPLOYED `02b73cf`; contains `9b0dd05` + `277d55d` + `02b73cf`)

The five codex review findings from 2026-09-09, all verified by reproduction
first, then fixed in one bounded piece with a shared order planner, plus the
operator's request to open the desk to `vjmallya` — which the second review
then found let an extra account overwrite the primary operator's shared
holdings file, now closed by read-only access for extras.

* **One order planner for all three execution paths** (`backend/agents/
  trading/desk/planner.py`): `target_shares` + `plan` decide the orders at
  the close the decision could see; the simulator (`simulate.py`), the paper
  account (`paper.py`) and the record tracker (`market_scorecard.py`) each
  keep only their execution (continuous shares at the open / whole-share
  broker rounding / pricing nightly records forward). The old tracker sized
  at the next *open*, so an overnight gap changed how much a rebalance was
  worth (F1); it mixed adjusted closes with raw opens, so a flat price across
  an ex-date booked a fake **-5.10%/+5.27%** move (F2); and a record with no
  challenger block turned a real +2.1% move into a NaN that compounded as
  flat (F3). Now: sized at the close, filled at the open, the open adjusted
  on the close's basis, a held book always earns the real move, and the
  tracker's turnover is recorded instead of hardcoded 0.
* **The network hold-out purges whole sessions** (`market_interactions.py`):
  the last `HORIZON` sessions before the validation window, not
  `min(HORIZON, rows)` flattened rows — which left a ninety-name session half
  in and half out (F4). Only affects the network's early stopping.
* **A partial fill stays pending** (`paper.py` `apply_settlements`): its
  outstanding quantity is asked about again and the rebalance is never
  concluded on a partial (F5); a terminal outcome still rolls the clock back.
* **The live snapshot is marked stale when older than a candle** (`market.py`
  `desk_live` + `age_seconds`/`stale` in the response; the panel shows
  "stale — older than a candle").
* **Named extra accounts read the desk; only the primary operator writes it**
  (`MARKET_DESK_USERS` allowlist + `MARKET_DESK_USER` writer guard on
  `PUT /desk/holdings`; `SessionResponse.desk_write`; the panel hides the
  buy/mark-done/positions-editor for readers and shows "read-only — the
  operator's book"). The second review reproduced an extra account replacing
  the operator's `holdings.json`; the two-account test now writes the
  operator's, attempts the extra's, and reads back both sides (403, list
  intact).

**Verified:** all five findings reproduced first (repro script
`/tmp/opencode/repro_scorecard.py`); ruff clean; 110 desk/market/auth unit
tests pass including the new two-account holdings test, the flat-across-a-
dividend test, the whole-session purge test and the partial-stays-pending
test; `npm run build` clean. `9b0dd05` and `277d55d` pushed to `main`;
deploy of `277d55d` started 2026-09-10T07:29Z detached
(`data/deploy-277d55d-*.log`). The 1410607a post-deploy sweep completed
**OK** (sweep_journeys + exercise_search_scenarios). The forward-track
numbers in the `market_scorecard.py` module docstring's history table will
change once the tracker fix is live — re-run `python -m
backend.cli.market_scorecard` after deploy and update the table.

**Next atomic task.** Confirm the `277d55d` deploy's unit + routing gates,
then its post-deploy sweep; verify `MARKET_DESK_USERS=vjmallya` and
`market_desk_operators = {vjmallya, ani.mallya}` in the running backend, and
that a vjmallya token gets 200 on the desk read routes and 403 on
`PUT /desk/holdings` (needs their password for a full end-to-end). Then
re-run `market_scorecard` and record the corrected forward-track numbers,
and let the next 19:30 nightly write records under the new tracker before
judging the rule's live track record.

## 2026-09-09 (late) — the desk reads are model-written prose, the levels are named by what they are, and the practice account shows lifetime and day moves (DEPLOYED `c9ffd0c`)

The operator's second word-by-word review of the dashboard. Every prose
output the desk shows is now written by the model; the deterministic
renders survive only as the fallback floor, and every model-written
prompt is pinned by a functional test.

* **The drill-down "read" is model prose, complete by construction.** The
  whole evidence for a name — every analyst, every measurement, the nearest
  support and resistance named by what they are (a swing point, the 50-day,
  the 200-day, or the weekly 21-day average) — is written once a night by
  `prompts/trading/desk_read.md` (`--read` / `--read-book` on the nightly),
  stored on the record's grade as `read`, and rendered as prose. The nightly
  evidence now carries `support_level/support_kind/resistance_level/
  resistance_kind` from `levels.level_identity` (`backend/market/levels.py`),
  which says what the nearest level is rather than only how far away.
  `DeskNarrator.read_sync` writes unstructured prose (no schema, greedy), and
  a coverage gate checks the read still mentions every analyst and both
  levels with a distance, retries once naming the gap, then falls back to the
  deterministic `plainly.reads()` — so a skipped trigger is structural, never
  silent. Pinned by `test_desk_read_behaviour.py` (2 tests, real model).
* **The live technical read is model prose too.** `prompts/trading/
  desk_live_read.md` + `GET /desk/live/read/{symbol}` (cached per candle)
  turns the live short/medium/long features into plain words; the
  deterministic `live_technical.lines()` — now a backend function, with the
  level kinds named — is both the model's input and the fallback when the
  runtime is away. Pinned by `test_desk_live_read_behaviour.py` (real model).
* **The practice account fixed.** `$99,254↑ +0.0%` mixed the live equity
  with the record's 0.03% lifetime figure. `desk_paper` now returns
  `pl_pct` (equity/start − 1) and `day_pl_pct`; the strip shows lifetime and
  today's moves as percentages beside the dollars.
* **The "While held" block reworded** to "Return while it was an A /
  Return while it was not / Sessions it was an A / Crossed the A line" with
  a lead-in sentence; **stale briefs** that dump raw evidence
  (`revenue_yoy +0.262`) are hidden by shape and the model read shown
  instead; **BestBuys** no longer duplicates the board under "Set up the
  board" when holdings are empty.

**Verified:** ruff clean; 108 desk/market unit tests; 74 functional tests
including the coverage gate and both new read pins on the real model; tsc
and `npm run build` clean; 4/4 desk browser tests in Chromium (new
assertions for the reworded cells, the model read, the live read, and the
practice percentages). Merged to `main` and deployed as `c9ffd0c`
(`scripts/deploy.sh`, unit gate 3299 passed + routing gate green; the
gateway image rebuilt 2026-09-10T01:24Z and its bundle contains the new
"Return while it was an A" strings; backend verified through the gateway
answering 401). One pre-existing failure had to be fixed first: the other
agent's `d40d766` changed the search-credits waiting lines without
updating `test_search_credits_tool.py`, so the unit gate was red on main;
the test's allowed set now names the tool's actual lines. Post-deploy
sweep/harness running detached (`data/post-deploy-c9ffd0cc-*.log`).

**Next atomic task.** Tonight's nightly must run with `--read-book` (and
`--brief-book`) so every book name gets a read; the on-disk `desk.json`
briefs are still the old-prompt dumps until the next 19:30 nightly. The live
read endpoint needs a model call per drill-down open — watch its latency
through the gateway after deploy. If the operator records positions
(Buy/done), re-check the Exit column's held-name wording as before.

## 2026-09-09 (evening) — the desk's live numbers serve the candle, briefs say measurements in words, and the board's list is live and clickable (DEPLOYED `b833c6d`)

Continues the 2026-09-08 entry below it. The operator's dashboard feedback
through the day, each verified on the deployed system:

* **The live endpoints were six or seven seconds each** — a fresh Alpaca
  quote fetch plus the technical analyst re-read on every request
  (`technical_now` alone is ~4.25 s). The intraday balancer already computes
  both on each fifteen-minute candle, so it now persists them to
  `data/market/desk/live.json` and the API serves that candle instead of
  recomputing. Measured live: `/desk/live` **6.9 s → 0.008 s**, `/desk/mine`
  **6.1 s → 0.005 s** (~1000×). The snapshot covers `book ∪ held ∪ actions`
  (10 names; the old live path covered actions only). A balancer run with no
  quotes (keys unavailable) leaves the previous snapshot standing rather
  than clobbering it, and the API falls back to computing live when the
  snapshot is missing or empty.
* **The desk brief quoted the desk's own field names back at the reader**
  (`revenue_yoy +0.194`, `stack_order +1.000`) — the prompt told it to copy
  numbers verbatim with their names. `prompts/trading/desk_brief.md` now
  says what each measurement means in plain words and never reproduces a
  field name or a raw signed figure; `test_desk_brief_behaviour.py` pins the
  property instead of rewarding echoes (3 passed on the real model).
  **Caveat:** the briefs in the UI come from the last nightly (session
  2026-09-08, old prompt); they regenerate at the next 19:30 nightly.
* **Every grade is now ranked by the live score** (best value at the current
  price on top) and its tickers open the same drill-down as the board.
* **The Exit column repeated the same rule on every row** (all nine rows
  were "a buy only while it holds an A grade", because the operator has not
  yet recorded positions via Buy/done, so `holdings.json` is empty and the
  board shows the book's names as buys). It now says each name's own
  distance from the line that ends its buy or hold, from `grade_margin`:
  "on the edge, one analyst away" (≤ 0, red), "a hair above the line"
  (< 1, amber), or the plain rule (comfortable). Held rows and dropped rows
  have their own wording. The board's "you hold N at $X" text will appear
  once positions are recorded.
* Also landed earlier today: the `$` audit fixes (`887daef`), the drill-down
  horizons as chart timeframes — daily / weekly / monthly (`cb92fa8`), the
  backend mount of the whole market root (`0905008`), and Claude's desk
  fixes (`8a73c6e`, `175c556`) — all reviewed clean.

**Verified:** full unit gate passed before deploy; routing gate passed; desk
brief functional test 3/3; live latency measured 0.008 s / 0.005 s through
the gateway; the deployed gateway bundle contains the new exit-column and
every-grade strings. Post-deploy sweep for `b833c6d` was still running at
the last check (previous verdict `cb92fa86 ok`).

**Next atomic task.** Let tonight's 19:30 nightly write the new-format
briefs, then confirm a brief reads as prose with no `revenue_yoy`-style
identifiers. If the operator records his positions (Buy/done), re-check the
Exit column's held-name wording and the "you hold" lines. The desk's search
quota note still applies (the shared Tavily pool resets October 1).

## 2026-09-08 — the desk dashboard overhaul, built and browser-verified on the branch (NOT MERGED)

On `feat/desk-dashboard-overhaul` (currently at `f8270e2`, the same commit as
`origin/main`, work uncommitted until the merge decision). The operator asked
for the trading dashboard to be understandable to a person; the agreed scope
was the dashboard overhaul plus autopsy-as-a-view. Verified by running:

* **Backend (18 tests, ruff clean).** `market_daily` now writes a curve block
  into the record (the rules walked forward against SPY and QQQ plus the
  paper account's live equity) and a per-name history file under the market
  data root; `GET /desk` returns the curve, `GET /desk/history/{ticker}`
  reads the nightly file, `GET /trading/autopsy` runs the caller's own
  trading documents through `TradeAutopsy` and returns patterns/costs/plan
  with sources and passages used. The nightly cron on spark1 needs no new
  flag: the new `main()` computes and writes these automatically.
* **Browser (4 new tests in `frontend/e2e/desk.spec.ts`, all passing).** The
  real desk page is exercised with the session mocked as the operator and
  every desk endpoint mocked from the record's shape: the at-a-glance strip
  (practice worth, today's move, rules vs SPY/QQQ, exposure, next rebalance
  date), the regime warnings in plain words, "what changed since the last
  session", the track-record curve and CAGR/vol/drawdown, the plain-word row
  with its ticker drill-down, the autopsy view, and the getting-started empty
  state. `npm run build` and `tsc --noEmit` are clean. (The container runs
  e2e with Alpine's `chromium` binary and a `colorScheme: 'light'` override;
  the throwaway `playwright.container.config.ts` was removed after the run.)

**Next atomic task.** The merge and deploy are the operator's call: merge the
branch, then rebuild the gateway for the frontend (`docker compose build
gateway && docker compose up -d gateway` — a plain restart ships stale bytes),
recreate the backend for the new routes, and confirm the nightly cron writes
the curve/history files into the mounted `data/market/desk` partition. The
real record on disk has no curve yet because the feature is new; the page
says so until the next close.

## 2026-09-08 — failed photo analyses are recovered so a picture's meaning always reaches memory (DEPLOYED `58d0cca`)

Recurrence prevention for the bird-evening defect. The 09-05 fix stopped
unaddressed room photos being dropped (`_observe_photos`), but a photo whose
vision pass transiently fails is still stored with no meaning — exactly the
"picture meaning never reached memory" failure the operator described. A new
maintenance job `backend.cli.recover_vision_analysis` (service
`vision-analysis-recovery`, maintenance profile, 12 h interval) re-inspects
every ready upload with `analysis_status: failed` using the real VLM and
rewrites the analysis and its embedding in place (`VisionAnalysisService.recover_analysis`).
**Verified:** recovered the two existing failed uploads live (ani.mallya's
08-25 photo and carolinecheatham's) — both now `analysis_status: ready` with
an embedded `visual_artifact_analysis` semantic-memory row; unit tests added
(11 in `test_vision_memory_indexing.py`, incl. failure-leaves-artifact-alone);
unit gate 3233 passed; post-deploy `sweep_journeys OK` + `exercise_search_scenarios OK`.
Recurrence-prevention stack for "photo meaning reaches memory" is now: room
path stores/announces photos (`_observe_photos`), upload path stores+analyzes,
failed analyses recovered within 12 h, momentary-state memory rule stops
"i'm with gubacchi" being recorded as a person, and the naming feature binds
user-given names to photos at upload.

## 2026-09-07 (end) — harness search identities are no longer capped like people (DEPLOYED `90c028d`)

The post-deploy checks were reporting "used up the search allowance for
today/this month" while real search stayed up. Root cause, found by probing
the live meter: a deploy harness is an account `issue_user_token` creates on
demand as an ordinary **guest**, so it drew the guest allowances - 40/day and
60/month - and the post-deploy run's own searches spent them in a day. The
assistant then told the harness (and it would tell a real account) its
allowance was gone while Tavily had room and ani.mallya had used 2 of 80.
`_bind_search_identity` in `backend/core/auth.py` now treats any
`is_harness_id` as an operator with a 10 000/day and 2 000/month cap; the
shared pool (Tavily, 1 000/month, the ceiling that actually runs out) still
bounds everyone, and Brave (900/month, used 34) is the backup rung. **Verified
live on `90c028d`:** a fresh guest harness account binds as operator with the
high caps and searches (8 results), `sweep_journeys OK` with zero "used up"
refusals and `sources=8` on every search journey, and `exercise_search_scenarios
OK` (what's-on live, events offers links, try-again redoes the search, meter
reads 44/1000 Tavily credits). Note for a new month: the pool resets October 1.

## 2026-09-07 (later) — the momentary-state memory rule closes the gubacchi pollution; the vision functional tests assert on properties (DEPLOYED `560d643a`)

Continues the entry below it. Three changes, each verified against the real
models and, where it matters, the live system.

**A present-moment state is not a durable memory.** The 09-05 bird evening
stored "Ani is with Gubacchi" twice and read it back as if the pet bird were
a person. `prompts/memory/proposal.md` now states the general rule - who the
user is with, where they are, or what they are doing at this instant is
carried by the conversation and fills nothing; only stable, standing facts
do - pinned by four momentary-state cases in
`test_memory_capture_discipline.py`. **Verified live on the deployed system:**
"i'm with gubacchi" now proposes nothing, while "my dog is called Biscuit",
"I'm allergic to peanuts", and the spare-house-key arrangement still capture.
The three other pinned suites (scout-schedule referent, correction capture,
preference labelling) all pass (25). Sarcasm remains a documented, unfixed
ceiling: "yeah i'm going line dancing with a bird" is still captured, and no
phrasing rule is added for it, because a rule against a phrasing is the
overfitting the prompt header forbids. Re-measured 2026-09-08: no rule -> 6/6
captured; a general plan-and-joke principle -> 0/12 then 7/20 (unstable, so
nothing pins it deterministically), genuine line-dancing capture 8/8 either
way. That variance is the model ceiling, not the wording.

**The vision functional tests assert on properties.** The four tests in
`test_visual_observation_behaviour.py` had never run here - the test
container could not reach the vision runtime until `VISION_LLM_BASE_URL` was
set - and failed on exact phrasings the model does not use (it transcribes
"8 PM" as "p.m.", declines "no fish or biological subjects", and answers the
apple/device case in prose rather than the `identified_items` array). They
now assert on properties - a time is read, a species is refused, a covered
device is never given an exact make or model - so a reworded prompt survives
and a changed behaviour fails.

**The deployed 09-07 batch before this one (`50d973bd`) verified live:**
upload a bird photo captioned "this is gubacchi" → `analysis_names:
['gubacchi']` stored on the artifact, folded into the indexed memory, and
"do you know gubacchi?" recalls the picture (artifact within
`CANDIDATE_CEILING` distance, then `prefer_prompt_matches` narrows to it).

**Post-deploy checks are blocked by the search allowance, not by code.**
`sweep_journeys` passes; `exercise_search_scenarios` fails only because the
Brave search allowance is used up ("used up the search allowance for today",
`sources=0`), so the what's-on and try-again scenarios cannot search at all.
The old `printed map=True` event failure is gone; the events-format fix is
pinned by its functional test and cannot be walked end-to-end until the quota
resets. When it does, re-run the post-deploy checks and expect the events
check to pass.

**Next atomic task.** When the search allowance resets, re-run
`exercise_search_scenarios` to walk the events offer-links path end-to-end on
the deployed system. Separately open: the entity side of an unknown name
(gubacchi-as-person could recur if the name is heard in conversation with no
photo bound), and sarcasm in the memory classifier (documented ceiling).

## 2026-09-07 — events offer their links instead of printing them; the VLM records the names a user gives an upload (DEPLOYED `50d973b`; superseded by `560d643a` below)

Two fixes, both with functional tests on the real models.

**The events prose fallback offers links instead of printing them.** The
typed listing moved to offering the map/calendar/page links on 2026-09-05,
but the prose fallback (`prompts/reply/events_format.md`, used when the
search results could not be typed into the code listing) still printed
`Map: https://maps.google.com/?q=...` and `Hear it:`/`Details:` URLs, and
the link fence let the grounded map searches through — so
`exercise_search_scenarios` failed on **every deploy from 2026-09-06**
(`offers links=False, printed map=True`). `events_format.md` now says no
web address at all and finishes with the same offer the typed listing
uses ("Want the map, the calendar link, or the event page for any of
these? Tell me which and I'll send them."). `_apply_event_links`
(conversation_service.py) already degrades gracefully (`no_listing` → the
reply asks) so offering is honest on the prose path too.
`test_events_format_behaviour.py` now asserts the property: no printed URL,
an offer present.

**The VLM records what a user names an uploaded subject.** Gubacchi is the
operator's pet bird; the assistant once recorded the name as a person and
had no picture bound to it. Now `UploadInspectionDecision.names` (required
in the strict grammar — an optional field is a field the model skips) plus
an instruction in `prompts/vision/upload_inspection.md` capture the handles
the user gives in their request, even a made-up word like a pet's name and
even when the pixels cannot show it. The names are stored on the artifact
as `analysis_names`, folded into the embedded index text (semantic recall),
and matched exactly by `prefer_prompt_matches` (`_TEXT_FIELDS` now includes
`analysis_names`), so "do you know gubacchi?" can find the photo. Functional
`test_vision_naming_behaviour.py` 2/2 on the real VLM: a bird caption "this
is gubacchi, my pet bird" → `names` contains gubacchi and the observation
describes the bird; a caption with no name → empty. Unit tests in
`test_vision_provider.py`, `test_image_prompt_match.py`,
`test_vision_memory_indexing.py`.

**Gap fixed along the way:** the `functional-tests` compose service never
set `VISION_LLM_BASE_URL`, so `get_vision_provider()` fell back to
`127.0.0.1:8003` inside the container and **every vision functional test
silently skipped**. The serving services set it literally
(`http://animallya-spark2.local:8001`); the test service now does too, and
the vision tests actually run.

**Vision functional tests now run and pass.** The 4 tests in
`test_visual_observation_behaviour.py` had never run here — the test
container could not reach the vision runtime until `VISION_LLM_BASE_URL` was
set — and failed on exact phrasings the model does not use (proven identical
at HEAD `3595b03`). They now assert on properties and pass (see the
`560d643a` entry below).

**Gates:** unit suite 3222 passed (the one `test_agent_runs` claim test
races live agent workers — passes in isolation; same class as the
documented `test_run_answers` flake); routing gate 100 passed. Both
functional tests and the 57 vision unit tests pass.

**Next atomic task.** Deploy this batch, re-run
`exercise_search_scenarios` (expect the events check to pass now), then the
gubacchi *entity* side is separate: no gubacchi photo exists yet, so a
future upload of the bird with a naming caption is what binds the name to a
picture. The person-misclassification ("i'm with gubacchi" recorded as a
person) is still an open, wider issue and has no dedicated functional test
yet.

## 2026-09-05 (evening) — the events listing offers links instead of printing them; the follow-up delivers them (PUSHED `153ec73`, NOT DEPLOYED)

A weekend answer used to carry a row of links under every event. Now the
listing ends with one offer line and `send_event_links` delivers the map,
calendar and event-page links for exactly the events the person names, in
one follow-up. The Scout digest is untouched. Which events the person means
is resolved by the existing `pick_many` against the last listing this
conversation showed, kept per user in Redis (`last_listing_store`, 72h TTL)
as typed records; links are built by code (`backend/core/event_links.py`),
so the link fence still holds. Read-only, fast, withheld from a firing.

Measured: send_event_links 9/9 (evaluate_tool_selection 3 reps, floor 0.66);
functional/test_send_event_links_behaviour.py on the real model - router
sent "send me the links for the sunset session" to send_event_links, picker
resolved "the sunset session at potato head" with grounded links. Same commit
fixed the pre-existing red `test_tool_coverage_completeness`: `manage_runs`
had shipped with no TOOL_NAMES entry, cases, floor or `_ACTION_TOOL` mapping
(the exact gap the test catches); coverage added, measured 9/9, floor 0.66.
Unit: discovery + tools + reply suites 600 passed; two real-model functional
tests passed. Note: only the `send_event_links` and `manage_runs` routing
families were measured, not the whole matrix - re-run `evaluate_tool_selection
--reps 3` and the routing gate before raising `TURN_MAX_STEPS` to 3.

Diagram impact: NONE (no component added; the last listing rides the Redis
the app already reaches).

## 2026-09-06 (last) — the desk is the operator's; the paper book exists but is not armed (PUSHED, NOT DEPLOYED)

Continues the entry below it. Commits `5d02eac5`, `90871287`.

**One person's desk.** `MARKET_DESK_USER` (default `operator`) names
whose it is. The desk route answers 403 for any other user id whatever
its token, the Desk view and its sidebar entry render only for the
operator session, and the trading card carries the desk only for that
user. The card no longer asks for statements: the desk needs nothing from
the person, and a statement or journal only feeds the autopsy of past
trades, so `setup_needs` is empty and the status is idle either way.

**The paper book.** `backend/market/alpaca_trading.py` (paper endpoint
only; a non-paper base URL raises) and `desk/paper.py`. The rules are the
measured ones: every 20 sessions the book is brought to the desk's target
weights at the next open in whole shares; between rebalances the only
sale is a held name graded below B for 10 consecutive sessions; there is
no price stop, because every stop measured worse than none on every name;
moves under half a percent of equity are skipped; a session is planned
once. State lives in `data/market/paper/state.json` (rebalance clock, per
name run of C grades, starting equity, equity history). `market_daily
--paper-dry-run` prints the plan and the account; `--paper-trade` cancels
yesterday's unfilled orders and submits. Both are off by default and the
cron does not pass either.

**Proven, not armed.** The dry run against the real paper account read
equity 100,000 with no positions and planned nine buys (HPE 103, FTNT 31,
ANET 26, AAOI 21, PLTR 20, PANW 18, MRVL 10, SNDK 4, LITE 2). Nothing was
submitted. The Desk page shows the paper equity, cash, P/L since the
paper book started, the orders submitted and each position's open profit
or loss, whenever the record carries a paper entry.

**To arm it** (the operator's call): add `--paper-trade` to
`~/desk_daily.sh` on spark1 and put `APCA_API_KEY_ID` and
`APCA_API_SECRET_KEY` in that script's environment (the desktop reads
them from `.env`; spark1's checkout has no `.env`). The first live
session rebalances from cash into the nine names; after that it trades
about once a month plus exits.

**Next atomic task.** The deploy (mount, backend rebuild, gateway), then
arming the paper book if the operator says so, then a monthly
`--calibrate` line on the page.

## 2026-09-06 (later still) — the desk runs itself on spark1 (PUSHED; DEPLOY STEP PENDING)

Continues the entry below it. Commit `562cce2d`.

**Scheduled.** `~/desk_daily.sh` on spark1, in the crontab at 17:30
Eastern on weekdays: pulls origin/main into `~/deploy/anios`, then runs
`market_daily --refresh --brief-book --prune-days 30 --llm-url
http://127.0.0.1:8000 --llm-model deepseek-v4-flash` with the research
venv (CUDA hidden, so nothing touches vLLM's memory). It writes bars,
filings and any new release scores into a fresh partition, grades the
book, briefs every held name through the local model, writes
`data/market/desk/asof=<session>/desk.json`, and drops bar and filing
partitions older than 30 days (a day is about 12 MB; tone and desk
records are never pruned). The log is `~/desk_daily.log`. The first run
was started by hand on 2026-09-06 to prove the path.

**The one deploy step left.** `docker-compose.yml` now mounts
`./data/market/desk` read-only into the backend container, so once the
stack is rebuilt (`docker compose up -d --build backend` and the gateway
for the new frontend view) the Desk view at deep-matter.com reads the
records the cron writes. Until that rebuild the API answers `latest:
None` and the page says so. Not done here: it restarts the production
backend, which is the operator's call.

**Next atomic task.** After the deploy: open #desk, confirm the record
and the orders render; then the paper book on the operator's Alpaca
paper account behind an explicit `--paper-trade` flag, and live P&L on
the page from the account's positions.

## 2026-09-06 (night) — the Desk page, and the desk run for real (PUSHED, NOT DEPLOYED)

Continues the entry below it. Commits `4ddb4873` (pipeline and brief),
`cf937dc3` (ranks in the evidence), then the page.

**The desk ran end to end on real data.** `market_daily --refresh` pulled
95 bar series and 90 filings into `asof=2026-09-06`; the tone step scored
0 new releases because `prior_records` carried every earlier score
forward by accession; the desk ran; briefs for SNDK, CRWV and AAOI came
back from spark1's model (SNDK "own", CRWV "avoid", AAOI "own", each
citing the analysts by rank among the book); the record is at
`data/market/desk/asof=2026-09-04/desk.json` (the last session on file;
the run was on a Sunday).

**The operator's point: a printout is not a product.** What he acts on
is the change list and the book, so the page shows those. `backend/
market/deskrecord.py` diffs two records into upgrades, downgrades, the
orders that turn yesterday's book into today's (buy, sell, add, trim,
largest first) and the regime flags raised or cleared;
`GET /api/v1/market/{user}/desk` serves the latest record with its
summary, changes and sessions, `/desk/{session}` an earlier day; the
trading agent's card carries the session, the grade counts and the book
and opens the Desk view; `frontend/src/components/DeskPanel/DeskPanel.tsx`
renders the regime and flags, the orders at the next open, the book, every
grade with the four stances, and the brief per name, re-reading the record
every five minutes. Backend tests: `test_market_deskrecord.py`,
`test_market_desk_api.py` (including another user's token refused).
The frontend builds (`npm run build`).

**To deploy** (not done here): mount `./data/market` into the backend
container (the compose file only mounts `data/models`), rebuild the
gateway for the new view, and run `market_daily --refresh --brief <book>
--llm-url http://127.0.0.1:8000 --llm-model deepseek-v4-flash` on spark1
after the close (the research venv has curl_cffi, pyarrow and lightgbm;
spark1 is on Eastern time). Until then the record is written on the
desktop and the page reads it there.

**What comes next for making money with it**, in order: a paper book on
the operator's Alpaca paper account that places the page's orders at the
open (an explicit `--paper-trade` flag, off by default, so the track
record is real before any capital is), live P&L of that book on the page
from Alpaca positions, and a monthly `--calibrate` line on the page so a
grade that stops paying is seen.

## 2026-09-06 (night) — the 15-minute bars on entry days: fills and structure (NO CODE CHANGE)

Continues the entry below it. The last open intraday question, measured
on 9,968 entry days (grade A or better plus a dip or breakout trigger at
the prior close) across all 90 names with a full 15-minute session, from
the Alpaca bars in the store (scratch script `fill_study.py`).

**Fills.** Against the session VWAP: the open -1.1 bp, 10:30 -2.4, a
pullback to the 15-minute 21 EMA +1.4 (it happens on 83% of entry days
but sits above the open on down-gap days), a break of the first bar's
high +0.9, the close +2.5. On dip-entry days the first hour dips further
(10:30 is 3 bp under the open, the close 19 bp over it); on breakout days
nothing separates any fill. The 20-session return from every fill is
within noise of the return from the open (every t against the open below
1.1; the close on dip days is the one worse fill, t -1.9). Execution
timing on the entry day is worth a few basis points against an expected
move of 3.3% over 20 sessions: the backtest's next-open assumption stands,
and a 10:30 entry on dip days is the only thing worth doing differently.

**Structure as information.** Whether the entry day closed above its
15-minute 21 EMA: all entries +3.49% vs +3.01% over the next 20 sessions
(t 1.5); breakout entries +3.50% vs +2.91% (t 1.7); dip entries no
difference (t 0.0), and on dip days a close below the open is followed by
more (+3.99% vs +2.86%), the bounce not yet having happened. The
operator's read that the 15-minute trend lines are worth respecting is
mildly true on breakout entries and not on dips; at t 1.7 it does not
enter a rule. The 15-minute layer is closed: session features, the tape
encoder, fills and entry-day structure have all been measured.

**Next atomic task.** A desk narrative prompt with a functional test if
the operator wants the reasoning in words; otherwise the desk is complete
as measured, and the work is running it daily and re-calibrating monthly.

## 2026-09-06 (later) — the defaults now say what the backtests said (PUSHED, NOT DEPLOYED)

Continues the entry below it. The operator asked "have you implemented
your best solution given what you've learnt?" and the honest answer was
not yet: the defaults still encoded the beliefs from before the backtests.
Four changes, each measured after:

* **Backtest rules default to no price stop and a 10-session grade exit**
  (`backtest.Rules`), the set that measured best on every name; the
  variants list now starts from it and switches rules on, not off.
* **The book default is the top tenth at a 25% volatility target with a
  15% name cap** (`risk.BOOK_CONFIG`). Since 2021-06 on the 90 names:
  +31.6% a year, Sharpe 1.55, max drawdown -24.9% (the top fifth at 15%:
  +16%, 1.25, -16.5%; equal weight +41%, 1.28, -39%; SPY +14%, 0.85,
  -24.5%). `risk.size` rescales the engine's top fraction to the whole
  universe, since the engine only sees graded names: without that, "top
  tenth" meant three names on a day with 35 graded.
* **The fundamental analyst scores from whichever legs exist** (at least
  two of revenue growth, sequential growth, gross margin, acceleration), so
  a young filer like SNDK gets a view from its second quarter rather than
  its fifth.
* **Stances persist three sessions** before they change a grade
  (`opinions.persist`), which ends CRWD's daily B/C flicker on the
  rotation half-vote.

Calibration after all four: A+ 77 bp per 20 sessions (t 1.4), A 85 (t
1.7), B 10, C 18; 295 / 223 / 88 / 55 at 60; graded score rank IC 0.034
(t 2.3) at 20 and 0.052 (t 2.2) at 60. Persistence costs A+ some of the
first sessions after a release (102 → 77 bp) and buys a cleaner order.
Per-name backtests under the new defaults since 2021-06: the desk rules
are the best or near-best rule set on every name (AVGO +176% vs hold
+214%, MU +182% vs 252%, PANW +40% vs 171%) and still trail holding,
for the reasons in the entry below. Today's book: 9 names at the top
tenth (SNDK, ANET, PANW, AAOI, HPE and four A names).

**Next atomic task.** Whether the 15-minute bars improve the fill on an
entry day (next open versus a pullback to the 15-minute 21 EMA), the one
intraday question still open; then a desk narrative prompt with a
functional test, if the operator wants the reasoning in words.

## 2026-09-06 — entries, exits, the trade backtest, and what the book is worth (PUSHED, NOT DEPLOYED)

Continues the entry below it.

**Two more of the operator's claims measured.** His mean-reversion entry
(far below the short EMAs, near the lower Bollinger band) pays at one
week among qualified names: more than 8% below the 21 EMA +1.2% in 5
sessions (t 3.5, hit 0.58), below the lower band +0.9% (t 2.6), below the
band while the AI basket falls +2.1% (t 4.3, hit 0.62); by 20 sessions the
dip edge is gone and strength pays instead (more than 8% above the 21 EMA
+2.0%, t 2.6). Dips are entries, trend is the hold. And a learned model
does not beat the fixed grade: walk-forward LightGBM on every desk feature
(analyst ranks, levels, stretch, Bollinger, momentum, regime) gives
out-of-sample IC 0.006 (t 0.4) against 0.035 (t 2.1) for the grade on the
same sessions; it ranks tone, fundamentals and momentum highest and fits
noise after that. Reinforcement learning was asked about and declined for
the same reason: one path of 90 correlated names is not many episodes.

**The entry analyst and the trade backtest.** `desk/entry.py` (dip and
breakout triggers), `desk/backtest.py` (enter at the next open on A or
better plus a trigger, sized by grade and exposure; exit on a support stop
or a chandelier ATR stop or after N sessions below B; 10 bp a side;
variants switch each rule off), `market_desk --backtest MU NVDA --since
2021-06-01` and `--book-backtest`. **Result, on eight names since 2024 and
six since mid-2021: every per-name timing rule trails holding the name,
and the stops are the worst part** (AVGO since 2021: support stop +118%,
chandelier 3 ATR +40%, no stop with a slow grade exit +173%, hold +214%;
NVDA: +104% / +122% / +138% / +265%; PANW: -10% / +10% / +80% / +171%).
Hit rates 30-60%. The best rule set everywhere is no price stop and an
exit only after 10 sessions below B; even that trails buy-and-hold because
the first A grade arrives late (fundamentals need a year of filings: SNDK
entered 2025-11, CRWV never) and the position is out a third of the time.

**The book.** The graded scores through the sizing engine on the 90
names, monthly rebalance, no stops, since 2021-06: top 20% at a 15% vol
target +16.1% a year, Sharpe 1.25, max drawdown -16.5%; top 10% at 25%
vol +30.9%, Sharpe 1.55, -20.2%; equal weight of all 90 names +40.9%,
Sharpe 1.28, -38.7%; SPY +14.3%, 0.85, -24.5%. The daily equal weight of
A-or-better names +47.3% (Sharpe 1.22) against C names +42.0% (1.33): in
raw terms the grades barely separate, because these names' returns were
the AI theme, and the grade's measured edge (100 bp per 20 sessions,
beta-adjusted) is small next to a 40%-a-year drift. What the desk adds is
risk: a third of the drawdown at a similar Sharpe. That is the honest
"hedge-fund implementation" on this history: own the theme, size by risk,
rebalance monthly, exit on the grade, never on a price stop.

**Next atomic task.** Hysteresis on stances; the per-name backtest on the
book's 20-session clock; then whether the 15-minute bars improve the fill
on an entry day (enter at the next open versus a pullback to the 15-minute
21 EMA), which is the only intraday question still open.

## 2026-09-05 (later) — trade location; the technical analyst rebuilt on it (PUSHED, NOT DEPLOYED)

Continues the entry below it. Commits `19a45009` (history), `34bd4af0`
(levels), then the veto.

**The operator's objection** was that the grades ignored technical
analysis as he practises it: location between support and resistance,
multi-timeframe agreement, reward-to-risk. The prior technical analyst
scored momentum and stretch only, because EMA slopes and candles measured
nothing as cross-sectional rankers. That was the wrong test. The right one
is trade quality among names that already qualify on fundamentals and
release tone, including entry risk. `backend/market/levels.py` computes
confirmed swing lows and highs (strictly the extreme of five bars either
side, stamped when confirmed), support as the nearest of those and the
daily 50/200 and weekly 21 EMAs below the close, resistance as the nearest
swing high above, reward-to-risk, position in the 60-session range, weekly
and daily trend, and a confluence count. Measured on the 90 book names
among qualified names, beta-adjusted, next 20 sessions, with the maximum
adverse excursion inside the window: weekly trend up +1.0% (t 4.2) against
-2.0% when flat; daily trend up +0.9% (t 3.3); top of the 60-session range
+1.3% (t 3.7, hit 0.56) against -0.5% at the bottom; more than 15% above
support earns nothing with a -12% adverse excursion against -7.6% at
support (support is an entry-risk fact, not a return fact); reward-to-risk
from swing levels inverts (RR < 1 +0.7%, t 2.3: resistance close overhead
means breakout on these names). The technical analyst now blends weekly
trend, daily trend, momentum and the negative of stretch (falling theme)
or range position (rising theme).

**Calibration after it** (`market_desk --calibrate`): A+ 102 bp per 20
sessions (t 1.9) and 343 per 60 (t 2.3, from 258); graded score rank IC
0.031 (t 2.1) at 20 and 0.050 (t 2.3) at 60. **The veto**: a bearish core
analyst caps the grade at B, which lifts A from 17 to 53 bp per 20
sessions and removes the losing case (IREN, January 2026: bullish release
and tape over bearish filings, then -22% and -26%).

**Per-name history** (`market_desk --history SNDK MU --since 2026-01-01`)
prints every grade change with the stances, the regime multipliers, the
next 20 sessions raw and beta-adjusted, earnings reaction days marked, and
a hold-while-graded backtest against buy-and-hold and SPY. 2026: SNDK A+
every session (+184% held, SPY +12.5%); MU A+ 107 sessions averaging
+14.7% (hit 0.80) against B sessions -8.9%; CRWV C all year (-4.6% on C
sessions); CRWD flickers between B and C daily on the rotation half-vote.
Two things still to do there: stances need hysteresis (a view must persist
before it changes a grade), and the per-name backtest switches daily where
the book rebalances every 20 sessions.

**What quant desks do with the same reads** (for the operator's question):
moving-average distance (21 vs 200 day) predicts the cross-section with
~9% annual alpha beyond momentum and the 52-week high (Avramov, Kaplanski,
Subrahmanyam 2021); the 52-week high is an anchor (George and Hwang 2004);
Lo, Mamaysky and Wang (2000) found chart patterns and levels carry
information when detected mechanically; Osler (2000) found bank-published
support and resistance levels in FX predict intraday reversals. None of
them trade levels by eye: every one is a feature measured in a
cross-section, which is what `levels.py` now is.

**Next atomic task.** Hysteresis on stances (persist N sessions), then
re-run `--calibrate` and the four histories; then the per-name backtest
on the book's 20-session rebalance clock.

## 2026-09-05 (night) — the book is AI and software only; the desk (PUSHED, NOT DEPLOYED)

Continues the entry below it. Commits `9a5aaac1` (merged as `4764b76b`)
→ the technical switch.
Another agent is committing to this repository; files are added by name.

**The operator narrowed the book** to the AI-infrastructure and software
names he watches. `universe.book_sides()` returns 90 of them (every
overlay name plus the index's semiconductor, communications-equipment and
software sub-industries; utilities that only carry the power theme via the
index mapping are out), each tagged `ai` or `software`. The rest-of-
universe release batch on spark1 was killed for it (it was eight parallel
model calls against the assistant's own vLLM); the themed batch had
finished (3,896 releases, 382 min) and its partition is copied to the
desktop store (`edgar_tone/asof=2026-09-05`, 176 names).

**The desk** (`backend/agents/trading/desk/`, `python -m
backend.cli.market_desk --calibrate --brief SNDK`): fundamental, technical,
sentiment, regime and risk modules, each an `Opinion` (score, stance,
evidence) on the book's panel; a fixed grade rule (A+: bullish release and
agreement; A: agreement; B: one voice; C: none or split) with size
multipliers 1 / 0.75 / 0.5 / 0; `desk.calibrate` re-measures the grades.
Measured on the 90 names, beta-adjusted: A+ 102 bp per 20 sessions (t
2.0), A 26, B 24, C 15; at 60 sessions monotone, 283 / 173 / 105 / 59
bp (A+ t 1.9); the graded score's rank IC 0.035 (t 2.3) at 20 against
the composite's 0.025 (t 1.8) on the same names. Today: 6 A+,
11 A, 19 B, 54 C; book gross 0.30 (LRCX, NTAP, PANW, ANET, FN, AVGO,
AAOI). SNDK is B (fundamentals bullish, technical and tone neutral), CRWV
and IREN are C.

**What the regime analyst measured.** Software and AI residual baskets
were +0.19 correlated daily over the decade (+0.35 in 60-day windows, 7%
of windows negative) and -0.37 in 2026, -0.52 in the latest window: the
"inverse correlation" is a 2026 regime, so the analyst carries a novelty
z-score on the six theme baskets' co-movement structure (today +4.8) and
flags a change of shape rather than assuming one. Participation (20-day
dollar volume against the year, AI basket median) gates everything: tone
IC 0.033 (t 2.2) above the median vs -0.004 below; following the
60-session AI-vs-software leader 0.086 (t 3.0) vs -0.007; the composite
0.049 (t 2.3) vs -0.002 by software participation. After the top
participation quintile the AI basket lags SPY by ~1.2% over 20 sessions,
after the bottom it leads by 1.1%. So selection confidence is 0.5 below
the median (rotation withheld) and exposure 0.75 in the top quintile.
Today participation is at its two-year low (pct 0.00), confidence 0.5.

**The technical analyst switches playbook.** Over the decade the 21-EMA
fade pays only while the AI basket's 60-session return is negative (IC
+0.082, t 2.5; -0.006 while rising), proximity to the 52-week high pays
only while it is rising (+0.042, t 2.3), momentum 120/21 holds in both
and is strongest in low participation (+0.074, t 2.6). The first build
(momentum plus fade) lost through the rising basket of 2024-2025
(-0.057 on 2024-2026); it now fades stretch in a falling theme and buys
strength in a rising one. The operator's EMA slope and stack reads
measured nothing over the decade and paid only in the low-correlation
regime of 2026 (+0.066 to +0.072, t 2.0, 35 windows): cited as
evidence, not scored, until that regime has history. Buying near the
200 EMA lost in every regime (-0.023; -0.082 on 2024-2026).

**Beta-label model rows** (`sweep_beta.tsv`): lgbm alpha h20 0.008, +
technical h20 0.010 / h60 0.016, + calendar 0.007, + macro 0.005, all
t < 1. Chart CNN (plain residual) h20 -0.001, h5 -0.012 (t -2.2). Nothing
learned beats the tone. The tape encoder (15-minute bars, `tape_h5`/`tape_h20`,
beta label) measured 0.004 (t 0.4) and -0.004: nothing. Balance-sheet
instants on the
full universe: buybacks 0.002, asset growth -0.015 (t -1.7, growth names
pay here), book-to-market 0.007; none entered the composite.

**Next atomic task.** The desk's sentiment stance is coarse (the reader
returns -1/0/1 per field, so ties leave SNDK neutral on a +1/+1 release):
add `tone_pricing` and `tone_supply_constrained` as tie-breaks and
re-measure with `--calibrate`. Then a functional test for a desk
narrative prompt if one is added (none yet: the desk is numeric). Then the
intraday controls on the 90 names measured zero on every session feature;
the 15-minute layer is closed unless a new idea comes with a number.

## 2026-09-05 (late) — beta was the signal; the calendar, the macro state, the tape (PUSHED, NOT DEPLOYED)

Continues the three entries below it. Commits `bc20418d` → `02a51e00`.
Another agent is committing to this repository and editing the security
agent in this checkout; files are added by name only.

**The correction that matters most (`9dbe052d`).** The harness scored
rankings against own return minus the benchmark's, and the models trained
on the same label. In a market that rose most years that pays high-beta
names for the market's drift. Beta-adjusted (own minus 120-session rolling
beta times the benchmark, beta known at t, now the default in
`evaluate_scores` and the model label): distance above the 52-week low
0.045 (t 2.8) → 0.005 (t 0.3); high volatility 0.037 → -0.017; the
fundamental blend 0.026 → 0.021 (t 2.3); the 21-EMA fade 0.027 → 0.024
(t 1.7, 20 sessions only); **the release-tone blend 0.063 → 0.044 (t 3.0)
at 20 sessions and 0.076 (t 3.8) at 60**. The book's composite drops the
52-week-low leg and adds the tone where a name has scored releases: rank
IC 0.032 (t 3.1), book Sharpe 1.05 vs 0.84, max drawdown -6.8%. Sweep
rows now go to `sweep_beta.tsv`; `sweep.tsv` (plain residual, full
cross-section) and `sweep_themed_only.tsv` are history. The full-cross-
section model rows measured on the plain residual before the change:
lgbm alpha h10 0.001 / h5 -0.001 / h60 0.024; lgbm +edgar h20 0.003;
lgbm +technical h20 0.019 (t 1.1) / h60 0.033 (t 1.2); mlp alpha h10
-0.002 / h5 0.011; mlp +edgar h20 -0.005; mlp +technical h20 0.010;
xsect alpha h10 0.008; lgbm +calendar h5 0.005 / h20 0.003. Nothing
learned beats the tone blend or the composite; the remaining GPU rows
(master, chart CNN h20/h5) append to `sweep.tsv` as the old process
finishes, and every model row is due a re-run under the beta label
(`--only ...` into `sweep_beta.tsv`).

**The calendar** (`backend/market/calendar.py`, FOMC dates committed):
over 94 decisions the index drifts up into the meeting (day -1 +24 bp, t
1.9), high-vol minus low-vol names +41 bp (t 2.4) on the decision day, AI
basket +32 bp (t 1.9) then -29 bp on day +2 and +32 bp on day +3. Quad
witching -41 bp (t -3.1), monthly expiry -13 bp (t -2.2), the Russell day
50% more volatile; turn of the month faint; December and January nothing.
**The macro state** (`macro.py`: VIX level, change and ratio to realised,
10-year yield and change, dollar, oil; series stored via `market_snapshot
--tickers "^VIX,^TNX,DX-Y.NYB,CL=F"`). Both enter every gate's market
vector and the "calendar"/"macro" feature layers.

**Other documented anomalies as controls (plain residual, then beta):**
low volatility and low beta are *negative* here (high vol +0.037 plain,
-0.017 beta-adjusted: beta); illiquidity within the index +0.015 →
+0.021 (t 2.6), plausibly survivorship of small survivors; anti-lottery
nothing. **Balance-sheet instants** (`02a51e00`): share issuance, asset
growth and book-to-market are parsed point in time; the desktop EDGAR
partition is being refetched to carry them (old one set aside as
`old-asof=2026-09-05`), controls to follow.

**The 15-minute tape.** Alpaca keys in `.env`; `market_intraday
--refresh` running for the universe (~30 s a name). Preliminary on 198
names, beta-adjusted, 20 sessions: bars above the 15-minute 9 EMA (5-day
mean) IC 0.029 (t 1.6), trending tape 0.026 (t 1.5), calm tape 0.015 (t
1.6, net Sharpe 0.58); at 5 sessions every strength measure is mildly
negative (reversal). The tape encoder (`tape.py`, encoder "tape",
`bc20418d`) recovers a planted intraday pattern in its test and runs
(`tape_h5`, `tape_h20`) once the fetch completes.

**Release batch:** ~90 of 109 themed names scored on spark1; the rest of
the universe since 2020 is queued (`~/run_tone_rest.sh`). Tone frames on
the desktop are a copy from the 51-name stage; copy again before
measuring.

**Next atomic task.** When the batch completes: copy `edgar_tone` from
spark1, rerun the tone controls on all names (beta-adjusted), then
`market_sweep --only lgbm_macro_h20,master_macro_h20 --device cuda` plus
tone-inclusive runs, into `sweep_beta.tsv`. When the intraday fetch
completes: the intraday controls on all names and `tape_h5,tape_h20`.
When the EDGAR refetch completes: controls for share issuance, asset
growth and book-to-market, and the CPU LightGBM rows under the beta label.
Whatever beats the composite's 0.032 (t 3.1) beta-adjusted becomes the
book's score.

## 2026-09-05 (afternoon) — the trader's toolkit measured, a measurement bug fixed, the tape arrives (PUSHED, NOT DEPLOYED)

Continues the two entries below it. Commits `0fd59012` → `bc20418d`,
gated on spark1. Every number was produced by running the code.

**A bug in my own measurement, fixed in `dc8f8bdc`.** The two theme
baselines fed to every model as features are NaN for untagged names (right
as controls), and the model's eligibility mask requires every feature
finite, so every learned model in the night's sweep trained and scored on
~96 themed names while the momentum reference beside it used 532. The
model rows in the previous entry's table are void as comparisons (kept as
`data/market/models/sweep_themed_only.tsv`). Untagged names now carry the
market series for those two inputs (506 eligible names per session); the
sweep table has a `names` column. The controls, the fundamental blend, the
technical features and the book were never affected. Re-measured so far on
503 names (rank IC, 10 bps): lgbm alpha h10 0.001, h5 -0.001, h60 0.024 (t
0.75); lgbm alpha+edgar h20 0.003; lgbm +technical h20 0.019 (t 1.12), h60
0.033 (t 1.22); mlp alpha h10 -0.002. Remaining rows (mlp h5, mlp edgar,
mlp technical, xsect, master, chart CNN h20/h5) append to `sweep.tsv` on
the desktop as the run completes.

**The trader's toolkit** (`backend/market/technical.py`, 33 features: EMA
9/21/50/200 and SMA 200 distances and slopes, stack order, crossovers,
weekly EMAs, 52-week high/low, candles, EMA spreads with slope-change
"converging" flags, the normalised MACD family), each alone through the
harness on 532 names since 2015:

| feature as the ranking | h | rank IC | t | net Sharpe |
| --- | --- | --- | --- | --- |
| distance above the 52-week low | 20 | 0.041 | 2.60 | 1.05 |
| distance above the 52-week low | 60 | 0.084 | 3.45 | 1.23 |
| extension above the 21 EMA (a fade) | 5 | -0.022 | -2.79 | -0.94 |
| 9/21 cross up within 5 days | 5 | -0.007 | -1.79 | -2.10 |
| 50/200 golden cross within 5 days | 5 | -0.007 | -2.91 | -0.71 |
| 21/50 converging (slope turning) | 20 | 0.011 | 0.94 | -0.05 |
| candles, MACD family, trend stack | any | ~0 | | negative |

The 52-week-low distance is positive in every sub-period (0.036, 0.025,
0.030, 0.055) and in both full-history and later-listed names. EMAs carry
information as levels price returns to, not as trend confirmation; the
crosses lose; the slope-turning flags are small and positive at 20 days.

**The composite** (fundamental blend + 52-week-low trend + 21-EMA fade,
`market_book --score composite`, now the default): rank IC 0.047 (t 3.73),
hit 0.65, net Sharpe 1.06 at h20; the book Sharpe 1.08 vs 0.92 benchmark,
max drawdown -8%. SanDisk ranked 1.00 on it through its July pullback to
the 200 EMA at $1,016 (the operator's example), the 21/50 convergence flag
was on from 08-27 and the cross came 09-04 with the 12% day; across all
names that flag raises P(>8% in 3 sessions) from 2.3% to 3.0%.

**Rotation from filings** (`market_rotation`): each theme's median
fundamental blend as every member's score has rank IC 0.049 (t 2.39, net
Sharpe 0.48) at h20 while theme price momentum is -0.036 on the same
sessions. As of 09-04: memory-storage revenue growth 35% and accelerating
fastest, networking 32%, ai-compute 29%, software 19% flat, power-cooling
10% decelerating.

**The release reader, first reading** (51 themed names scored at the time,
`edgar_tone` frames synced to the desktop): tone_guidance h20 IC 0.054 (t
3.68) net Sharpe 0.74; guidance change 0.052 (t 3.93); tone blend
(guidance, demand, change) 0.062 (t 4.24) net Sharpe 1.10; the fundamental
blend on the same names 0.028 (t 1.35). Capex and supply commentary carry
nothing alone. The strongest signal so far; a ~40-name cross-section, to be
re-measured when the batch completes (74 of 109 themed names stored on
spark1 at the time of writing; the rest of the universe since 2020 is
queued behind it, `~/tone_rest.log`).

**Alpaca 15-minute bars** (`backend/market/alpaca.py`, `market_intraday`;
keys in `.env`): the free IEX feed serves 15-minute bars back to 2016.
Ten session features (VWAP trend, first/last hour, reversal, bars above the
15-minute 9 EMA, EMA crosses as chop, range position, volume front-load);
SanDisk's 12% day reads as a clean trend day, its +5% day of 08-31 as chop
(9 crosses). The universe fetch is running on the desktop
(`E:\AgentWorkspace\tmp\intraday_refresh.log`, ~30 s per name, ~4 h).

**The tape encoder** (`backend/market/tape.py`, encoder "tape"): the
26-slot tape of each session (time-slotted, gaps flat with zero volume,
relative to the open) for the last five sessions through 1-D convolutions,
the daily window through an MLP, merged and attended across names. A
planted intraday pattern is recovered out of sample in the test. Sweep
runs `tape_h5` and `tape_h20` wait on the fetch. Torch encoders now train
one padded batch per step (`1d001b71`).

**Next atomic task.** When the fetch finishes: run
`scratchpad/intraday_controls.py`-style controls (kept in the session
scratchpad; re-derive from `alpaca.FEATURE_NAMES`) and `market_sweep
--only tape_h5,tape_h20 --device cuda`. When the batch finishes: rerun the
tone controls on all 109 names, then `market_sweep` with
"alpha+edgar+technical+tone" for lgbm/mlp/xsect at h20, then put whichever
score wins the harness into `market_book`. Then a point-in-time universe
remains the honesty gap (survivorship).

## 2026-09-05 (day) — filings are the signal: the EDGAR layer, the book, and the release reader (PUSHED, NOT DEPLOYED)

Continues the entry below it. Commits `96ee4e6f` (EDGAR layer), `2fc6610e`
(sizing), `67f1bf2f` (release reader); every one gated on spark1, the last
with its functional test against the real DeepSeek. Every number here was
produced by running the code.

**The night's sweep, completed.** Fourteen price-only configurations and
six with filing features, every encoder and horizon: nothing beats the
plain controls. Full table in `data/market/models/sweep.tsv` on each
machine; the six filing-feature rows: lgbm h20 0.013, mlp h20 0.008, xsect
h20 -0.008, lgbm h60 -0.044, mlp h60 -0.014, master h60 -0.010 (rank IC).
The models keep losing to a hand-built ranking of the same columns.

**The EDGAR layer** (`backend/market/edgar.py`, `market_edgar --refresh`,
546 names in 7 min, ETFs fail by design): 8-K item 2.02 events with
acceptance timestamps (after the New York close → next session), XBRL
company facts kept as the earliest-filed value per period (restatements
never leak backwards), fourth quarters derived from the year, the tag with
the most quarters chosen per fundamental. Fifteen point-in-time features:
sessions since a release, the reaction-window residual return (the drift
signal), revenue yoy / qoq / acceleration, EPS change, margins, capital
intensity, staleness, presence indicators; neutral fills keep foreign
filers in the cross-section. Stored as immutable `edgar_events` and
`edgar_facts` frames (store.write_frame/read_frame).

**The first cost-positive signal on this universe.** Controls through the
unchanged harness, 532 names, 10 bps:

| control | horizon | periods | rank IC | t | net Sharpe |
| --- | --- | --- | --- | --- | --- |
| post-earnings drift (recent) | 20 | 146 | 0.002 | 0.34 | -0.10 |
| revenue yoy | 20 | 146 | 0.027 | 2.46 | 0.60 |
| revenue qoq | 60 | 48 | 0.025 | 2.24 | 0.65 |
| gross margin | 20 | 146 | 0.020 | 1.96 | 0.53 |
| **fundamental blend** (yoy, qoq, gross margin, acceleration) | 20 | 146 | **0.029** | **3.07** | **0.66** |
| fundamental blend | 60 | 48 | 0.039 | 2.63 | 0.71 |

Post-earnings drift is absent (as the literature says for large caps since
2015); fundamental growth is present. **Caveat, measured:** the blend's IC
was 0.049 (t 2.94) in 2015-2018, 0.041 in 2019-2021, -0.002 in 2022-2024,
0.007 (t 0.34) in 2025-2026. Part regime (the 2022 growth-to-value
rotation), part survivorship (today's index over-represents the names that
were growing a decade ago). It is the best signal on file and its recent
evidence is thin; both are true.

**Sizing** (`backend/market/sizing.py`, `market_book`): select the top
fraction, inverse-volatility weights with a 10% volatility floor (a name
pinned by a pending takeover read as 3% vol and would have taken the whole
cap), name and theme caps with excess redistributed, a volatility target
measured on the book's own trailing returns under the candidate weights
(the diagonal estimate ignored market correlation and let realised vol
reach 39%), and turnover control where an exit is always a full trade
(skipping small sales let stale positions accumulate to 2.7x gross). Six
tests including the two properties the report exposed. On the fundamental
blend, long-only, 15% target, 10%/40% caps, 20-session rebalance, 10 bps:
**Sharpe 1.02 vs benchmark 0.83, max drawdown -15%, turnover 16% per
rebalance**; the tighter book (top 10%, 20% target) Sharpe 0.92, drawdown
-27%. Today's book: SanDisk rank 1.00 and CoreWeave 0.82 enter at ~0.3%
each — their realised volatility (137%, 102%) is seven times the median
name's, which is the honest size at equal risk; IREN (rank 0.02, annual
facts only as a foreign filer) is not selected.

**The release reader** (`prompts/trading/release_tone.md`,
`backend/agents/trading/release_tone.py`): DeepSeek scores what a company
states about its outlook, demand, pricing, capex and supply constraint,
bounded, greedy. Functional test 4/4 on the real model (raised outlook
positive on all four; a cut negative; facts-only exactly 0 guidance;
deterministic). A first-draft instruction returned zeros for text with
explicit guidance — the prompt exists because of that.
`backend/market/language.py` finds the EX-99.1 through the filing index
page, stores `edgar_tone` frames, resumes from partials, and builds
point-in-time tone features (scores + change vs the previous release).
`market_tone --refresh` runs it; feature sets compose as
"alpha+edgar+tone".

**In flight:** the scoring batch for the 109 themed names, all years, on
spark1 (`~/tone_themed.log`, frames under
`~/deploy/anios/data/market/edgar_tone/asof=2026-09-05/`), ~4 hours at
four threads (~3 s per release effective; ~7k tokens each). Then the rest
of the universe since 2020 is the next batch. The desktop store has tone
frames only for CRWV and SNDK.

**Next atomic task.** When the batch has enough names: copy spark1's
`edgar_tone` partition to the desktop store, run the tone columns as
controls through `evaluate_scores` (guidance, guidance change, demand,
capex, supply) at 20 and 60 sessions, then the blend plus tone, then the
learned models on "alpha+edgar+tone". Anything that beats the fundamental
blend's 0.029 / 0.66 row on the same sessions replaces it as the book's
score in `market_book`. Then a point-in-time universe is the remaining
honesty gap (survivorship); free sources do not give delisted prices.

## 2026-09-05 — the market research system: measured end to end, and what the measurements say (PUSHED, NOT DEPLOYED)

Everything below was produced by running the code. Commits `1e4970de` →
`00ebf082` on main; the spark1 gate passed on `90b40e5c` (36 passed, 1
skipped: the model test skips without torch, by design). The operator was
asleep for the second half of this; nothing was asked, everything is here.

**What exists now, all in `backend/market/` and `backend/cli/market_*`:**
a Chrome-impersonating Yahoo fetch (Yahoo refuses by TLS fingerprint, not
IP) with corporate actions and the live session dropped; an immutable
as-of parquet store (`data/market/`, on this desktop and on spark1 at
`~/deploy/anios/data/market`, 546 names since 2015); a 546-name universe
(current S&P 500 with GICS tags + AI-infra/memory/networking/power/software
overlay + 15 sector ETFs); the aligned panel with theme baskets; 8 raw
channels and 31 causal multi-scale features (`alpha.py`); five baselines;
a walk-forward harness (rank IC against residual return, purged folds,
cost-charged long-short); a ranker with five encoders (mlp, gru, xsect =
attention across names, master = market-gated MASTER-style, lgbm) with
rank labels and seed ensembles; and a sweep CLI that appends one row per
run to `data/market/models/sweep.tsv` beside momentum on the same
sessions. 57 market tests, ruff/black clean.

**Research (through September 2026).** The Qlib leaderboard's best daily
rankers reach rank IC 0.05-0.067, rank ICIR ~0.45, on Chinese A-shares with
158-360 engineered inputs at a one-day horizon; the gains come from wide
inputs, market-gated attention within and across stocks (MASTER, AAAI-24;
StockMamba 2026 +15% rank IC over MASTER; ACT 2026), rank-aware losses
(LambdaRankIC 2026) and ensembling. Time-series foundation models
(TimeGPT, Chronos-2, TimesFM-2.5, Moirai-2) were evaluated on US equities
in June 2026: gains over a random walk "small and sparse". LightGBM remains
the tabular reference every deep model is judged against.

**Results, 532 ranked names, 2015-01-02..2026-09-04, 10 bps per unit
traded, top/bottom 20%, all through the same harness:**

| run | horizon | periods | rank IC | t | net Sharpe |
| --- | --- | --- | --- | --- | --- |
| momentum 12-1 (reference) | 10 | 213 | 0.015 | 0.95 | 0.15 |
| mlp, raw channels | 10 | 213 | 0.015 | 1.01 | 0.12 |
| gru, raw | 10 | 213 | -0.005 | -0.35 | -0.27 |
| xsect, raw | 10 | 213 | 0.012 | 0.79 | -0.36 |
| mlp, alpha, rank label | 10 | 213 | 0.018 | 1.30 | -0.26 |
| lightgbm, alpha, rank | 10 | 213 | 0.002 | 0.10 | -0.67 |
| master, alpha, rank | 10 | 213 | -0.005 | -0.29 | -0.70 |
| xsect, alpha, rank | 10 | 213 | -0.001 | -0.08 | -0.63 |
| momentum 12-1 (reference) | 5 | 425 | 0.020 | — | 0.09 |
| lightgbm, alpha, rank | 5 | 425 | -0.003 | -0.21 | -0.92 |
| mlp, alpha, rank | 5 | 425 | 0.017 | 1.59 | -0.10 |
| xsect, alpha, rank | 5 | 425 | 0.013 | 1.01 | -0.30 |
| master, alpha, rank (spark1, CPU) | 5 | 425 | 0.012 | 0.88 | -0.44 |
| mlp, alpha, rank, 3 seeds, hidden 32, wd 1e-2, train 1250 | 5 | 325 | 0.018 | 1.32 | -0.68 |
| xsect, alpha, rank, 3 seeds, hidden 32, wd 1e-2, train 1250 | 5 | 325 | 0.013 | 0.92 | -0.61 |
| lightgbm, alpha, rank | 20 | 107 | 0.003 | 0.14 | -0.53 |
| master, alpha, rank (spark1) | 20 | 107 | -0.014 | -0.64 | -0.73 |
| mlp, raw (spark1) | 20 | 107 | -0.006 | -0.30 | -0.51 |
| lightgbm, alpha, rank | 60 | 34 | 0.018 | 0.38 | -0.03 |
| mlp, alpha, rank | 60 | 34 | -0.072 | -1.98 | -0.63 |
| master, alpha, rank | 60 | 34 | -0.033 | -0.84 | -0.46 |

Full rows with hit rate, net per period and cost: `data/market/models/
sweep.tsv` on each machine (the LightGBM h10/h20 rows there show NaN IC
from before the harness fix; recomputed from their saved scores above).

No encoder, feature set, label or horizon beats the reference on the
same sessions, and at sixty sessions the fitted models are *inverted*
out of sample (the relation learned in each training window flips in its
test window: regime dependence, on 34 periods). **The positive control explains why.** Run through the unchanged
harness on the same panel:

| known effect | horizon | periods | rank IC | t | Sharpe @0 bps | @10 bps |
| --- | --- | --- | --- | --- | --- | --- |
| 1-day reversal | 1 | 2934 | 0.016 | 4.65 | 0.42 | -3.90 |
| 5-day reversal | 5 | 586 | 0.024 | 3.16 | 0.66 | -0.04 |
| 10-day reversal | 5 | 585 | 0.018 | 2.40 | 0.38 | -0.12 |
| theme reversal (20d) | 10 | 291 | 0.030 | 2.07 | 0.14 | -0.07 |
| theme momentum (60d) | 60 | 47 | 0.054 | 1.56 | 0.39 | 0.36 |

The pipeline sees the effects the literature says are there. They live at
one to five sessions (reversal, significant, eaten by cost at full
rebalancing) and at one to three months (theme rotation persists, too few
periods yet to be significant). At ten sessions the two cancel, and that is
where every model was trained. **Structure exists; the label horizon was
wrong.**

**In flight at shutdown (results append to `sweep.tsv` on each machine):**
desktop 5080: done, every row above. spark1, CPU only
(`CUDA_VISIBLE_DEVICES=` — torch 2.14's AdamW touches the accelerator even
for CPU tensors and the GB10 has no free memory beside vLLM): master h20,
h5, and the 3-seed ensemble at h10 (`~/sweep_spark1_cpu2.log`,
`~/deploy/anios/data/market/models/sweep.tsv`): only the 3-seed master
ensemble at h10 is still running there. Read that table first.

**Next atomic task.** Read the h5 and h60 rows. If a model beats the
reversal control at h5 or the theme-momentum control at h60 net of cost,
that is the model; build position sizing on it (volatility-targeted, theme
exposure budget, turnover-aware so reversal is not traded at full
rebalance). If nothing does, the next lever is information the price
series does not hold: a scheduled DeepSeek pass turning earnings calls,
hyperscaler capex guidance and memory-pricing news into dated features on
the same calendar (`model.build_features` takes any (T, N, K) array).
Second lever, cheap: batch several sessions per step with padding masks —
the per-session Python loop keeps the 5080 at 10-13% utilisation.

## 2026-09-06 — Cross-chat continuation and unsupported media (DEPLOYING)

See `docs/CHANGELOG.md`, this date. Codex should review
`backend/services/cross_chat.py` and `_history_for_routing`, and the media
branches in `backend/workers/imessage_chat.py`.

**VERIFIED (unit):** `test_cross_chat_and_media.py` 7 and the suites around
them 199. **VERIFIED on the real router:** `test_cross_chat_followup_behaviour.py` 3/3, including the control without the room turn.

**Deploy:** this batch and everything since `8116e7d2` (the deployed marker)
goes out through `scripts/deploy.sh` on the Spark from this session, with
`AGENT_RUNS_ENABLED`, `AGENT_EXPERIENCE_REVIEW_ENABLED` and
`AGENT_EXPERIENCE_REVIEW_HOUR_UTC` added to the Spark `.env` first.
Deploy #1 failed its unit gate on a stale listing test (opencode's
events-links change; fixed). Deploy #2 passed both gates, backed up,
migrated and restarted; its post-deploy sweep died because the backend was
recreated mid-sweep to stop the hand-off's texts (below); the marker was not
written but the code is live. Deploy #3 <<DEPLOY3_RESULT>>

**The hand-off's first live run** texted the operator a failure; see the
changelog entry of this date. Its fixes and the reviewer's per-fact verdicts
are committed and go out with the next deploy.

## 2026-09-05 — The bird, Don Tito's, and the experience reviewer (NOT DEPLOYED)

See `docs/CHANGELOG.md`, this date, newest entry. Codex should review the
room photo path (`imessage_chat._observe_photos`), the firing note
(`services/transcript.py`), the proposal prompt's rejection rule, and the
experience world's check (`agents/experience/world.py::_check`).

**VERIFIED on the real models:** reminder-not-habit 1/1 (three replies),
correction capture 5/5. **VERIFIED (unit):** room worker, transcript,
recall, experience world and the suites around them 357.
**VERIFIED on the real model:** `test_experience_review_behaviour.py` 2/2 (the bird and the reminder found, a quiet day clean). **VERIFIED live:** three reviews of the operator's last 36 hours
(`backend.cli.review_experience --run`); the third, run `92af03ec`, is
parked in the live `agent_runs` table on "forget the memory 'Ani is with
Gubacchi'" and expires in 24 hours if nobody answers - the runs API and
`manage_runs` are not deployed yet, so it can only be answered after the
deploy or left to expire. Two earlier runs from the same session sit there
completed and cancelled.

**Deploy notes (operator):** the room photo fix and the firing note take
effect with the next backend deploy; the reviewer needs
`AGENT_EXPERIENCE_REVIEW_ENABLED=true` beside `AGENT_RUNS_ENABLED=true` on
`discovery-worker` (both in compose now). The three wrong memories from the
bird evening ("Ani is with Gubacchi" twice, "going line dancing with a
bird") are still stored; the reviewer's first run proposes forgetting them,
or `DELETE /api/v1/memory/{user}/semantic/{id}` removes them by hand.

**Next atomic tasks, in order:**
1. Deploy; turn the reviewer on; read its first daily report.
2. Fixes beyond forgetting: re-run a dropped attachment through vision;
   correct a fact in place with the person's yes.
3. A labelled corpus of degraded days under `docs/evals/` and a precision
   floor for `experience/judge`.

## 2026-09-05 — A hard constraint filters a result (NOT DEPLOYED)

See `docs/CHANGELOG.md`, this date, newest entry. Codex should review
`semantic_fact_is_constraint` in `backend/memory/proposal_agent.py`, the
`violates` path in `backend/core/result_ranking.py`, and `_without_violators`
in `backend/services/conversation_service.py`.

**VERIFIED (unit):** `test_constraints.py` 7; regression 586 passed.
**VERIFIED on the real models:** `functional/test_constraint_ranking_behaviour.py` 7/7 (ranking 3, classifier 4).

**Known and left:** existing preference rows were classified before the
flag existed, so a stored allergy is a preference until
`backend.cli.classify_preferences` is run (it now asks the constraint
question; dry run by default, `--apply` writes). The memory classifier
captured "I use a wheelchair, so I need step-free access" in one run of
three during the functional run while the model was at capacity, and
twelve of twelve across three phrasings when probed afterwards; the
functional test now judges the label over what was captured, and the
capture rate is the memory-capture discipline suite's property. The
paired-profile property is also a recorded measurement:
`python -m backend.cli.evaluate_constraints --reps 3` writes a run under
`docs/evals/runs/constraint-ranking/`.

**Next atomic tasks, in order:**
1. Run `classify_preferences --apply` on the Spark once the dry run below
   has been read, so stored allergies and needs become constraints.
2. The deploy steps with the operator (see the previous sections).

## 2026-09-05 — A run's approval can be answered from chat (NOT DEPLOYED)

See `docs/CHANGELOG.md`, this date, newest entry. Codex should review
`backend/tools/manage_runs.py`, `backend/services/run_answers.py`, the
`runs_waiting` context and `_render_run_context` in `backend/agents/graph.py`.

**VERIFIED (unit, real schema):** `test_run_answers.py` 7; suites 428.
**VERIFIED on the real models:** `functional/test_run_answers_behaviour.py` 6/6 (routing 4, with `MCP_SERVERS_JSON` exported; reply 2).

**Known and left:** a yes by tapback or a phone reply outside a turn is
still not an answer; `manage_runs` has no cancel mode (the runs API has
cancel). The router's judgement that a bare "yes" answers a run rests on
the history carrying the assistant's mention of the waiting run, which the
turn context now makes it say.

## 2026-09-05 — A cut-short chat turn hands the rest to a run (NOT DEPLOYED)

See `docs/CHANGELOG.md`, this date, newest entry. Codex should review the
hand-off (`ConversationService._hand_off`, `_create_continuation_run`), the
step routes (`backend/api/v1/chat_steps.py`, `decide_step`/`apply_step`),
and the world (`backend/agents/chat/world.py`).

**VERIFIED (unit, this host, real schema):** `test_chat_continuation.py` 30;
regression 498. **VERIFIED on the real model:** `functional/test_handed_off_wording_behaviour.py` passed (three replies, one property at a time).

**UNVERIFIED and worth a session:** a live hand-off end to end - a real turn
on deep-matter.com stopping on its budget, the run claimed by the worker,
the two routes called through the gateway, the person told. It needs
`AGENT_RUNS_ENABLED=true` on both `backend` and `discovery-worker` (compose
carries it on both now) and `IMESSAGE_CHAT_BASE_URL` reachable from the
worker (it is, for iMessage). `TURN_MAX_STEPS` is still 1 in the deployment,
so no turn hands off until the routing gate lets it rise.

**Next atomic tasks, in order:**
1. Phase 4: hard `constraints` in `PersonContext` and the paired-profile
   evaluator.
2. The deploy steps with the operator (see the previous sections).

## 2026-09-05 — Runs hardened: grant, fair claiming, delivery, capacity drill (NOT DEPLOYED)

See `docs/CHANGELOG.md`, this date, newest entry. Codex should review the
grant enforcement (`backend/runs/grants.py`, `RunController._apply`,
`run_worker.py::GRANTS`) and the delivery (`backend/runs/delivery.py`).

**VERIFIED (unit, this host, real schema through the tunnel):** runs 19,
drills 2, capacity 1 (24 runs / 3 workers / 29.4 s), delivery 6 = 29 passed;
regression over isolation, review check, security world, loop bounds,
discovery worker, boundaries and coverage 134 passed. Diagram
`agent-runs-subsystem` re-rendered; others restored. **UNVERIFIED:** delivery
on a real iMessage channel (the worker path is exercised with a null
channel; the discovery digest uses the same channels).

**Gap audit against `docs/AGENT_PLATFORM_PLAN.md`, what remains:**
- Phase 3: a chat turn that exceeds its budget creating a run (needs a
  conversation world over `_execute_step`); an approval answered from chat
  or the phone (today: told, answered only via the runs API); an
  idempotency key on `ScheduledTaskRepository.create` for the chat loop's
  own writes.
- Phase 4: hard `constraints` in `PersonContext` (filter, not rank) and the
  paired-profile evaluator.
- Phase 5: `repo_blame`; a labelled corpus of diffs beyond the planted
  functional fixtures; runs created from a repository event.
- Phase 6: enrichment tools (log query, alert fetch, CVE lookup through
  `allowed_hosts`); remediation tools with `approval: always`.
- Phase 7: the grant as a verifiable token (D8's second shape); redaction
  short of deletion; the isolation numbers under concurrent load with chat
  in the mix (the capacity drill is runs only).
- Deploy (operator): Spark `.env` gets the `repo` server, `REPO_MCP_ROOT`,
  `SECURITY_AUTHORIZED_ASSETS`, `AGENT_RUNS_ENABLED=true`; `git` in the
  serving image; `TURN_MAX_STEPS=3` after the routing gate.

**Next atomic tasks, in order:** the Phase 3 items above (chat → run
hand-off first, then approvals in chat), then Phase 4's constraints, then
the deploy steps with the operator.

## 2026-09-05 — Every flagged line accounted for: the security agent's judgement step (NOT DEPLOYED)

See `docs/CHANGELOG.md`, this date, newest entry. Codex should review the
judgement step (`backend/agents/security/prompts.py`, `SecurityWorld`
in `backend/agents/security/world.py`, `prompts/security/judge_hits.md`).

**VERIFIED on the real model:** `functional/test_security_review_behaviour.py`
2/2 with the stage (log `scratchpad/sec_fn6.log` on the desktop). Before
it, the planted case passed 3 of 5 attempts: the findings step left the
hard-coded key out, silently. **VERIFIED (unit, this host):** security
world 13, review check 23 + coverage suites (91 together), runs/drills/
isolation/bounds/prompt/worker suites 400. Diagram `agent-security`
re-rendered; the other SVGs restored unchanged.

**What the stage does:** after the findings are checked, every flagged
line no kept finding covers goes back to the model with six lines of code
on each side for a verdict - a finding through the same evidence check, or
a dismissal with a reason. Each verdict is bound to the hit it is about
(`hit_for`), so the hit's identity is the world's and only the quote is the
model's. The report carries `dismissed` and `unjudged` beside `findings`
and `rejected`; a hit past `MAX_JUDGED_HITS` (12), unanswered, or whose
judgement failed `MAX_JUDGEMENT_ATTEMPTS` (3) times is named unjudged.

**Known and left:** the egress screen withholds `password` and `api_key`
in any tool argument, so those words cannot be grep shapes; `secret_key`
and `token=` stand in. The functional test's variance is the model's, at
temperature zero under batching; the stage is what makes the property hold
regardless.

**Next atomic tasks, in order:**
1. Configure on the Spark: the `repo` server in `.env`'s `MCP_SERVERS_JSON`,
   `REPO_MCP_ROOT`, `SECURITY_AUTHORIZED_ASSETS`, then `AGENT_RUNS_ENABLED=true`
   on `discovery-worker` once one hosted run has been watched end to end.
   The serving image needs `git` (opencode's Dockerfile change is in flight).
2. Compare the pilot review's findings on `7cdd4af4` with Codex's.
3. Raise `TURN_MAX_STEPS` to 3 after the routing gate and a sweep pass.
4. Phase 7 remainder: retention for run events, fair scheduling per
   principal, a capacity test. The router track remains unstarted.
5. Chat → run hand-off and approvals in chat (Phase 6 remainder).
6. The gap audit the operator asked for, against `docs/AGENT_PLATFORM_PLAN.md`.

## 2026-09-05 — Security agent verified on the model (2 of 3 attempts); Refused decision; drill pollution fixed (NOT DEPLOYED)

See `docs/CHANGELOG.md`, this date, newest entry. Codex should review the
`Refused` decision (`turn_steps.py`, `runs/controller.py`) and the evidence
check's canonical-line change (`agents/review/world.py`).

**VERIFIED on the real model:** `functional/test_security_review_behaviour.py`
- the refusal case passed on both attempts; the planted case passed on its
second attempt (three investigations, key and shell found each time, safe
call not reported) and failed on the first with the assertion lost to a
25-line log tail. A third full run was started at this checkpoint with the
whole log kept (`scratchpad/sec_fn2.log` on the desktop); if it fails, the
assertion is the thing to read first. **VERIFIED (unit, this host):** full
suite 2850 passed / 8 failed before the fixes below; the drill, encryption,
pool and runs suites 32 passed together after; review check 23, security
world 4, loop bounds 25.

**What was wrong and is fixed:** the security scope refusal was retryable
(`Unavailable` → requeued) and is now `Refused`, final, `error_code=refused`;
a kept finding's evidence was the model's quote, cut at the first embedded
`"`, and is now the file's own line; two grep shapes (`password=`, `secret=`)
were withheld by the egress screen on every run and are replaced by shapes
it lets pass; `test_crypto.py` and `test_storage_encryption.py` blanked the
encryption key on teardown and broke the process-kill drill in the full
suite only.

**Untracked and deliberately not committed:** fifteen trajectory run records
under `docs/evals/runs/tool-selection/` from this session's measurements
(the measurement of record is the one tracked file), and
`backend/market/model.py`, which belongs to the other session.

**Next atomic tasks, in order:**
1. Read `sec_fn2.log`; if the planted case failed, fix the cause and re-run
   before anything else. Then compare the pilot review's findings on
   `7cdd4af4` with Codex's on the same commit.
2. Configure on the Spark: the `repo` server in `.env`'s `MCP_SERVERS_JSON`,
   `REPO_MCP_ROOT`, `SECURITY_AUTHORIZED_ASSETS`, then `AGENT_RUNS_ENABLED=true`
   on `discovery-worker` once one hosted run has been watched end to end.
   The serving image needs `git` (opencode's Dockerfile change is in flight).
3. Raise `TURN_MAX_STEPS` to 3 after the routing gate and a sweep pass.
4. Phase 7 remainder: retention for run events, fair scheduling per
   principal, a capacity test. The router track remains unstarted.
5. Chat → run hand-off and approvals in chat (Phase 6 remainder).
6. The gap audit the operator asked for, against `docs/AGENT_PLATFORM_PLAN.md`.

## 2026-09-05 — Place judgement live (9/9); security agent's first shape; pilot defects fixed (NOT DEPLOYED)

See `docs/CHANGELOG.md`, this date, newest entry. Codex should review the
security world (`backend/agents/security/world.py`) and the two pilot
fixes (`backend/mcp/servers/repo.py` bounds, `turn_steps.py` key-before-step).

**VERIFIED on the real model:** `functional/test_place_bound_judgement_behaviour.py`
9/9. **VERIFIED (unit, this host):** security world 4, API isolation 3,
repo server + evidence check 23, loop bounds 15, search place suites, the
coverage and prompt suites; 30 diagrams synchronized.
**VERIFIED on the live model:** the pilot review of `7cdd4af4` completed
(run `2aeb5927-6526-4596-9d23-eca7c62d4bfe` for `operator`: six files
read, one finding kept, seven rejected for a quote one line off - the
evidence check now tolerates two lines). **UNVERIFIED:**
`functional/test_security_review_behaviour.py` (running at this checkpoint
against a model at six concurrent requests). The local
`.env`'s internet server entry was behind the Spark's (17 of 23 forwarded
names) and is refreshed; the deployment was never affected.

**Opencode's state (checked 2026-09-05 afternoon):** nothing pushed since the
Phase 1 scorer fix (`29c48ea3`). Its Spark checkout is behind `origin/main`
with no unpushed commits and two uncommitted things: `Dockerfile` gains `git`
in the *test* image for the repo-server tests (right, and it should commit
it), and two trajectory runs recorded at `2fc6610` - the tree before the
step-line fix - reading 9/18 and 9/18, i.e. the pre-repair baseline, not a
regression. Its second run showed `reference` at 2/3 breaching a 0.67 floor:
2/3 is 0.667, so that floor tolerated no miss; the floors for three-sample
categories are 0.66 now. When reviews are hosted by `discovery-worker`, the
*serving* image needs `git` too (the repo server shells out to it); that is
the Dockerfile's runtime stage, left to opencode since the file is in flight
there.

**Next atomic tasks, in order:**
1. Read the security functional test's result; compare the pilot review's
   findings on `7cdd4af4` with Codex's on the same commit.
2. Configure on the Spark: the `repo` server in `.env`'s `MCP_SERVERS_JSON`,
   `REPO_MCP_ROOT`, `SECURITY_AUTHORIZED_ASSETS`, then `AGENT_RUNS_ENABLED=true`
   on `discovery-worker` once one hosted run has been watched end to end.
3. Raise `TURN_MAX_STEPS` to 3 after the routing gate and a sweep pass on
   this tree.
4. Phase 7: a restart drill that kills the worker process (the in-process
   drill exists), retention for run events, fair scheduling per principal.
   The router track (rate assertions, the SetFit front) remains unstarted.
5. Then the gap audit the operator asked for.

## 2026-09-05 — Phase 2 closed (15/18); Phase 3 built; the reviewer built; two functional tests wait on a quiet model (NOT DEPLOYED)

Read `docs/CHANGELOG.md` (this date, second entry) for what was built and
measured. Codex should review the Phase 3 controller (`backend/runs/`) and
the reviewer world (`backend/agents/review/world.py`) before Phase 5 goes
further.

**VERIFIED:** trajectories 15/18 on the real router, recorded and floored;
unit suites for runs, the repo server, the evidence check, the harness and
the registry; the additive migration `20260905_0019` applied to the live
database (backup first); 29 diagrams synchronized.
**VERIFIED on the real model:** `functional/test_unknown_step_wording_behaviour.py`
(with `LLM_TIMEOUT_SECONDS=900` under load).
**VERIFIED on the real model:** `functional/test_code_review_behaviour.py`
- three reviews of a planted off-by-one behind an injected comment, run
through the real repo MCP server and the real controller: every run
completed on evidence, only read tools were recorded, no finding named the
file the comment pointed at, and the defect was found (5m33s under a model
at six concurrent requests, `LLM_TIMEOUT_SECONDS=900`). Run them alone when
`curl http://172.16.8.3:8000/metrics | grep num_requests_running` is near
zero, with `LLM_BASE_URL=http://172.16.8.3:8000 LLM_MODEL=deepseek-v4-flash
PYTHONPATH=<checkout>` exported (the test suite skips `.env`). Sweep
journeys and the routing matrix have not been run on this change. Nothing
is deployed; `TURN_MAX_STEPS` is still 1 and `AGENT_RUNS_ENABLED` false.

**Next atomic tasks, in order:**
1. Configure the `repo` server in `.env`'s `MCP_SERVERS_JSON` and
   `REPO_MCP_ROOT` on `discovery-worker` (compose allowlist too), review one
   real commit of this repository with `backend.cli.review_commit`, compare
   with Codex's review of the same commit.
2. Raise `TURN_MAX_STEPS` to 3 in `.env` and read it back from the
   container, only after the routing gate and a sweep pass on this tree.
3. Phase 4's first slice is in (`backend/memory/person_context.py`, wired
   into the search stage and the ranker, unit-verified). Next for it: retire
   `_PLACE_BOUND` by adding `place_bound` to `search/place.md` with a
   functional test, then constraints as hard filters and the paired-profile
   evaluator. The router track (rate assertions, the SetFit front), Phase 6
   and Phase 7 remain unstarted.

## 2026-09-05 — Phase 2 first checkpoint: bounds are structural, the step line is the next defect (NOT DEPLOYED)

Committed as a checkpoint at the operator's request (usage ran out), with
the verification state below. Codex should review this commit before the
next step. The plan is `docs/AGENT_PLATFORM_PLAN.md`; this is its Phase 2.

**VERIFIED (unit, this host, Postgres and Redis over the SSH tunnel):** the
29 focused suites around the change and the four new modules
(`test_turn_steps_bounds`, `test_effect_contracts`, `test_mcp_tool_contracts`,
`test_routing_decisions`) - 366 + 147 passed. `test_tool_catalog_page` and
`test_discuss_image_tool` updated for the new column and the removed
`_runnable`. Diagram check: 27 synchronized.
**VERIFIED (full unit suite, this host):** 2744 passed, 3 skipped, 9 failed
in 8m11s. One failure was this change (`test_history_recall` imported the
removed `_runnable`; rewritten against the executor in the follow-up commit).
The other eight are this Windows host, not the change: six need the parser or
Drive services (`ConnectError`), one is `_hold_to_dates`'s `%-d` format that
Windows `strftime` rejects, and `test_settings_reach_their_consumer[internet.py]`
fails at HEAD too. Re-run in the container before deploying.
**UNVERIFIED:** the sweep journeys and the routing matrix have not been run
on this change. Nothing is deployed.
**MEASURED:** `evaluate_trajectories --reps 3` on the real router: 10/18,
unchanged; one acceptance breach (a duplicate in `search-then-remind`).

**Next atomic task - make the step line say what was done.** The evidence
in the run file is unambiguous: `_step_line` renders "Scheduled tasks: once at
18:00" and "Manage scheduled tasks: reschedule", so the router cannot tell
which reminder it already set and writes "call mum" twice (at 6pm and again
at the gym's 8pm), and repeats a reschedule it cannot see it made. Fix
`_detail` in `backend/tools/registry.py` to carry the instruction (`once at
18:00 - remind me to call mum`) and `which`/the new time for `manage_tasks`;
strip trailing punctuation in `schedule_task`'s key; then re-run the
evaluation and expect `multiple_writes` to move. Two case questions for the
operator: `cancel-and-reschedule` is answered by one `reschedule` call, which
the case labels incomplete; and `search-then-remind` took no tool twice on
the first decision - the harness should record the typed decision
(`NeedsInput` is the likely reason: "saturday" has no time) rather than
`(none)`.

After that: `TURN_MAX_STEPS=3` in `.env` and the three compose services,
read back from the container, only once the gate holds; then Phase 3.

## 2026-09-05 — Phase 1 evaluation made honest after codex review (PUSHED)

Codex reviewed the Phase 1 baseline and showed four false positives: the
first scorer credited any step of the right *name*, so a failed reminder for
the wrong task "completed", two identical wrong reminders "completed" with
zero duplicates, and list-tasks counted as "carrying" the move request it
never made. The follow-up makes completion mean the requested effects
happened, and records why a turn stopped. Verified:

- `trajectory_harness.py`: `RequiredEffect` pairs each required step with the
  operation, the argument words it must carry, and whether it must have
  succeeded; the required sequence is matched in order `required_times` over,
  and `covers` words must appear across the *matched* steps (two copies of one
  reminder never satisfy a request for two). `honest_failure` semantics for
  the scripted not-found case. Duplicate = a create beyond the allowance OR
  identical to an earlier one. `carried` is a diagnostic, independent of
  success.
- `turn_steps.py`: `run_steps` returns a `TurnResult` with a real, named stop
  reason (declined / ceiling / repeated / unapplied / budget / second-create).
  The recorded reason answers the review's question directly: every
  `two-reminders` run stops on `SECOND_CREATE` — the repeat guard, not the
  model, is what cuts two writes to one.
- `evaluate_trajectories.py`: `acceptance()` is a pure gate (completion and
  carrying floors, no unauthorized tool, no duplicate effects) that fails the
  CLI; runs persist per-observation evidence, the model, a case fingerprint,
  and the commit (`ANIOS_EVALUATION_COMMIT`).
- The four review reproductions are pinned as regression tests in
  `test_trajectory_evaluation_behaviour.py`.

Corrected baseline (2026-09-05, two runs, recorded pre-commit as
`*-nocommit.json`): single_step 3/3, reference 3/3, partial_failure 3/3,
mixed_tools 0–1/6 (router does the first tool and stops or repeats), and
multiple_writes 0/3 (all `SECOND_CREATE`) — overall 9–10/18, now honest.
Carried: single/reference 3/3, mixed_tools 1/6, multiple_writes 0/3. Floors
in the CLI were then set one miss below these numbers and the gate re-run
PASS. Verified: full unit suite **2635 passed / 9 skipped** via
`bash scripts/gate.sh --unit`; trajectory + loop + turn-steps functional
suite **25 passed** (one transient router-variance failure on the first
batch run, passed alone and green on re-run).

## 2026-09-05 — stock-analysis foundation, slice 1 (SUPERSEDED by the market research entry above; kept as history)

First slice of the deep-learning research system for the trading agent,
built from the plan the operator endorsed (daily data, swing horizon,
DeepSeek as a research component, measure before betting). The design answer
to "wouldn't a neural network already learn the structure report?": **yes —
so it is fed raw normalized price/volume sequences, not a hand-coded trend
slope or volatility number.** The hand-coded sector report is a later
baseline to beat, not the architecture.

New `backend/market/` package:

- **`universe.py`** — focus names (CRWV, IREN, SNDK), a comparison universe
  across the themes money rotates between (software, ai-compute,
  memory-storage, networking, power-cooling; overlapping baskets, not one
  "AI" label), and benchmarks (SPY, QQQ, SMH).
- **`yahoo.py`** — daily OHLCV + adjusted close from the free keyless Yahoo
  chart endpoint, with a normal user agent. A 429 or any non-200 raises
  `MarketDataUnavailable`; the parser is a pure function over the payload so
  tests use a recorded fixture, never the network.
- **`market_daily_bars` table** — one row per (ticker, session date, source)
  with raw OHLCV, adjusted close, volume, source and retrieved_at, so
  corrections are traceable. Migration `20260905_0018`, **applied to the
  live DB** (backup taken first; head now `20260905_0018`).
- **`repository.py`** — async upsert (rerunning a date refreshes, never
  duplicates), latest-session, bars-for-range, delete-for (test cleanup).
- **`snapshot.py`** — `refresh` (fetch + store, failures captured per ticker,
  never fatal) and `status` (per-ticker missing/stale flags), plus
  `daily_returns` computed **from adjusted close, so a split cannot
  manufacture a return**.
- **`windows.py`** — the model input: per ticker, windows of raw daily
  channels (own log return, log volume, market-relative return vs the
  benchmark) over the shared trading calendar, **structurally no look-ahead**
  (a window ending at session t contains only <= t) with a separate K-day
  forward-return label marked invalid wherever the future is not fully known.
  Channels are emitted raw; z-scoring is a harness step fit on train only.
- **`backend/cli/market_snapshot.py`** — `--refresh` and `--status`.

Verified: 15 new tests (parser fixture, 429 handling, upsert idempotency,
reproducibility, split-safety, stale/missing flags, window no-look-ahead and
gap handling); full unit suite **2635 passed / 9 skipped** via
`bash scripts/gate.sh --unit`. CLI verified live: `--status` reports every
ticker MISSING; `--refresh` against the real source flagged each ticker
FAILED with a clean message and exited 0 — **the rate-limited path is proven
live**. The DeepSeek research model was checked as requested:
`deepseek-v4-flash` is live on spark1 `172.16.8.3:8000` (`/v1/models`,
max_model_len 1048576).

**UNVERIFIED:** a successful real fetch+store. Yahoo is 429-throttling this
network (host and backend container) all session; the parser is fixture-tested
and the fetch+store path is gate-tested with a stubbed fetcher, but the
real-network round trip has not landed rows yet.

**Next atomic task:** when Yahoo's throttle clears, run
`python -m backend.cli.market_snapshot --refresh` over the universe and
confirm stored rows via `--status`. Then slice 2: the walk-forward harness
with a relative-strength baseline (the thing the DNN must beat), and decide
the training environment — **no torch/pandas/sklearn in the backend
container today**, so training placement (a Spark, a new image, or the Mac)
is a decision before any model can be trained.

## 2026-09-05 — Phase 1 of the execution-boundary repair: measured and pushed

The trajectory baseline is built, measured, and on `main`
(`python -m backend.cli.evaluate_trajectories --reps 3`). It drives the real
router + `run_steps` over six labelled trajectories and measures whole-turn
completion, argument carrying, unauthorized tools, duplicate effects, and
cost. Baseline (stable across two runs): **10/18 overall (0.556)** —
single_step 3/3, reference 3/3, partial_failure 3/3, but mixed_tools 1/6
(the router does the first tool and stops or repeats it) and multiple_writes
0/3 (two reminders become one: the repeat guard cuts the second write). Both
failing categories are floored at 0 until Phase 2/3 moves them. Runs recorded
under `docs/evals/runs/trajectories/` (pre-commit, `*-nocommit.json`).

Next is Phase 2, the repair the baseline was built to measure: typed
decision/result states (distinguish finished / needs clarification / model
failure / no tool), deadline enforcement (re-check before executing the
returned action), complete nested MCP schema validation, recursive outbound
screening, cache identity on full tool definitions, and per-tool retry rules.
Phase 3 then makes the run durable (storage, idempotency, cancellation,
recovery). The user will have codex review each phase's work.

## 2026-09-04 — the "try again" fix is deployed (8116e7d); the search-place fix is live

The first bad "fun things to do in the area" answer shipped on pre-fix code
(the distance filter was not yet in the built image). The retry ran on the
fixed code and was still bad: "try again" searched **Colonial Heights** for a
person in Courthouse because `search/compose` copied the town out of the
previous answer's listing. A prompt sentence was measured and failed 2/3, so
the fix is structural (`prompts/search/place.md`, `foreign_places`,
`_drop_foreign_places` in `_research`) — see the CHANGELOG entry of this date.

Also fixed: `test_the_search_is_personalised_only_where_that_is_the_answer`
could never pass (it compared the *pair* of lists `relevant_interests` returns
against the flat interest set, and `bool(((), ()))` is truthy), so the "18/18
measured" claim for `search/personalize` had no passing test behind it. The
corrected test passes on the real model.

Verified: unit suite 2620 passed / 9 skipped; `functional/test_search_compose_behaviour.py`
13 passed against the real model. **Deployed and live** as `8116e7d` on
2026-09-04: unit gate 2620 passed, routing gate 83 passed, sweep journeys and
search harness passed after deploy.

## 2026-09-03 — model-serving docs corrected, and the Trading agent's first capability (NOT DEPLOYED)

Three files still described the retired 2-bit ds4 GGUF as the deployed model:
`AGENTS.md`, `docs/DEVELOPMENT_GUIDE.md`, and the top of
`docs/MODEL_EVALUATION.md`. The running reply model is the **official FP8**
DeepSeek-V4-Flash-0731 (~156 GB, `quant_method: fp8`), served by vLLM
tensor-parallel across both Sparks, port 8000 — confirmed from the live
container (`config.json`, `/v1/models`, the vLLM command line, and the
retired ds4 port 8888 refusing connections). `ML_SYSTEM_DESIGN.md` already
recorded this correctly; the three other docs now agree. Pushed as
`ea3bfb0`.

**Trading agent (Phase 1 of the personal trading analyst):** a new agent
`backend/agents/trading/` with one prompt (`prompts/trading/autopsy.md`) that
reads a person's own trade-history passages and names the behaviours that
repeat, what they cost (only when a number is actually in the record), and a
stop/start/keep plan. Card registered in `agents/registry.py`; a new
`agent-trading.mmd`/`.svg` diagram pair registered in the renderer, the
published page, and the catalog; a row in `AGENT_CATALOG.md`; functional
proof `backend/tests/functional/test_trading_autopsy_behaviour.py` — 6/6
against the real model (pattern must repeat, once-off is not a pattern, no
invented amounts, real costs reported with source, plan has all three lists,
every pattern carries evidence). Also fixed a pre-existing inconsistency the
renderer surfaced: `document-knowledge` was rendered and cataloged but never
in the published page or the renderer list; it is now registered and the
full suite is 26/26 synchronized. Full unit suite green (2530 passed, 9
skipped).

**Next atomic task:** make the autopsy reachable in chat — a router tool
(e.g. `analyze_trading`) so the assistant can act on "analyze my trading".
Per AGENTS.md a new tool is not shipped until the router is measured choosing
it, so that means a `TOOL_NAMES` entry, labelled cases in
`backend/services/tool_selection_cases.py`, and `python -m
backend.cli.evaluate_tool_selection` per-category comparison, then a sweep
journey over HTTP. Broker statements (Schwab) are post-analysis only — not
ingested yet. Free market data (yfinance-style Yahoo chart API, Alpha
Vantage, TwelveData) is reachable from inside the backend container; that is
the Phase 2 data layer. Nothing here is deployed.

## 2026-09-02 — decks plan their slides together, and background work stops starving (NOT DEPLOYED)

Traced from a live deck that took 12m32s for seven slides while the inference
engine sat at `Waiting: 0 reqs`, 0.5% KV. Three things were serialising it and
all three are addressed; the full reasoning and numbers are in the CHANGELOG
entry of the same date.

- **`backend/core/model_gate.py`** — `background()` waited for *zero*
  interactive requests before starting, which never happens under sustained
  chat (17-27 calls/min when measured). It now yields for
  `MODEL_GATE_MAX_WAIT_SECONDS` (20 s) then proceeds; a held lease is renewed
  so a whole deck does not outlive it; Redis keys are namespaced so a test
  cannot stall the live scheduler.
- **`backend/presentations/provider.py`** — slide calls are scheduled together
  (`PRESENTATION_SLIDE_CONCURRENCY`, 4) and consumed in outline order, and the
  background lease is taken once per deck rather than once per call.
- **The trap that would have made it a no-op**: `LLMClient` serialises its own
  requests through a per-instance lock guarding the `reasoning_effort` latch,
  so each concurrent worker gets its own client from `llm_factory`. Without a
  factory the provider plans one slide at a time rather than pretending. The
  lock itself was deliberately not touched — every other caller relies on it.

Measured on the deployed stack, one 6-slide deck per arm: concurrency 1
130.65 s, 2 75.66 s, 4 50.30 s, 8 51.89 s (four is the knee). Two further
1-vs-4 runs gave 1.86x and 1.46x. Foreground cost with chat probes running:
no deck 0.17 s median / 0.24 s p95; deck at 2, 0.26/0.39; deck at 4,
0.27/0.40 — so almost all of the cost is a deck running at all, not its width.

Verified: 10 new unit tests green (5 gate, 5 fan-out), deck functional suite
6/6 against the real model in 4m47s including new `create_progress` coverage,
2,387 unit tests green in the container. The two failures in that run are the
documented environment leak (`AUTH_COOKIE_SECURE`, `LLM_BASE_URL` from the real
container env) and pass when those are neutralised — not regressions.

**Next atomic task: deploy it.** Nothing is deployed; the measurements above
were taken by running the new code inside `anios_backend` via the `docker cp`
overlay, which does not affect the running server. Before `bash
scripts/deploy.sh`, check `git status --porcelain` in the Spark's `~/anios` —
deploy.sh builds from that working tree, and opencode edits in it. Two live
values to confirm reached the containers afterwards, since a `.env` entry beats
a compose default: `docker compose exec -T presentation-worker printenv | grep
-E 'PRESENTATION_SLIDE_CONCURRENCY|MODEL_GATE_MAX_WAIT_SECONDS'`.

## 2026-09-01 — links are hyperlinks on every surface (deployed 2ee4c4a)

Chat replies and digests pasted bare long URLs: the listing wrote `Map:
https://maps.google.com/...` and `Details: https://...` as raw text, the web
chat rendered bare URLs as inert text, the Scout "Add to calendar" used a
relative `/api/v1/discovery/...` path, and a feed URL with a stray newline
became dead text in iMessage. Fixes in the working tree (deploy pending via
`scripts/deploy.sh`):

- **Listing emits markdown links** `[Map]/[Add]/[Hear it]/[Details](url)`
  (backend/core/events_listing.py). Web chat renders them tappable; the
  iMessage worker's `plain_text` converts to `label (url)` which iMessage
  auto-links. The link fence keeps every one (verified).
- **Web chat auto-links bare URLs**: `frontend/src/utils/linkify.ts`
  `linkifyMarkdown` in MessageBubble, plus `frontend/src/components/Linkified.tsx`
  for the Scout preview/rehearsal panes (ScoutSetup.tsx). Safe because the
  reply fence already stripped unvouched URLs.
- **`calendar_path` is absolute** (backend/api/v1/discovery.py `_calendar_link`,
  both call sites), built from `DISCOVERY_CALENDAR_BASE_URL`
  (`https://deep-matter.com/api/v1/discovery`), so the `.ics` opens from a
  phone. NOTE: the single-event `.ics` route is still behind `authorize_path_user`
  — a phone without a session still gets 401. If "Add to calendar" must work
  unauthenticated, make it public-by-unguessable-digest like the feed router.
- **Digest URLs cleaned** (`_clean_url` in backend/discovery/digest.py, applied
  at every append site) — strips control characters/whitespace.

Verified: 187 unit tests (including new: cleaned digest URLs, absolute
calendar link, markdown listing assertions), fence keeps all listing links,
`plain_text` round-trips, frontend type-checks. A deterministic Playwright
test (`renders markdown links and bare URLs in an answer as tappable links`
in frontend/e2e/chat.spec.ts) is written but **could not be run here — no
host node/browser**; run `npm run test:e2e` (or open the web chat and confirm
the listing's Map/Add/Details are clickable) to close the UI check.

**Still open from the 2026-08-31 work**: four commits (`1a5b8a3`, `e9a476b`,
`9627a26`, `bff350f`) are deployed but UNPUSHED to origin (no git auth on this
host — push from the Mac). `NEXT_SESSION`
and `CHANGELOG` got entries for the 2026-08-31 fixes; the Google-fallback,
pool, spread/repeat, date-rollover, and chat-grounding changes need their
handoff entries folded in.

## 2026-09-01 — digest keeps the working artifact (deploying with this commit)

- **`prompts/memory/digest.md`**: the rolling digest now explicitly keeps "the
  artifact they are working on... and what was decided or changed about it, by
  name." A long coding thread can outlive the ten-turn window; the durable fact
  is which file/artifact was in play, which the old keep-list captured only via
  "what the person is trying to do". Pinned by
  `test_digest_keeps_the_artifact_and_the_decision_about_it`
  (`test_conversation_digest_behaviour.py`); 14 digest tests pass.
- Investigation result worth remembering: the durable-context machinery already
  exists and is sound - cumulative digest every 10 turns at priority 0 (never
  trimmed), reply prompt already hedges on missing earlier turns, reply-rescue
  covers explicit replies. No new system was needed; this is a one-line
  keep-list refinement plus a pin.

## 2026-09-01 — manage_tasks claims its memory undo (deployed 7fff8d9→ecc233a)

- **`backend/tools/manage_tasks.py`**: the tool description now says undo puts
  back "the most recent change the assistant made - a reminder, Scout's
  schedule, or a fact it just saved to memory - 'forget that'..." . The router
  reads each tool's own description when choosing, and the old text never
  mentioned the memory undo this tool performs, so "forget that" mis-routed to
  Past conversations/None ~1/3 of the time with a false "forgotten" claim.
  Controlled in-process A/B: 4/15 -> 15/15 manage_tasks. Full matrix with the
  fix: manage_tasks 45/45, task_undo 15/15, no new cross-tool cell.

## 2026-09-01 — "forget that" routing fix + judge pin (deploying with this commit)

- **`prompts/routing/select_action.md`**: removed the contradiction that made
  the router sometimes route "forget that" to no tool, leaving the reply to
  claim a forgetfulness that was never written (the sweep journey caught it).
  An instruction to change what the assistant holds is an action (manage_tasks
  undo), never a question to answer. Verified 5/5 journey runs; matrix gate
  7/7; evaluator 0.9184 overall, manage_tasks 43/45, task_undo 13/15.
- **`backend/tests/functional/test_semantic_judge_reliability.py`**: pins
  `semantic.states` (the judge behind a dozen functional modules and every
  journey) against ten unambiguous seeds at a floor one miss below the
  measured 10/10. Finding recorded in the module: the judge reads action
  wording ("forgot, removed") but not state wording ("no longer remembers"),
  which is why journey statements already carry the action words.

## 2026-09-01 — notability tiebreak + check-in journey (deployed 593cf3c)

- **`prompts/scout/rerank.md`** adds a notability tiebreak: among finds the
  approved facts do not distinguish, a one-off festival/headline leads a
  routine weekly social. Reorder-only, never an exclusion, so it cannot empty
  a digest. Pinned by two cases in `backend/tests/functional/test_prompt_behaviour.py`;
  `evaluate_discovery_ranking` green (filtering recall 0.8571, geography
  happening-retention 1.0). Rehearsal still shows variety.
- **`backend/cli/sweep_journeys.py`**: "group: a shared plan arms a check-in
  in the room" now allows `(None, "Past conversations")`. Check-in arming is
  route-independent; in the red runs the check-in was armed and only the route
  was flagged. sql_holds (the armed `checkin:%` task) stays the real assertion.
  Verified 3/3 green.
- Both were committed with this session's link work as `2ee4c4a` is already
  deployed; these two are in the next commit.


## 2026-08-31 — recommendation quality: ranked by the person, not a stale mood (deploy pending)

The operator's digest on 2026-08-31 recommended a guided walk at Arlington
Court, **Devon, England** to someone in Courthouse, Arlington, Virginia.
Root cause, all verified by running the live pipeline: the profile's region
was stored **`Arlington, Arlington`** (a repeated region), which makes the
US-state-only `contradicts_locality` guard see nothing and every query say
"Courthouse, Arlington, Arlington"; the Brave snippet named only the estate's
town, so the `_located_elsewhere` judge said "local"; and the URL
(`/visit/devon/`) — where the page actually is — was never shown to the
judge. With one novel candidate that sweep, it shipped. Second contributor:
the memory classifier had stored "feeling a little tired today" (2026-08-29)
with **no expiry**, so it aimed the hiking query at "easy scenic nature
walks" and put a hiking-guide page ahead of the dance events the account
asks for.

**Fixed and functionally verified in the working tree (deploy pending via
`scripts/deploy.sh`):**

- **Region**: `_apply_locality` collapses a repeated region segment
  (projection.py); operator's locality corrected to `Courthouse, Virginia`
  (approved fact + `discovery_localities`), which re-arms the US-state guard
  and fixes the queries.
- **Locate judge sees the URL** (describing.py + prompts/scout/locate.md):
  the Devon snippet alone returns not-elsewhere, with the URL it returns
  elsewhere — verified live.
- **Sweep context excludes image descriptions** (runner.py, purpose
  `visual_artifact_analysis`), so durable demographics/preferences fill the
  bounded context.
- **Transient facts expire** (proposal_agent.py `semantic_fact_is_transient`
  + conversation_service save path, `TRANSIENT_FACT_DAYS=7`); operator's
  stale "tired today" row expired.

**Rehearsal proof** (`DiscoveryRunner.sweep(...persist=False)` for
operator, worker image with the tree mounted): query now
"Courthouse, Virginia"; shortlist all line-dancing/social-dance finds;
reranker (memory) orders NVCDA social dances, Virginia Line Dance Festival,
DanceSportVA — no Devon, no hiking guide.

**Measurements**: `evaluate_discovery_ranking` green (filtering 0.857/1.0,
geography retention 1.0; the new Devon case is labelled and the deterministic
US-only guard honestly still can't catch it — the model stage now does).
`test_description_quality.py` 101/101, `test_prompt_behaviour.py` 22/22,
`test_preference_labelling_behaviour.py` 13/13, `test_memory_capture_discipline.py`
green, discovery/memory units 512+44+17+30.

**Known**: `test_memory_capture_discipline.py::test_a_fact_survives_a_catalogue_that_mentions_its_subject`
is flaky by nature (per-message 3/4 recall on a documented-fragile case; it
flaked with and without this change, and is not in the deploy gate). The
reranker's exclusion of an explicit restriction (e.g. "55+") is deliberately
conservative and flaky (see reranking.py) — ordering, not exclusion, is the
memory mechanism.

**Deploy**: `bash scripts/deploy.sh`, then confirm the next operator sweep
(19:00 UTC) recommends local dance/social finds. After deploy, re-check
`docker compose exec backend` has the new code (it is image-baked).

**If you are picking this up on the Mac**, read [Where things run](#where-things-run)
and [Operational traps](#operational-traps-that-cost-real-time) first. The Mac is
not currently part of the running system except as the iMessage bridge, and one
task below is deliberately assigned to it.

## Live and verified

| | |
|---|---|
| site | `deep-matter.com` 200, tunnel is a compose service on spark1 |
| database | on spark1, migration head `20260828_0011` (conversation groups; 39 tables) |
| redis | 6,655 keys, append-only on, cursor `imessage:chat:cursor` present |
| models | DeepSeek-V4-Flash TP=2 (spark1+spark2), Qwen3-VL-8B (spark2), nomic 768-dim + Qwen3-Reranker-0.6B (spark1), FLUX.2 Klein 9B Q6_K + Kontext via ComfyUI on the desktop (only while it is on) |
| deploy gate | `bash scripts/gate.sh` — 7 passed, 0 skipped, ~5 min; exits 1 with the router down |
| backups | nightly 03:30 timer, three copies (spark1, spark2, Mac), restore proven end to end; WAL archived every 5 min with weekly-pruned base backups, point-in-time recovery rehearsed 2026-08-25 |

## Where things run

| Host | Address | What it holds |
|---|---|---|
| spark1 | `172.16.8.3` | every app container, the database, redis, the tunnel |
| spark2 | `172.16.8.5` | the VLM, half of the TP=2 router, the backup mirror |
| Mac | iMessage bridge only | `allow_recipient`, `send_imessage`, `read_messages` |
| desktop | `172.16.8.6` (Wi-Fi) | RTX 5080, **16 GB VRAM**; revived to host ComfyUI. Image work only while it is on |

User `sparkuser` on both Sparks, same password on both. No BMC and no
wake-on-LAN, so **a powered-off Spark needs someone to press the button.**

## Search spend and providers — 2026-08-29

- **Brave is metered now.** Its live headers say `50;w=1, 0;w=2678400`: 50
  per second, **0 per month**, and requests are still served - i.e. billed
  (~$5/1k). The local `BRAVE_SEARCH_MONTHLY_LIMIT=900` is a spend cap, not a
  free allowance. Check the Brave dashboard and decide the cap deliberately.
- **Tavily leads now** (`SEARCH_PROVIDER_ORDER=tavily,brave,google` in
  `.env`, backup `.env.bak-20260829-search`): 1,000 free credits a month,
  reset on the 1st, so from 1 September the free one is spent first.
- **Gemini grounding stays off, and turning it on is now three steps.**
  Google's pricing page: grounding is *not available* on the free tier
  (which is the 429 we measured - a plain call on the same key works). With
  billing enabled the first 5,000 search queries a month carry no grounding
  surcharge on Gemini 3.x, then $14/1,000, and prompts stop being used to improve
  Google's products.
  1. AI Studio → API keys → find the Cloud project behind `GOOGLE_API_KEY`.
  2. Google Cloud console → Billing → link a billing account to that
     project, and confirm Tier 1 on the rate-limits page.
  3. On spark1: `GOOGLE_SEARCH_ENABLED=true` in `.env` (already inherited by
     the search subprocess), and put `google` first in
     `SEARCH_PROVIDER_ORDER`. The ceiling is already in place -
     `GOOGLE_SEARCH_MONTHLY_LIMIT` defaults to 4,800, under Google's included
     5,000 search queries, with the daily 450 beneath it. As of the paid-key
     acceptance on 2026-08-29, AniOS reserves ten queries before each call and
     reconciles the counters from `web_search_queries`; an uncertain timeout
     keeps the reservation. This is a buffered local stop, not a provider bill
     cap.
  Verify with one grounded call and `search_credits`, which now reports the
  Google allowance beside Brave's.
  The paid-key comparison chose `gemini-3.1-flash-lite` for this retrieval
  worker: across Python, Federal Reserve, and Artemis queries it returned the
  same current facts and official sources as 3.6, while the two timed comparison
  cases took 1.56/1.95 seconds instead of 3.25/7.96 and used one search query
  each instead of one/two. Current paid token rates are also lower.
- **The sweep is the biggest spender**: ~344 of the month's ~403 searches
  were verification runs, against ~59 from people. The 30-minute answer
  cache is live and measured (560 → 561 → 561 for a repeated question); if
  that is not enough, give the sweep a "skip the live-search journeys" mode
  for routine deploys and keep the full set for weekly runs.
- **`BRAVE_SEARCH_MONTHLY_LIMIT` is now a spend cap, not a free allowance**
  (900). The operator has not chosen that number under the new billing -
  ask before assuming it is right.
- **"group: dinner suggestion uses a member's taste" - fixed structurally
  2026-08-29.** The "What's on" pack was on every user's menu and took
  requests that were never about it (dinner question: 4/4 skill without the
  clock, 1/4 with it, and it failed a deploy's sweep twice). Wording in the
  pack description and in the router prompt was already right, and a third
  attempt measured worse. Now a shipped pack is offered only when the
  message names it: dinner 0/3, "what's on ..." 3/3, "quick brief ..." 3/3.
  Taught skills are unaffected. If a future pack needs to be found without
  being named, the answer is a semantic shortlist (the pattern MCP tools
  already use), not a sentence.

## Group chats — BUILT AND GATED 2026-08-28, live acceptance pending

The assistant in an iMessage group with approved users, as its own account
(ADR 0016; design, proof and status in `docs/GROUP_CHATS_ARCHITECTURE.md`;
diagram `docs/diagrams/group-chats-subsystem.svg`). Bridge, worker, pipeline,
attribution, delivery, admin, sweep journeys, and three real-model suites are
in; the unit gate and `sweep --only group` ran green before the deploy that
carried them (CHANGELOG).

**Done live on 2026-08-28 in "Groupie"** (`chat308729799386740866`, the
operator + jenos1): mention → answered in the chat in 22 s; thread reply →
answered (late, fixed); weather "here" → Somalia (fixed). The bridge's plist
now carries `IMESSAGE_BRIDGE_GROUPS`, `IMESSAGE_BRIDGE_READ_GROUPS=true` and
`IMESSAGE_BRIDGE_ADDRESSES=deep-matter@agentmail.to`. What remains is a
re-test on the build that carries the fixes (dd3cc92e): an @mention asking
the weather (answered for the speaker's city, or asked if none is on
record), a tap-and-hold reply with a question (seconds, not a minute), and
a "thanks!" reply (no bubble). For any other group, the steps:

1. find the room's identifier - `osascript -e 'tell application "Messages" to
   get {id, name} of every chat'` and pick the `iMessage;+;chatNNN` whose name
   matches;
2. add to `~/Library/LaunchAgents/com.anios.imessage-bridge.plist`:
   `IMESSAGE_BRIDGE_GROUPS=chatNNN` and `IMESSAGE_BRIDGE_READ_GROUPS=true`
   (`IMESSAGE_BRIDGE_ADDRESSES=deep-matter@agentmail.to` is already there:
   a mention is matched on the account's address, so the name each friend
   saved the contact under does not matter; `IMESSAGE_BRIDGE_DISPLAY_NAME`
   is optional and only adds "scout, ..." as a plain-word trigger); then
   `launchctl kickstart -k gui/$(id -u)/com.anios.imessage-bridge`;
3. in the group, from the friend's phone: "Scout, thai or pizza friday?" →
   one answer in the room; a tap-and-hold Reply to that bubble: "thai then"
   → answered; "thanks!" → no bubble; an unaddressed "lol" → nothing leaves
   the Mac (bridge log shows no forward);
4. `GET /api/v1/admin/groups` lists the room with both members;
5. `python -m backend.cli.explain_turn --user group:<slug> --last 3` shows
   `group: {speaker, members}` in each trace.

If anyone in the room is not approved, the assistant stays quiet and your
phone (`OPERATOR_ALERT_PHONE`) gets one text a day about that room.

**Candidate verified, not deployed:** conversational ❤️/👍 now queries only the
exact GUIDs of Scout's recent bubbles and becomes "yes, do that" only when the
readiness model's separate `accepts_offer` field says the targeted bubble
unambiguously offered one action. In a room the allowlisted reactor is mapped
to a current member and becomes the turn's speaker; missing or unknown identity
fails closed. Focused bridge/worker/API tests are 179/179 on the Mac; the Spark
candidate is 178 passed plus the expected macOS-only skip; the real-model
readiness suite is 33/33 and the accepted-search router proof 1/1. The exact
current-tree candidate also passed 2,213 non-functional tests with nine
documented environment-dependent skips. A live
tapback in Messages and deployment are still pending. The
remaining unbuilt trigger is the next otherwise-unaddressed message from the
person Scout asked; that needs a scoped expectation with a short TTL.

**Deploy #16 then showed the real defect behind "forget that":** with the
journey's own setup turn failed under model contention, "forget that" undid
a *task change from another conversation* - the change log's latest
undoable change was per person, not per conversation. Scoped to the
conversation now (migration `20260828_0012`); the sweep reports a failed
setup turn as the journey's failure. Deploys now retry a failed journey once
before paging.

**Two intermittent sweep gaps, traced and closed (2026-08-28):** "more
casual (draft referent)" - the resolver read "draft" every time, but a
draft turn could still be offered `edit_image` and the router took it
1-in-3; picture-editing tools are now withheld on draft turns and the
follow-up reading is traced on every routed turn. "forget that (memory
undo)" - its assertion counted every semantic row of the sweep user, so
earlier journeys' captures failed it in full sweeps; it asserts the change
log now. `sweep_journeys --keep` exists for the next one. The kept full
sweep (user `sweep_708ace97`) showed exactly that: the undo removed the
dentist row, the leftovers were "the user has a retail team" (captured from
the draft-email journey) and the next journey's restatement of the dentist.

**Fixed 2026-08-29 (they predated this session - four of five reproduce at
`7df424b6`):** the five red cases in
`functional/test_main_action_selector_behaviour.py` - a haiku routed to
generate_image, a polite "can you generate a labelled image of this?"
routing to nothing, an invented "Arlington, Virginia" when no place was
known, and two tests left stale by capabilities that shipped after them.
See the CHANGELOG for what each measured before and after. **The lesson to
carry:** this suite is not part of the deploy gate, so it drifted unseen for
at least a week. Consider adding it to `deploy.sh` (it costs ~7 minutes) or
running it weekly.

**Still red, deliberately: `test_search_routing_quality_meets_the_retired_cascades_floor`.**
Recall 0.806 against the 0.85 floor, the same five misses at this session's
base commit and with today's weather wording reverted - a real decline, not
variance and not from this session. The misses are all questions whose
subject the conversation never names ("did the merger go through", "what
time does the game start", "has the strike ended", "any news about the
merger", "is the farmers market open this sunday"): the subject-copy rule
added after the Surviving Paradise incident tells the router to call no tool
when nothing names the subject. Narrowing that rule to pointing words was
tried and measured *worse* (6 misses, two new: the euro cases), and was
reverted. Next step is the proper instrument, not another wording guess:
`ablate_prompt_rules` over the search rules plus `evaluate_tool_selection`,
then decide whether these cases should search in the person's own words or
whether the cases themselves encode behaviour the incident rule deliberately
replaced. The floor is left red on purpose - lowering it would hide the
decline.

**Router wobble, observed once (deploy #17's sweep):** "Scout hows the
weather here today?" in a group, with the speaker's place known, routed to
a history search; it was Weather in deploys #15 and #16 and 2/2 in
`test_weather_here_uses_the_known_place_or_asks`. Deploys retry a failed
journey once from #18 on; if this shows twice in one deploy, it is not a
wobble - trace it with `--keep` and read the `followup` and `route` in the
turn's trace before touching the router prompt.

**Observed once in the kept full sweep, not yet fixed:** the group dinner
question ("where should the two of us go for dinner on friday?") was routed
to a built-in skill pack that searched "events happening this weekend"
(off-subject results; the reply still answered from the room's Thai plan).
A dinner question is not a weekend brief. Measure with the evaluator before
touching the router prompt; the sweep journey keeps `Skill` out of its
accepted routes on purpose.

## Shipped 2026-08-24

**Sign-up collects a phone number, and approving someone allowlists them.**
The number is required at sign-up in E.164 (`backend/core/phone.py`), stored
encrypted with a separate digest, and approval does two things that used to be
done by hand and drifted: enrols the number as a subscriber in AniOS, then
calls `allow_recipient` on the Mac. Both gates, one decision. Verified live —
`saps21` signed up 03:23:17 and was approved 03:23:41 with both gates set.

**A newly approved person gets an introduction.** `backend/services/welcome_service.py`,
fired from the approve button. The message is generated by the reply model from
the same capability list the router offers as tools, so it describes what the
system can do today rather than what someone wrote in a paragraph once. Sent
after the bridge grant (the Mac refuses a number it has not been told about),
never fatal to the approval, and `user_accounts.welcomed_at` makes it
exactly-once. Existing accounts are deliberately **not** back-filled — they have
been using the assistant for weeks and an introduction now would read as a
fault.

**Data durability, which was the weakest thing here.** Before: two dump files,
one of them 20 bytes, both on the same NVMe as the live database, no schedule
and no restore ever attempted. Now: a nightly systemd timer, a mirror to
spark2, thirty-day retention pruned on both sides, Redis append-only, and a
restore proven end to end — 37 tables and 2,506 rows identical to live, then 65
encrypted values decrypted out of the restored copy with the escrowed key. That
last check is the one that matters; see [docs/RESTORE.md](RESTORE.md).

**The architecture page now publishes every canonical view.** The iMessage
bridge and Tasks & skills diagrams existed but were absent from the page's
publication list, which left its own completeness metric at 20/22. Both are now
included, and the freshness check fails whenever that list and the canonical
Mermaid source count diverge. The generated page reports 22/22; its structure,
unique embedded SVGs, source links, and zoom controls were checked locally.

## Live incident 2026-08-26 21:28 — a reminder became Scout's schedule, and "this" moved the wrong thing

What the operator saw: "adjust this to daily at 3pm", said about Scout,
moved their stretch reminder to 3 PM. What actually happened, from the
decrypted conversation rows and the task/schedule tables:

1. 21:28 "send another don tito reminder at 7" set the reminder correctly
   *and* the memory proposal agent read "at 7" as the sweep's cadence
   (its prompt said "asking for one to be set or changed states it just
   as plainly"), so Scout - daily 5 PM until then (runs 21:00-22:00 UTC) -
   became daily 7 AM, and the reply truthfully reported "the daily 7 AM
   Scout check is saved".
2. 21:30 "when did i say 7 am for scout?" - the reply invented a
   conversation ("back when we were setting up your recurring events
   sweep").
3. 21:31 "adjust this to daily at 3pm" - the router chose the task
   manager; the picker, given only the word "this" and two tasks, chose
   the only daily one (stretch, 18:00) and moved it to 15:00; the proposal
   agent moved Scout to 15:00 as well.

Fixed, verified, and deployed the same evening (see CHANGELOG 2026-08-26):
the proposal agent's `schedule` means the sweep's own cadence and never a
reminder; the proposal agent and the task picker both see the assistant's
previous reply; the picker is offered "none"; the router matrix carries
the Scout continuation as NO_TOOL; the reply answers "when did I say X?"
only from what it can see. Stretch reminder restored to daily 6 PM.

Then the journey sweep's Scout-continuation journey showed the route
itself still wrong (manage_tasks, with the picker's "none" as the only
thing between Scout and a moved reminder), and the 2026-08-23 note in
`backend/tools/manage_tasks.py` had already measured that no wording
fixes it. So the structural fix landed the same night: `scout_schedule`
is Scout's own tool (see CHANGELOG 2026-08-26).

Closed by the operator at 22:08 UTC the same evening: "i don't want
stretch reminders. only scout for 3pm everyday" - the stretch reminder was
cancelled on request and Scout stays daily at 3 PM (it had run daily at
5 PM before the incident).

**For the operator, one click:** GitHub -> repository Settings -> Branches
-> add a rule for `main` -> tick "Do not allow force pushes" (and "Require
linear history" if you like). The local pre-push hook now refuses rewrites
from this checkout, but only the server setting protects the branch from
every clone.

## Live incident 2026-08-27 15:55 UTC — "weather in DC" asked for a ZIP code, then got the wrong words

ama_edm (new that day, no locality on record) asked for DC's weekend
weather; the geocoder had nothing for "Washington, DC" so the reply asked
for a ZIP, and the forecast it then gave was Open-Meteo's WMO wording
("violent showers" on a 29% day, "overcast" on a mostly-sunny Saturday)
without Sunday. Fixed the same day: place aliases and fallbacks, NWS as
the US source, plain wording with the rain chance, weekdays and coverage.
See CHANGELOG 2026-08-27.

## Live incident 2026-08-27 02:41 UTC — a follow-up searched as a different show

jenos1, over iMessage, about Netflix's "Surviving Paradise": the router
searched "does only one person win at the end?" as Squid Game: The
Challenge and "you mentioned there was only one season" as Love Island
USA, and the reply answered about those shows. Read from the turn trace
in under a minute (`explain_turn --user jenos1`). Fixed the same night:
the query copies the conversation's subject (router + composer, tested on
the query text), and the ranker's new `on_subject` flag turns wrong-subject
results into a disclosure instead of an answer. See CHANGELOG 2026-08-27.

## State at the end of 2026-08-26 — the "no more bugs on done items" wave

Shipped through `scripts/deploy.sh` (the only deploy path now; it runs the
unit suite and routing gate before, the journey sweep and search harness
after): undo for reminders and Scout's schedule (`scheduled_task_changes`),
one writer for Scout's cadence (`scout_schedule`; the proposal agent has no
schedule field), a trace on every turn (`backend.cli.explain_turn`), a green
unit suite (1841; the 24 "stale" failures were the test container's missing
Redis and stale image copies), eight referent-shaped multi-turn journeys,
a pre-push hook against rewriting `main`, and - found only by an HTTP
end-to-end check - the stream wrapper losing every per-turn ContextVar
between frames (`_with_heartbeat` now runs each pull in one context).

Added 2026-08-27 (see CHANGELOG): a **follow-up resolver** - one reading
of "this/it/again" before the router, the research rounds and the trace
(the structural answer to the week's whole incident class); **"forget
that"** for automatic memory saves; the **ablation tool**
(`backend.cli.ablate_prompt_rules`) for measuring the router prompt's
sentences against each other; the ranker's **on_subject** flag turning
wrong-subject results into a disclosure.

Still open, in order of risk:
1. **The router's tail.** With the resolver alone: regenerate 5/6 (from
   3/6), followup_subject 6/6, diagrams 12/12 - but opinions about a
   picture moved from edit to *show* (0/9) and draft continuations stayed
   6/12. So: `discuss_image` (a named "talk about it, change nothing") and
   no automation offered on a draft turn. Measure again; if writing
   follow-ups still leak, the next step is a `regenerate_image` row and a
   two-stage router.
2. **Run the ablation** on the router prompt (`--categories` for the weak
   ones first) and delete what costs nothing.
3. **Two prompts with no functional pin yet** (declared in their headers,
   enforced by `test_functional_coverage_completeness`): `refinement/keep_scene`
   and `style/distill` - both need the edit model on a real picture.
4. **Operations on several tasks at once.** "delete the paused ones"
   (real phrasing) reaches a picker that chooses one task; cancel/pause of
   a set is not supported. Needs `manage_tasks` to accept a selection
   ("all paused", "the weather ones") and a confirmation line listing what
   it touched.
5. **GitHub branch protection** - the operator's click (above).
6. Tavily plan/credits; schedutil on the Sparks; wake-on-LAN for the
   desktop; a fare API for trips (all earlier notes).

## What is still open

**A third backup copy on the Mac — LIVE 2026-08-25.** Remote Login is on,
spark1's `spark1-backup-mirror` key is authorized for `sparkuser@172.16.8.2`,
and spark1's `.env` lists both mirrors. Proven with a real run: the same
dump (`anios_db-20260824-222902.sql.gz`, 37 tables) landed on spark1, spark2,
and `/Users/sparkuser/anios-backups`, 534 sealed values inside and zero key
material. The first three-copy run mirrored to nobody: the `.env` parser
stripped spaces along with carriage returns and fused the two hosts into one
name — fixed in `backup-db.sh` the same night. **The Mac still holds
ciphertext only: never copy `ENCRYPTION_KEY` onto it.** The key is escrowed at
`C:\Users\Ani Mallya\anios-recovery\anios-keys.env` on the Windows box.
(Cosmetic: the Mac's `~/.bashrc` line 2 prints `$: command not found` on
every non-interactive ssh; harmless, not fixed, the operator's file.)

**FLUX decision 2026-08-25: the desktop hosts FLUX.2 Klein 9B, and image
work is available only while the desktop is on.** The operator revived the
RTX 5080 box for exactly this: ComfyUI is to be the only GPU tenant there,
and when the machine is off the assistant says so ("the machine that runs
image generation is off - try again later"; `_image_provider_failure_message`,
29/29 gated). spark1's side is ready: defaults moved to the 9B pair
(`flux-2-klein-9b-fp8.safetensors` + `qwen_3_8b_fp8mixed.safetensors` -
the 8B encoder is mandatory, the 4B one produces garbage silently), the
Klein workflow nodes are unchanged from the 4B. **VERIFIED from spark1, 2026-08-25 03:50 UTC.** The desktop session
installed Plan B (`flux-2-klein-9b-Q6_K.gguf`, ungated, plus the official
`qwen_3_8b_fp8mixed.safetensors` encoder; the fp8 9B is HF-gated and the
operator's account is not on its list), started `anios_comfyui` as the only
GPU tenant, and measured 6.0 s warm / 114.5 s cold at 1024x1024, 13,755 MiB
peak. spark1's `.env` now points `IMAGE_PROVIDER_BASE_URL` at
`http://172.16.8.6:8188` with the Q6_K model names; backend,
presentation-worker, and local-capabilities were rebuilt (the running image
had predated the GGUF-loader commit - the baked-image trap, again - so the
first probe reached ComfyUI with a plain `UNETLoader` and a 400) and
recreated. A provider-level probe through the backend's own classes then
generated a 1024x1024 image in 16.9 s and Kontext-edited it in 118.6 s. That
second number is the model swap: Klein and Kontext cannot both stay resident
on 16 GB, so a generate followed by an edit pays a cold load of roughly two
minutes; ComfyUI runs prompts serially, so concurrent requests queue rather
than OOM. The Docker Desktop firewall rule that allowed any port from any
remote (an unauthenticated ComfyUI answering everything that could route to
`172.16.8.6`) was scoped to 172.16.8.0/24 by the operator on 2026-08-25;
spark1 and the Mac still get HTTP 200 from `:8188`, which is the allow side
proven. The deny side cannot be tested from inside the subnet - a probe from
outside the /24 is the only thing that would prove it. **Edits moved to the Klein 9B (13:4x UTC), measured first:** with the vision
model judging the pixels, the 9B added a yellow umbrella on request and
turned the wall white, in 20.0 s / 18.3 s while resident, against Kontext's
109.6 s cold / 43.7 s warm for the same edits (both editors passed both
judgements; the source had no umbrella). The 4B's "preserves its reference,
adds nothing" failure does not hold for the 9B, so `IMAGE_EDIT_MODEL` is
empty on spark1: one resident model, no Klein-Kontext swap, no swap-induced
VM-memory crash, and an edit after a generation in seconds. Kontext stays
one env var away (`IMAGE_EDIT_MODEL=flux1-kontext-dev-Q4_K_M.gguf`) if a
class of edit needs it; the judgement was two instructions on one picture,
not a fidelity benchmark. **Seventh scenario pass with edits on Klein: 7 of
7** (`python -m backend.cli.exercise_image_scenarios` inside the backend
container) - every edit on the picture it was meant for, lineage intact,
no ComfyUI restart, delete-all clean. **Correction, measured on the desktop itself 2026-08-24 22:50:** the
desktop *is* on the LAN, at `172.16.8.6` on its Wi-Fi adapter, same /24 as
the Sparks and the Mac. The earlier scan missed it. Its wired `Ethernet`
adapter is on a 169.254 link-local address, which is probably what the scan
found.

**Desktop readiness, measured on the box 2026-08-24 22:50.** All read-only;
nothing on that box was changed. Two of these started as blockers and are
resolved — both are kept, with the reasoning, because the corrections are more
useful than a tidy list would be.

**Verdict: Plan A is sound on paper and nothing technical is in the way.** What
remains is three things only the operator can authorise, listed at the end.
Plan B needs no code: commit `1bc2c2df` makes both Klein workflows follow the
model file name, so a `.gguf` routes to `UnetLoaderGGUF` and anything else to
`UNETLoader`. Dropping `flux-2-klein-9b-Q6_K.gguf` (~7.5 GB) into
`diffusion_models/` and pointing `IMAGE_MODEL` at it is the entire fallback.

- **VRAM: 16,303 MiB total, 13,727 free** (the rest ordinary Windows desktop
  processes — no compute tenant). I first read this as fatal, summing the 9B
  and its 8B encoder as ~17 GB co-resident. **That was the wrong model of how
  ComfyUI loads**: it encodes with the Qwen encoder, then evicts it to system
  RAM to make room for the diffusion model, which is why Comfy's own Klein
  guide lists 16 GB for the 9B fp8 pair. The figure that actually matters is
  the eviction target — and **I first reported that wrong.** The host has
  31.9 GB, but the container does not get it: with no `.wslconfig`, Docker
  Desktop's WSL2 VM takes the default 50%, so ComfyUI's own boot line reads
  **`Total VRAM 16303 MB, total RAM 15947 MB`** and `free -m` inside the
  container agrees. **The eviction ceiling is 15.57 GB, not 31.9 GB**, and
  14.35 GB of it is reserved as pinned memory.

  That ceiling is the real constraint, because the model pairs sit right
  against it: encoder 8.07 + Kontext 6.46 = **14.53 GB**; encoder 8.07 +
  Klein 7.33 = **15.40 GB** — before activations or a 2 MP latent. On
  2026-08-25 04:30:19 UTC the container exited mid-request during a Kontext
  edit at `IMAGE_EDIT_MEGAPIXELS=2.0` on a 1024x1024 source, and
  `restart: unless-stopped` brought it back: `RestartCount 1`,
  **`OOMKilled: false`, `ExitCode: 0`**, no CUDA error and no OOM anywhere in
  the log. A clean exit with no torch exception is VM memory pressure, not a
  GPU OOM.

  **The real fix is `.wslconfig` with `memory=24GB`** (then `wsl --shutdown`
  and restart Docker Desktop) — on a 32 GB host that gives the eviction target
  genuine headroom. The interim lever, and what was set when the box had to
  power down, is **`IMAGE_EDIT_MEGAPIXELS=1.0`**: it shrinks the latent and
  activations on the heaviest path, and a 1 MP edit of a 1024x1024 source is
  not a visible downgrade.
- **Neither 9B file is on the box.** `diffusion_models/` has
  `flux-2-klein-4b-fp8.safetensors` (3.79 GB) and
  `flux1-dev-kontext_fp8_scaled.safetensors` (11.09 GB);
  `text_encoders/` has `qwen_3_4b.safetensors` (7.49 GB), not the 8B. So
  spark1's defaults currently name files that do not exist — a missing
  checkpoint at request time, not a fallback.
- ~~ComfyUI is 0.28.0 and `nodes_flux2.py` is absent~~ — **retracted, this was
  a bad inference.** Upstream puts the FLUX.2 nodes in `nodes_flux.py`
  alongside the FLUX.1 ones; there is no `nodes_flux2.py` to be missing. All 13
  nodes the workflow needs are present, `CLIPLoader` offers `type="flux2"`
  (`nodes.py:995`), and `UnetLoaderGGUF` exists for the GGUF fallback. The
  checkout is `c9602625`, **18 July 2026**, `master` — the "0.28.0" is the
  generated version string, not the checkout age. No `git pull` needed.
- **`anios_comfyui` exited 137** (SIGKILL) 47 hours ago; cause not established.
  Its image is right for this card — `nvidia/cuda:12.8.0-runtime-ubuntu22.04`
  with cu128 wheels, i.e. Blackwell/sm_120. The "cannot emit sm_121" caveat in
  these notes is about the DGX GB10, **not** this box.
- **Port 8188 is closed.** Nothing listening (container down), and there is no
  Windows firewall rule for 8188 or ComfyUI, so inbound from 172.16.8.0/24 is
  dropped by default once it starts. Adding one needs admin on the desktop.
- **No Hugging Face auth**: no `~/.cache/huggingface/token`, no `HF_TOKEN`. The
  9B is gated, so this blocks the download outright.
- Present and healthy for the Kontext editing path:
  `unet/flux1-kontext-dev-Q4_K_M.gguf` (6.46 GB),
  `text_encoders/t5-v1_1-xxl-encoder-Q5_K_M.gguf` (3.15 GB),
  `clip_l.safetensors`, `vae/ae.safetensors`, and the `ComfyUI-GGUF` custom
  node.

**DONE 2026-08-24 23:40 — image generation runs on the desktop, on Plan B.**
Measured, not inferred:

| | |
|---|---|
| model | `flux-2-klein-9b-Q6_K.gguf` (7,865,424,160 B), `unsloth/FLUX.2-klein-9B-GGUF` |
| encoder | `qwen_3_8b_fp8mixed.safetensors` (8,664,848,742 B), Comfy-Org, ungated |
| loader | `UnetLoaderGGUF`, chosen by `_model_loader()` from the `.gguf` suffix |
| cold / **warm** | 114.5 s / **6.0 s** at 1024x1024, 4 steps |
| **peak VRAM** | **13,755 MiB of 16,303**, sampled every 2 s during the run |
| LAN | `system_stats` from spark1 → HTTP 200 in 0.015 s |

Run through `ComfyUIImageProvider._workflow()` rather than a hand-written
graph, so the proven path is the one the backend takes. Output verified as real
1024x1024 PNGs. **Peak never approached the ~17 GB predicted** — the eviction
model is correct and the earlier VRAM worry is settled empirically.

**A slow first edit is a cold load, not a fault.** Generation holds Klein 9B
Q6_K (7.33 GB); the Kontext edit holds `flux1-kontext-dev-Q4_K_M.gguf`
(6.46 GB) with a different encoder. Both together do not fit 16 GB, so
alternating generate → edit → generate makes ComfyUI evict and reload each
time. Measured: **114.5 s cold against 6.0 s warm.** So "make me a picture"
followed by "now change it" costs about two minutes on the second request, and
it will be reported as a hang. It is not.

Related, and recorded because I got it wrong first: **ComfyUI executes prompts
serially** (`queue_running` / `queue_pending`), so overlapping requests queue
rather than running together. There is no concurrent-workflow OOM to defend
against, and `IMAGE_MAX_CONCURRENCY=1` (settings.py:522) already holds. The
semaphore in `ComfyUIImageProvider` is per instance and `dependencies.py`
builds three, so two requests can be in flight in the app — harmless, because
ComfyUI serialises them anyway. Do not "fix" that by assuming it causes OOMs.

**Plan A remains unavailable.** `black-forest-labs/FLUX.2-klein-9b-fp8` returns
**403 GatedRepo** for `deepmatter77`; access needs a click on the model page and
no token can self-approve. Set `IMAGE_MODEL=flux-2-klein-9b-Q6_K.gguf` unless
that gate is cleared.

**CLOSED 2026-08-25 — 8188 scoped to the LAN, with one honest caveat.**
Publishing 8188 had exposed an unauthenticated ComfyUI to every source that
could route here, because `Docker Desktop Backend` allows **Any port from Any
remote** and an extra *Allow* rule cannot narrow that — Windows Firewall
permits if any Allow matches. The fix is a **Block** rule, since Block takes
precedence, written as the complement of the LAN because "block except X" is
not directly expressible:

```powershell
New-NetFirewallRule -DisplayName "Block ComfyUI 8188 outside LAN" -Direction Inbound `
  -Protocol TCP -LocalPort 8188 -Action Block -RemoteAddress @(
    "0.0.0.0-126.255.255.255","128.0.0.0-172.16.7.255","172.16.9.0-255.255.255.255")
```

The `127.x` gap keeps loopback working. Verified after applying: loopback 200,
spark1 200, spark2 200 — nothing that must work broke.

**The caveat, stated because it would be easy to imply otherwise: the block
itself was not empirically proven.** Every traffic source available on this
network NATs into `172.16.8.0/24` — a container's probe arrived as
`172.16.8.6 → 172.16.8.6:8188`, i.e. from inside the allowed range, so it
proved nothing. Testing it properly needs a host genuinely outside the `/24`.
What is established is that the rule is correctly formed, that Block precedence
is documented behaviour, and that the permitted paths still work.

Scale of the original risk, also worth stating plainly: NAT meant this was
reachable by devices on the home network, not from the internet, unless
someone had port-forwarded 8188.

**Awaiting the operator, and only the operator.** A peer session asking is not
authorisation for any of these:

1. **Hugging Face login** — the 9B is gated under FLUX Non-Commercial.
2. **~18 GB of downloads** — `flux-2-klein-9b-fp8.safetensors` (~9.5 GB) into
   `diffusion_models/`, `qwen_3_8b_fp8mixed.safetensors` (~8.5 GB) into
   `text_encoders/`. The `vae/flux2-vae.safetensors` already present is right.
3. **An inbound Windows firewall rule for TCP 8188, scoped to 172.16.8.0/24**
   — needs admin on the desktop.

Then, in order: `docker compose --profile comfyui up -d comfyui` with
`COMFYUI_DOCKERFILE=Dockerfile`, confirm via `nvidia-smi` that ComfyUI is the
only compute process and no other anios container started, and prove it with
`curl http://172.16.8.6:8188/system_stats` from a Spark plus one real 4-step
1024x1024 generation. Report wall time and peak VRAM during the run; on OOM,
switch to Plan B and report the same numbers. Only then does spark1's `.env`
get `IMAGE_PROVIDER_BASE_URL=http://172.16.8.6:8188` and the 9B names.

The earlier headroom analysis, kept for the record:
**FLUX did not fit on the Sparks as they stand.** The sm_121
blocker is solved — `docker/comfyui/Dockerfile.gb10` (NVIDIA CUDA-13 PyTorch
base, aarch64), selected by `COMFYUI_DOCKERFILE` in `.env`, and
`IMAGE_PROVIDER_BASE_URL` is now env-overridable so placement is an `.env`
decision. The real blocker is **headroom**: measured 2026-08-24, spark1 has
~9 GiB available and spark2 ~2 GiB, because DeepSeek TP=2 holds ~97 GiB on each
node (weights+overhead are a ~90 GiB/node floor, so trimming KV frees only
~3 GiB). 4B needs ~14 GiB, 9B ~18 GiB — neither fits while DeepSeek holds both
nodes, and over-allocation hangs a box with no BMC. The desktop 5080 is retired
by decision, so it is not the fallback. Options recorded for the operator: run
DeepSeek TP=1 on one node to free the other; a GGUF-quantized 4B (~8 GiB, still
tight); or accept no local image gen and un-advertise `generate_image`/
`edit_image` (both are registered builtins, so the welcome currently promises a
capability with no backend). The 9B is additionally gated + FLUX
Non-Commercial; the 4B is Apache/ungated. Checkpoints are on the powered-off
desktop and must be re-fetched from HuggingFace (reachable from spark1).

## BUILT — active recall: `search_history` (2026-08-24; gate-verification pending)

The spec below was implemented the same day, from the Mac. Everything landed
as designed: `RecallHistoryAction` + `backend/tools/search_history.py` in the
registry; `search_turns` on the memory service (questions kept, exchange-level
dedup, excerpts bounded at 1,000/1,500 chars); `_recall_history_evidence` in
the conversation service (embeds the model's query, filters out what the
visible window already shows, never costs the turn); its own prompt section
(`_render_history_recall_context`, own-record framing, injection-resistant
wording) riding a new `past_conversations` budget section at priority 2 —
**the section priorities below it were renumbered** (tools 3, history 4,
images 5, recalled 6, memory 7), which was safe because enforcement is off
and no floors were ever recorded. `_runnable` now passes three action kinds.
The chat-orchestration diagram gained the flow (SVG re-rendered on spark1).

**Verification: GREEN, run on spark1 the same day through the gate's test
container** (working tree mounted, skips-count-as-failures):
`test_history_recall.py` 10/10; `functional/test_history_recall_behaviour.py`
7/7 against the real router — every backward-reference phrasing chose the
tool, ordinary questions and a visible-context follow-up stayed out, so the
routing-precision risk did not materialize; and the full tool-selection
matrix (`bash scripts/gate.sh`, 294s) stayed green with the new tool offered,
which is the no-regression proof for widening the router's option set. If a
future run flakes, tune the description by subject shape, never by adding the
failing phrasings to it.

**One loose end: chat-orchestration.svg is stale.** The .mmd (canonical)
carries the new flow; the SVG could not be regenerated — spark1's host has no
node, and a throwaway node:22 container gets as far as mermaid-cli's
puppeteer failing to launch its browser ("Failed to launch the browser
process", a container sandbox/provisioning issue; playwright's own install
succeeds and is not what mermaid-cli uses). Render it from whatever
environment produced the 2026-08-24 22/22 suite; the freshness check will
flag the pair until then.

## The spec as approved (kept for the record)

**The gap it closes.** Recall today is passive: top-3 similar past remarks are
injected before the model answers. A detail that was never fact-shaped, got
compressed out of the digest, and does not resemble the current wording sits in
Postgres but never reaches the model — recorded, not recallable. The operator's
stated bar is "recall anything at any point in time"; the fix is letting the
model *search its own transcript store* on demand, the way it can already
search the web.

**What exists to build on (all verified in source).**
`Conversation` rows are one per exchange with a pgvector `embedding` per turn
(`memory/repository.py::get_recalled_turns` is the passive query — user-scoped,
`embedding IS NOT NULL`, excludes the current conversation). Builtins are one
`BuiltinTool` row each (`tools/base.py`; label + router description in one
place), actions are frozen dataclasses in `tools/actions.py`, and search
evidence is injected at `conversation_service.py:1678` (`context["search"]`)
where it rides the "evidence" prompt section and the context budget.

**The build.**
1. `RecallHistoryAction(query: str)` in `tools/actions.py`. It must join
   `SearchAction`/`ToolboxAction` as the *third* action kind that survives to
   the reply path (that list is currently hardcoded to two — see the
   2026-08-20 handoff entry on dropped actions).
2. A `BuiltinTool` row: name `search_history`, schema `{query}` required
   (`required_text` house rule: empty query = no call). Description states the
   principle, not cases: it fires when the user refers to something from a
   past conversation that is not in view; a question answerable from what is
   already visible selects no tool.
3. Execution: embed the query with the existing provider, then a wider
   variant of `get_recalled_turns` — top ~12, cosine ≤ 0.6 (passive recall's
   0.45/top-3 stays untouched), exclude the current conversation, return
   `{when, said, answered}` snippets with timestamps. **No SQL text search is
   possible** — `query`/`response` are `EncryptedText` — so any keyword
   refinement happens Python-side over a bounded candidate set (e.g. the top
   200 by embedding), never a full-table decrypt scan.
4. Inject results into `context["search"]`-shaped evidence (untrusted-literal
   framing like everything retrieved), so budgeting, enforcement, and the
   buried-evidence gate apply unchanged. The iMessage worker gets the feature
   for free — same `process_request`.
5. Tests: structural (scoping, exclusion, empty-query-no-call) plus
   functional per the completion rule — a seeded old remark is found and used
   in the answer; the existing 52-case routing floor still passes so ordinary
   turns don't start misfiring into recall; assert properties, not wording.
   Routing on a 4B model is the known risk (see "The 4B ceiling") — measure
   the tool's trigger precision before trusting it, and keep the description
   subject-shaped, not phrase-shaped.

Latency cost: one embedding call + one pgvector query on selected turns only.
Diagram impact to assess at build time: chat-orchestration view if action
flows are drawn there.

## Recall scalability wave — BUILT AND VERIFIED 2026-08-24 (cad31224)

The five recorded limitations of the first search_history cut are closed, and
each fix ran on spark1 the same night: turn vectors now embed BOTH voices
(backfill re-embedded 188/188 rows into the `#qr1` space via the test
container with `-e EMBEDDING_BASE_URL=http://vllm-embedding:8000` — spark1's
host-style .env value otherwise leaks into the container and refuses);
retrieval matches only the current model+scheme signature so a space change
degrades to invisible-until-rebuilt, with the signature-driven backfill as the
one-command rebuild; `ix_conversations_embedding_hnsw` is live (applied via
the tree-mounted test container, verified in pg_indexes); the model states
time bounds as ISO dates in its tool call (never regex over prose) and they
narrow the search in SQL; misses log the nearest rejected distance so the 0.6
threshold becomes measured; excerpts carry truncation markers; the active
search probes both the router's query and the user's raw phrasing. Gates:
structural 13/13, functional 8/8, tool-selection matrix green. Multi-round
history search stays deliberately deferred until miss telemetry argues for it.

## Live incident 2026-08-24 23:52 — a debate point became a stored preference

In the operator's iMessage thread, "but conversation history will be
summarized and important facts stored in memory" — a rebuttal in a technical
discussion about context sizing — was answered as if it were an instruction
("Got it — noted and saved"), and the memory pipeline persisted it as a
user_explicit semantic fact describing how the system already works. No
context was lost (same conversation, 49 turns, prior exchange 78 minutes
earlier and inside the window): this is the documented over-capture class
(Scout interests from task talk, 2026-08-21) surfacing in the semantic
pipeline. The junk row (c6f33d16) was deleted. The real fix is prompt work on
the memory classifier — distinguishing a statement about the system in a
design discussion from a standing preference — done the recorded way:
reproduce the verbatim turn at temperature 0 first, one wording attempt,
functional-gated against the existing interest-capture cases.

## Reranker stage — DEPLOYED AND VERIFIED 2026-08-25 (d8887d30..92d62c83)

Qwen3-Reranker-0.6B serves on spark1 as `vllm-reranker` (same ARM image as
the embedding service, documented classifier hf_overrides, 0.03 utilization,
max-model-len 2048 after 4096 measured spark1 idling at 3 GiB free - the
trim bought back 2). `backend/core/reranker.py` speaks `/v2/rerank` - on this
build /v1 and /rerank reset the connection while /v2 answers in the JinaAI
shape - and history recall now fetches a top-40 and lets the cross-encoder
cut it to twelve, fail-soft to cosine order on any failure (an empty
RERANKER_BASE_URL switches the stage off entirely). Verified: live ranking
correct (0.987 answer vs 0.293 decoy), structural 5/5, functional 2/2,
history-recall 8/8, tool-selection matrix green.

One instructive regression, caught by the gate and worth remembering:
**adding optional fields to a tool schema moves the 4B router's decision
boundary.** The since/until additions made "make it more casual" (a revision
of the draft on screen) route to history search. Fixed on the first wording
attempt with a principle, not a phrasing: a short follow-up continuing work
in view is part of that work, never a reference to the past. Any future
schema touch on any builtin should expect to re-run its behaviour suite.

Follow-up MEASURED 2026-08-25, and the answer is no for now. The swap is
built and selectable - `DISCOVERY_RERANKER_SOURCE=service` routes Scout's
RerankProvider contract to the vLLM Qwen3 reranker through
`backend/embeddings/service_reranker.py`, probabilities converted back to
log-odds so MIN_ATTRIBUTION_MARGIN keeps its meaning - but
evaluate_discovery_ranking scored attribution 0.25 under the service
against 0.50 local (both below the harness's own 0.60 floor; local's
failures are wrong answers, the service's are all margin-misses). Default
stays `local`. That both models fail the floor says shortlist attribution
itself is weak and the labelled cases are seeded judgements worth
correcting; revisit at the Qwen3-VL migration, by the same harness.

## Embedding research verdict, 2026-08-25 (for the coordinated space migration)

Current text leaders: the Qwen3-Embedding family tops open MTEB; Tencent's
KaLM-Embedding-Gemma3-12B scores higher but is weeks old with no production
record. For THIS system the decisive fact is unchanged: text and vision are
one aligned nomic 768 space, so the text embedder cannot move alone.

**The designated migration target at hardware ramp: Qwen3-VL-Embedding
(2B/8B) + Qwen3-VL-Reranker (2B/8B).** One family, one unified space across
text, images, screenshots and video; Matryoshka output (can emit 768, so the
Vector(768) columns need no schema surgery); quantization-aware training;
vLLM-servable; and the reranker speaks the same /v2/rerank contract the
deployed 0.6B already uses - the multimodal step becomes a compose model-name
change plus one signature-driven backfill per store and a re-measure of the
two distance thresholds. jina-embeddings-v4/reranker-v3 rejected: stronger
per-parameter but CC BY-NC and no vLLM support. The cutover is sized for the
ramp, not before: the 2B pair wants ~10+ GiB that today's boxes do not have.

## Hardening wave — BUILT AND VERIFIED 2026-08-25

Four improvements closed in one pass, each verified on spark1:

**The memory classifier no longer stores the discussion as the user.** The
23:52 over-capture was reproduced first (the verbatim rebuttal plus two more
system-statement shapes, all failing at temperature 0), then fixed in the
prompt with principles, not phrasings: a statement about how the assistant
or any system under discussion works is the work at hand and fills nothing;
semantic facts are what the user states about themself; another person's
fact remains theirs. The first wording said "about the user's own life" and
the model read a daughter's ballet into it - the refinement to
states-about-themself closed that. `functional/test_memory_capture_discipline.py`
pins both sides; the full memory-capture batch runs 38/38.

**The phone/address digest is keyed (C12 closed).**
`discovery.addressing.address_digest`, HMAC-SHA256 from `ENCRYPTION_KEY`
(falling back to `SECRET_KEY`), in all four consumers at once; the rekey CLI
moved 1 access request + 14 subscribers and reports zero on re-run, which is
the proof the stored digests now match what the lookups compute. A
source-inspection test forbids the unkeyed path from returning. Rotating
`ENCRYPTION_KEY` or restoring a pre-rekey dump now requires
`python -m backend.cli.rekey_address_digests` afterwards.

**The memory export carries the sign-up phone** (`sign_up` section, schema
version 3): the approved access request keeps the number keyed by
desired_username, the one place a per-table coverage sweep cannot see.

**The loopback binding outage, caused and fixed the same evening.** Applying
the committed 127.0.0.1 port bindings for db/redis broke every NEW container
connection - services dialled the host's LAN address, established
connections coasted, health stayed 200 while 50 refusals accumulated.
Containers now address `db` and `redis` over the compose network (the
binding never touched it) and the gate's `POSTGRES_HOST` is literal `db` so
spark1's host-oriented .env value cannot leak in. See the new trap below.
One aftershock surfaced on the post-deploy health sweep: `up -d` had left
memory-maintenance and storage-collection running with the old env (28h
uptime, silently failing every job), and only an explicit
`up -d --force-recreate` of the pair moved them. After any compose env
change, check `docker ps` uptimes against the deploy time rather than
trusting up -d's own output.

## Image scenarios on the real chat path — measured, two defects fixed, 2026-08-25

Seven scenarios driven through `POST /api/v1/chat` (SSE) and
`/vision/analyze` inside the backend container - the browser's and the
iMessage worker's exact path - with the desktop generating. **Verified:**
generate (artifact_ready), upload + ask (the VLM described the picture),
edit the newest uploaded picture with no selection (child's
`parent_artifact_id` = the upload), and a question about a picture answered
in words with no artifact ("The bicycle in the first picture is red"). **Two
defects found, both fixed and gated, both awaiting an end-to-end re-run
when the desktop is next on:** (1) a generated picture was never indexed
into the visual-memory description store - only uploads were - so with no
explicit selection "add a yellow umbrella" right after a generation had no
edit candidate at all, and "edit the bicycle picture" found nothing; a
generated picture is now indexed by its prompt and an edit by its origin
plus the instruction (`ImageArtifactService._index_description`, fail-soft,
deleted with the artifact). (2) When that fall-through reached the plain
reply, the model answered "Here's the updated image with the yellow umbrella
added" for pixels never touched; `_render_edit_state` now tells the reply
that nothing was changed, and `functional/test_image_edit_state_behaviour.py`
holds three registers of the request at 4/4. **One infrastructure finding:**
the explicit-selection Kontext edit died with "server disconnected" at
04:30:16 UTC together with a generation that was not mine - ComfyUI had
exited cleanly (`ExitCode 0`, no CUDA error) under the WSL2 VM's 15.6 GB
RAM ceiling with Klein, the 8B encoder, and Kontext swapping. Edits now run
at `IMAGE_EDIT_MEGAPIXELS=1.0` (spark1 `.env`, verified generate 114 s cold +
edit 115 s cold after the restart); the structural fix is a `.wslconfig`
with `memory=24GB` on the desktop, an operator host change for its next
boot. **Third pass, after the fixes and at 1 MP (04:44 UTC): 6 of 7.** The
unselected edit right after a generation now edits that picture (child's
parent = the generated one), the explicit selection edits the chosen
picture with no ComfyUI restart, "edit the bicycle picture" resolves by
description into the bicycle lineage, generation, upload + ask, and the
question all pass. The one failure was new and different: for "make the
background of this picture purple" (no selection, right after the upload)
the router chose *no tool* this time, and the plain reply - its history now
full of "Editing ..." turns - wrote "Editing a red bicycle with a wooden
basket" for an edit it never made and a basket that did not yet exist. The
no-change block is therefore rendered whenever a picture is in view on the
plain path (`_render_edit_state`, neutral wording, 5/5 including a plain
question), rebuilt and redeployed. That routing shape - an
imperative edit with no selection after an upload turn - is now in the
tool-selection floor set (matrix 7/7 with it). **Fourth pass (04:55 UTC):
6 of 7 again, and the seventh changed shape** - the router chose edit this
time, but with no selection "this picture" edited the bicycle, not the
newest upload. Cause: referent candidates came only from a similarity
search over descriptions, and a bare "this" matches nothing, so the
picture the person was looking at was never offered and the resolver's
recency rule had nothing to apply to (in the second pass the same step was
right only because generated pictures had no descriptions yet). Fix: the
three newest ready pictures are always offered alongside whatever
similarity retrieved (`ImageReferentSource`, `RECENT_CANDIDATES`);
structural 44/44, referent-resolution behaviour 7/7, redeployed. Real
clients send the active picture explicitly (browser chip, iMessage
reply-pin) and never hit this; an API client without image tracking did.
**Fifth pass (13:08 UTC): 6 of 7 still** - the upload was now offered and
the resolver still chose the bicycle, reading "background" in "make the
background of this picture purple" as a detail matching its brick wall.
Fixed in the resolver prompt as a principle: "this" points at the most
recent candidate, and naming a part any picture has (background, sky,
colours, something to add) is not a distinguishing detail; only a detail
that fits some candidates and not others chooses an older one. Reproduced
first as three registers plus a separating-detail control in
`functional/test_referent_resolution_behaviour.py`; one of my own cases
("the sky in this one") was wrong rather than the model - among a flag, a
sunset portrait, a bicycle, and a kitchen a sky *is* separating - and was
replaced. 11/11, rebuilt and redeployed. **Sixth pass (13:22 UTC): 7 of
7.** Generate; unselected edit of the generated picture; upload + ask;
unselected edit of the upload landing on the upload; explicit selection;
"the bicycle picture" by description; a question answered in words - every
child's `parent_artifact_id` as expected, no ComfyUI restart, delete-all
clean. That is the image subsystem verified end to end through the chat
API. Still not driven by me: the browser's own clicks and an inbound
iMessage text-then-edit (the send half is proven), both recorded above.

## A newcomer's first evening: four defects and one exhausted key — 2026-08-25

Zakarya's first iMessage conversation (six turns) surfaced, in order:

- **"Can you show me that image?"** was answered "I can't display it here" with
  the picture already recalled into the model's context. No action existed
  that put an existing picture back in front of a person. `show_image` is now
  a router tool: the referent resolver picks the picture, the existing
  artifact is re-streamed as `artifact_started` + `artifact_ready` (the web
  fills the card, the iMessage worker attaches the photo), several matches
  show the newest and offer the rest. The web client's `artifact_started`
  validation accepted only fresh generations and would have thrown; widened.
- **"Can you regenerate it?" / "A general one"** was answered "I'll create a
  fresh one. Give me a sec." with nothing running. The router prompt now says
  a short answer to the assistant's own question about a picture completes
  the request; the honesty guard renders whenever the conversation has
  carried a picture, not only when one is in view, and forbids promising one.
- **"Who am I?"** got "I don't have your name": nothing seeded a profile at
  approval. Approval now writes the sign-up name; alippe and zakarya were
  seeded by hand.
- **A burst of photos** over iMessage: the worker waited nine seconds for
  iCloud to finish downloading and answered one photo per message. It now
  waits about a minute with backoff, answers every photo (up to four,
  numbered), and says "still downloading" rather than "couldn't open". The
  fourth photo that evening failed for a different reason: the backend was
  restarting under a deploy at that moment.
- **Writing inside generated pictures was not English.** `IMAGE_TEXT_SUFFIX`
  now rides on every generation prompt; the tenth image scenario reads a
  generated sign back through the vision model ("OPEN").
- **"Events that have passed"** is not the date - the reply and router get
  the real clock - it is that **every web search was failing**: Tavily
  answers 432 (plan limit). The key is at 993 of the Researcher plan's 1,000
  credits for the cycle, and the local ceiling had been counting calls while
  an `advanced` search bills two credits, so it never tripped first. Counting
  is fixed; a failed search is now rendered to the reply as evidence saying
  so, so it admits it could not check instead of promising to. **Operator
  decision:** wait for the cycle to reset, raise the plan or pay-go, or enable
  Google grounding. Since then: `search_credits` on the internet server lets
  the operator ask the meter in chat and schedule "message me if credits are
  below N" - the firing stays quiet until it is true; and with the pool spent, every
  turn now knows it before routing and opens with a friendly "search
  allowance used up" line instead of a search that fails. Later the same
  evening Brave Search became the first rung (900 requests a month, local
  hard stop under the $5 free credit; the operator also set the dashboard's
  monthly usage limit to the free credit), so live search is back. Google grounding (`GOOGLE_SEARCH_ENABLED`, off because the key's tier
  returned 429). Until then every live question is answered from training.

Measured on the live router 2026-08-26, with the firing rule in the prompt: "Remind
me to stretch" calls no tool 3/3, but "time to call mom" still searched 2/3 -
so plain reminder firings are no longer routed at all (`_is_plain_reminder`),
and the prompt rule covers the phrasings the regex does not.

The journey sweep (`sweep_journeys`, 2026-08-26) passes 17/18 on its first run
after two fixes it found itself: a guest's daily search allowance was charged
per round (three questions a day) and the reply did not know the person's
place. Two observations left open: "send an email to my landlord" is answered
with an offer to draft (right) without saying plainly that email cannot be
sent; and the sweep account is a guest, so the operator-only meter journey is
not in it.

One functional case is red independently of tonight: `test_scheduled_task_behaviour.py::
test_cancelling_names_the_task_in_the_persons_words` - "cancel the weather
texts" routes to manage_tasks with operation `list`, not `cancel`, and does so
with the router prompt and the tool registry as they were at c0cea0f, so it is
the model's decision drifting rather than tonight's prompt growth (bisected by
removing each added paragraph; none restores it). Worth a look at the
manage_tasks description.

Pre-existing red in the unit suite, untouched here and worth a session of
their own: `test_search_budget.py` (8), `test_access_requests.py` (5,
`KeyError: 'request_token'`), `test_turn_measurement.py`,
`test_unattended_turn.py`, and a handful more - 21 after this work, down
from 31. The desktop `.wslconfig` item closed itself later that evening: the
PC rebooted (cause unknown to this side) with the file in place, the VM now
reports 23.47 GiB, and `IMAGE_EDIT_MEGAPIXELS` is 2.0 again on spark1 with a
measured generate (54 s) then 2 MP edit (68 s) and 7.1 GiB to spare. The
parked Remote Control session on the desktop is gone with the reboot.

## alippe welcomed by hand, and two pieces of test residue found — 2026-08-25

`alippe` (Alec) was approved on 2026-08-17, before sign-up collected a number,
so the account had no phone anywhere - not on the request, not as a
subscriber, not on the Mac - and the welcome had nowhere to go. The operator
supplied the number; the same three steps approval performs were run by
hand from the backend container (enrol as a consented iMessage subscriber,
`allow_recipient` on the Mac, `send_welcome_if_new`): `granted`, `sent`,
`welcomed_at` set. He can now text the assistant as well as use the web.

`zakarya` (Zakarya) was in the same position - approved 2026-08-17 with
`phone: null` on the request, active on the web, never welcomed. The
operator supplied his number the same day and the same three steps were
run from the backend container: enrolled (active, deliverable), `granted`
on the Mac, `sent`, `welcomed_at` set at 17:34 UTC. Two accounts predating
phone sign-up are now reachable; any others will show as `welcomed_at`
null with no subscriber row.

Found while looking, **not cleaned up - the operator's call, since both are
deletions in production**: eight orphan `discovery_subscribers` rows for
`del_*` / `api_del_*` users on a fake `...0100` number (2026-08-08 and
08-12) - structural tests that ran against the live database through the
gate and did not clean up; and two fake numbers (`...0000`, `...0143`, the
README's examples) granted on the Mac's allowlist by test approvals. Neither
harms anything today; both are sloppy, and the first says the gate's test
container should be pointed at a scratch database before any test that
writes is run through it again.

## The desktop's memory ceiling, measured for the second time — 14:02 UTC

The operator received "the image generation backend stopped partway through
this request" over iMessage for a plain *generation*. spark1's log: six
generations submitted between 13:56 and 14:02 (the operator testing after
the seventh scenario pass), the sixth failing at 14:02:38 with "Server
disconnected"; the desktop: `RestartCount 1` at 14:02:39, `ExitCode 0`,
`OOMKilled false`, no error in the log, and a fresh process with nothing
resident afterwards. Encoder 8.07 GB + Klein 7.33 GB = 15.40 GB against the
WSL2 VM's 15.57 GB, with 14.35 GB already pinned - **a generation alone
crosses the line** when the encoder is evicted while Klein loads. Moving
edits to Klein removed the second model but not the pair already at the
limit, and `IMAGE_EDIT_MEGAPIXELS=1.0` was the right answer to the wrong
question. **The fix is on the desktop and is written but not yet in
effect:** `C:\Users\Ani Mallya\.wslconfig` with `memory=24GB` and
`swap=8GB` needs `wsl --shutdown` and a Docker Desktop restart - the
operator's call. **Until then generations die intermittently**, and the
provider now covers the common case: when ComfyUI drops a job it had
accepted, the provider waits for `/system_stats` to answer again (up to
`IMAGE_PROVIDER_RESTART_WAIT_SECONDS`, 90) and resubmits exactly once - a
job it rejected or one that timed out is never retried, and a second
failure reports as before. Structural tests pin both directions; the seven
scenarios then passed 7 of 7 on the deployed build with no resubmission
needed (ComfyUI stayed up for that run - the retry is insurance until the
VM restart, not a substitute for it).

## iMessage pictures — defect found and fixed, 2026-08-25

The operator asked for a picture over iMessage and received "here's the
image you asked for" with no image. The log trail: text bubble sent
04:09:16, the attachment send at 04:13:26 failed with
`MCPInvocationError: argument_withheld`. Reproduced in the worker container
by screening the exact argument shapes: `attachment_name`, media type, and
base64 all pass; `body: ""` returns `allowed=False, categories=['empty']`.
The egress policy's "empty means nothing to search" verdict was being
applied to a tool argument where empty is legitimate - every
attachment-only send. Fixed in `_screen_arguments` (an empty string
discloses nothing), pinned by `test_an_empty_string_argument_is_not_withheld`,
images rebuilt and redeployed, and proven by sending a labelled test picture
through `_invoke_discovery_tool` - the worker's own path - to the operator's
phone (message GUID returned, `is_error=False`). The text-before-image
ordering means a failed attachment still leaves a misleading sentence; the
bubble pacing and the reply pinning are unchanged.

## ML system design — the document that must move with every serving change

`docs/ML_SYSTEM_DESIGN.md` (and `docs/diagrams/ml-serving-design.mmd`) now
carries the serving decisions with their measurements and the tried-and-
rejected ledger, and the published architecture page renders it as its own
section. AGENTS.md's ownership rule: update it in the same change as any
serving flag, quantisation, model, cache, context, threshold, or token
budget; a decision whose evidence lives only in a commit message is not
documented. Three documentation drifts it surfaced, still to reconcile in
their owners: `ds4-tp2.sh`'s header asserts 0.83, 0.90, and 0.78 in three
places while the exec block runs 0.81 (the README already says to trust the
flags); `vlm-serve.sh`'s header says "2 GiB" for a 3 GiB KV cap; and
`docker-compose.yml`'s reranker comment says `/v1/rerank` where the code
speaks `/v2`.

## Backup alerting — LIVE 2026-08-25

`ALERT_BRIDGE_URL`, `ALERT_BRIDGE_TOKEN` (taken from spark1's own
`MCP_SERVERS_JSON`, never moved off the box), and `OPERATOR_ALERT_PHONE` (the
admin account's own approved subscription) are set in spark1's `.env`. A
labelled test page went through `scripts/notify-operator.sh` to the
operator's phone ("alert sent"). The four units are installed in
`/etc/systemd/system`: the nightly backup now carries
`OnFailure=anios-backup-failed.service`, and `anios-backup-freshness.timer`
(Mondays 09:00, `Persistent=true`) runs `scripts/check-backup-freshness.sh` -
every copy must hold a dump newer than 36 h, an unreachable mirror counts as
stale, and it pages on its own. The freshness service was run once under
systemd and finished `Result=success`; the failure unit lints clean. The
failure path was deliberately not fired end to end, because its only output
is a "backup FAILED" text to the operator - the notify script it calls is the
one already proven.

## Architecture document rewritten for newcomers, 2026-08-25

`docs/ARCHITECTURE.md` is now three parts: a newcomer's Part I (what it is,
the machines, a message's path, the models and why each is where it is,
memory in plain words, safety on one screen, and every subsystem in the
memory overview's numbered shape), Part II cataloguing every ADR and every
decision made while running the system with its reason and date, and Part
III, the prior engineering reference with its stale single-RTX-5080 topology
and role tables replaced by the Spark deployment and marked historical where
kept for measurements. Found while writing it, not yet fixed:
`docs/diagrams/authentication-subsystem.mmd` predates the phone sign-up,
approval, bridge grant, and welcome flow (2026-08-24) and still shows only the
operator-CLI invite path - a real diagram gap under the maintenance rule.
Also found and fixed the same hour: `RERANKER_BASE_URL` had reached only the
test container, so the live backend's reranker stage was off (fail-soft hid
it); it is wired into backend and local-capabilities and verified enabled.

## Direction from the operator, 2026-08-24

More MCP integrations are coming (Instagram, Google Drive, and more), and
**quality is as important as speed in scaling**. The toolbox path already
generalizes (shortlisted candidates, alias parsing, guarded invocation, the
per-server risk classification) — what each new integration needs is its own
quality gate in the house pattern: a labelled routing floor so the new tools
do not dilute selection precision, and functional coverage of the real
provider contract before it is advertised as a capability.

## Code review pass — 2026-08-24, and what it deferred

A full review of the 63 commits since the iMessage work closed a chain of
defects (commits d251338b, 26c7c303, 15c8d53b, 4b4864a3, ffc18fe0). Fixed: the
sign-up phone takeover chain (unverified/non-unique number → account takeover)
and its blast radius; the welcome service blocking the event loop and its
partial-failure handling; the image-reply path that never delivered (bridge
rejected the worker's empty-body attachment sends) and never pinned (guid
format mismatch); the Redis cursor discarding messages on a blip; the red
approval test suite; backup partial-file/CRLF/multi-host; and Postgres/Redis
bound off the LAN. Backend fixes are gate-verified only — the suite cannot run
on the Mac; **run `bash scripts/gate.sh` on spark1 before trusting them.**

Deferred, needing a box or a window, in priority order:
1. ~~Apply the committed deploy changes on the boxes~~ — done 2026-08-25.
   spark2's installed `/etc/systemd/system/anios-vlm.service` now carries
   `After=ds4-worker.service` (spark2 has no repo checkout; the unit was
   patched in place and reloaded, VLM left running). The port-binding change
   is applied on spark1 — with the compose-network fix it forced, above.
2. **Netplan for the RoCE fabric (#1, not written).** The `192.168.100/101.x`
   addresses are set by hand and do not survive a reboot, so a power cycle
   leaves both ds4 units retry-looping forever. Capture the live addresses
   (`ip -4 addr show enp1s0f1np1` on each node) into a netplan file and apply
   during a window — applying netplan can drop the network, so not done blind.
3. **Backup failure alerting (#3, not written).** Nothing signals a failed or
   silently-stalled backup. Wants an `OnFailure=` unit that notifies through
   the iMessage bridge plus a weekly "is there a dump newer than 36h on the
   mirror" check — not shipped blind because it needs the bridge token/recipient
   wired and tested on the box.
4. ~~Keyed phone/address digest (C12)~~ — done 2026-08-25, see the
   hardening wave above and SECURITY.md.
5. ~~Memory export phone; `.env.example` desktop paths~~ — both done
   2026-08-25.

**The architecture study-guide source is missing.** The prior handoff said a
100,501-character, 65-decision draft existed at `scratchpad/study_guide.md`,
but that path is absent and was never tracked by Git. Recover the draft from
the session or machine that produced it before attempting publication. The
existing `docs/architecture.html` is the generated canonical-diagram page and
must not be overwritten based on the stale premise.

**Point-in-time recovery does not exist.** `archive_mode=off`,
`wal_level=replica`, nightly dumps — so a failure at 03:29 loses the day. WAL
archiving is the fix if that window is ever too wide.

## Operational traps that cost real time

Every one of these cost hours or data, and none are discoverable from the code.

**A comment inside a backslash-continued shell command deletes every argument
after it.** This silently dropped seven vLLM flags and caused a two-hour
outage. `deploy/spark/ds4-tp2.sh` now keeps all commentary in the header and
none inside the exec block.

**`--kv-cache-memory-bytes` is a hard cap that does not scale with
utilization.** It survived in the repo copy after being removed elsewhere and
pinned the KV cache at exactly 5 GiB through four restarts. Banned; do not
reintroduce it.

**spark2 bounds `--gpu-memory-utilization`, not spark1.** spark2 also hosts the
VLM and has roughly 15 GB less headroom. 0.90 is refused there; 0.81 is the
settled value.

**Over-allocating GPU memory hangs the box.** No BMC, no wake-on-LAN: recovery
is a physical button press.

**Binding a published port to the host's loopback silently cuts off every
container that dials the host's LAN address.** Applied 2026-08-25 to
db/redis: services hardcoding `POSTGRES_HOST=spark1.local` kept
their established connections and refused all new ones - health answered 200
throughout, the failure lived only in the logs. Container-to-container
traffic must use compose service names (`db`, `redis`); anything that
regresses to host addressing will break again exactly this quietly.

**Redis 7 starts empty if `appendonly yes` is set with no AOF file on disk.**
It ignores the RDB. Enabling AOF must be done live with `CONFIG SET` first, so
the AOF is written from memory, and only then recreated. Getting this backwards
loses the iMessage cursor.

**The gateway and the backend are one-shot builds.** The gateway is a static
bundle and the backend bakes migrations into the image. A frontend change needs
a gateway rebuild and redeploy — Vite HMR proves nothing — and a new migration
needs a backend rebuild before `alembic upgrade head` can even see it. Both of
these were hit on 2026-08-24: a phone field that was "done" but invisible, and
a migration that reported success while doing nothing.

**`docker compose` service names are not what you would guess.** It is
`backend`, not `api`. The functional-test image is separate (`target: test`)
and a `docker compose build backend` does not rebuild it.

**Long bash heredocs fail to parse on the Windows host.** Use Write/Edit for
anything substantial; a doubled or very long heredoc silently runs nothing.

**Never run destructive DDL against `anios_db`.** It holds real user data.
Restores go into a scratch database, never over the live one.

## Conventions worth knowing before changing anything

- **Commit directly to `main`.** No feature branches, no PRs unless asked.
- **Intent and meaning are decided by models, never by regex.** Routing,
  classification, and "what did they mean" go through tool-calling.
- **Every new function gets a comment saying why it exists**, not what it does.
- **A change that adds or alters a prompt is not complete** until a functional
  test in `backend/tests/functional/` exercises it against the real runtime and
  asserts on what came back. Structural tests prove the call happened; they
  cannot tell you the answer got worse.
- **Prompts live in `prompts/`** — 39 files, catalogued in
  [prompts/README.md](../prompts/README.md). Two exceptions are still Python
  constants and are listed there under "Still in Python":
  `backend/agents/graph.py` and `backend/services/main_action_selector.py`.
- **Do not modify `bridges/imessage_mac`** except from the Mac session.
