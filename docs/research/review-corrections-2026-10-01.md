# Trading review corrections — verified branch checkpoint

Implementation: `33ac6c71`, branch `fix/review-consistency-20261001`, from
GitHub main `95424784`. The separate research correction is `647d289f` on
`fix/research-gross-execution-20261001`; do not merge that research branch
into live main. Neither checkpoint is a strategy-performance promotion.

## Results

| Finding | Implemented result | Remaining boundary |
| --- | --- | --- |
| Reset buys clipped to the 15% entry cap | Funded resets retain allocator targets; ordinary entry cap, cash funding, rounding and band gate remain | Execution prices can change exposure; this is not a continuously enforced holding limit |
| Historical curve claimed live execution | Curve has its own `daily-open-close/1` identity; old/unknown stamps no longer imply live parity | Current dip/pop-or-close historical execution is not implemented here |
| Gross-risk cuts lost mid-cycle | Separate research branch preserves next-open cuts/recovery and clears obsolete retries | FOMC lifecycle combination is refused, not integrated |
| Dashboard due/sent and partial/filled conflation | Independent counts and honest unsent wording; terminal actions grey in ticker panel too | A waiting BUY is still strategy intent, not a completed entry trigger |
| Missing 6-K coverage passed audit | Empty/untestable coverage fails; audit horizon includes missing trailing full years | Classifier, fiscal-quarter completeness and missing releases are not repaired |

Planner identity becomes `cash-bounded-breakout-rotation/5`; allocator stays
`graded-equal-weight/5`. The allocation stamp and intraday timing are unchanged,
so this correction does not itself trigger an unscheduled reset.

The reset counterexample is a $100,000 cash account with four 25% targets at
$100: formerly 150 shares each, $60,000 deployed and no cash-shortfall retry;
now 250 shares each. With insufficient cash, quantities are scaled down and
the unpaid portion remains explicit. Planned sells do not fund simultaneous
buys before their proceeds exist.

## Acceptance evidence

All 21 changed/new backend/frontend files matched the Spark test source by
SHA-256 before commit. Test source:
`/home/animallya96/scratch/review-fixes.7geh0o`; isolated frontend at
`127.0.0.1:5192`, not the deployed app. No live service, broker account,
stored recommendation or historical performance artifact was modified.

- **VERIFIED:** 381 backend tests passed in the network-disabled
  `anios-functional-tests` image with this source mounted read-only.
  The one torch-dependent EDGAR loader test skipped there passed separately
  in Spark's research venv: 382 relevant cases passed in total.
- **VERIFIED:** 138 Playwright tests passed: `desk-trade-board`,
  `desk-level-gate`, `desk-history-accuracy`, `simple-actions`, `chart-15m`,
  `desk`, and `fundamental-source-versions`. Covers board/detail agreement,
  paper history, reference sizes, phone layouts, reload, stale/missing data,
  simulation provenance and order state distinctions. The provenance suite
  allows only aborted conversation GETs with a successful replacement;
  desk read failures, writes, HTTP errors and runtime errors remain fatal.
- **VERIFIED:** TypeScript, Vite production build, generated paper-plan
  fixture check, whitespace checks and all 33 diagram pairs/published page.
  Diagram rendering used an isolated network-disabled container and its
  bundled browser, with no laptop or host settings changed.
- **VERIFIED:** Ruff on the new tests and changed execution/audit modules.
  The 15 remaining Ruff findings in four existing files exactly match
  base `95424784` by diagnostic code/message; no new findings remain.
  Existing build warnings concern one CSS pseudo-class and bundle size;
  synthetic invalid-price tests emit 13 NaN/invalid-arithmetic warnings.
- **UNVERIFIED:** production deployment, the full release gate, current
  intraday end-to-end simulation parity, and improved economic performance.

The broadened backend run covers reset sizing, audit/disclosure, intraday
orders, entry timing, paper planning/funding/history, live policy and missing
marks, market-daily, EDGAR/6-K/YTD, tone refresh, simulator, strategy parity,
event execution, allocation edges, board paper and single-source orders.
The separate gross branch passed 54 tests including independent accounting
reconstruction at 25/100 basis points.

## Read-only stored-data audit

The corrected CLI read `/home/animallya96/anios/data/market` through a
read-only mount with no network, horizon `2026-10-01`:

| Name | Admitted releases | Verdict |
| --- | ---: | --- |
| ARM | 12 | Completed-year counts pass |
| ASML | 18 | CHECK: 2021–2025 |
| NBIS | 0 | CHECK: no admitted releases; 53 refused |
| SIMO | 57 | CHECK: 2015, 2020, 2022, 2025 |
| TSM | 27 | CHECK: 2020 |

These are admitted filing counts, not tone-scored counts. Exit status 1 is
the intended failing-coverage result. The first observed year and current
year are treated conservatively as partial; four filings do not by themselves
prove four distinct fiscal quarters. No classifier call or rescore occurred.

## Next boundary

Review/integrate only the main-based correction branch, then use Spark's
clean deploy checkout and `scripts/deploy.sh` with its normal gates. Do not
pull/reset/stash the shared checkout or remove its untracked work. Publish
to Spark first, then to GitHub from Spark. Keep the research branch separate.

Before comparing a learned sizing/risk policy with live `/5`, implement and
verify its shared intraday execution and coordinated FOMC recovery. Preserve
the existing daily simulation as a named historical control, and version any
new corrected research run instead of overwriting a prior result. Separately
review the existing `fix/6k-classifier` work before fetching/rescoring releases.

Diagram impact: NONE — assessed full-system, trading/market-data and frontend
views; these changes do not alter components, stores, trust boundaries or
cross-component flows.
