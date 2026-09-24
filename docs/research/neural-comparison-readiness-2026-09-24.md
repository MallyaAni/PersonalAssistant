# Frozen neural versus the live rule: comparison readiness

Read-only audit on 2026-09-24. No inference, fitting, scoring, data fetching,
account writes or ledger migration was performed for this audit.

## Decision boundary

The nightly frozen neural network has not been tested against the full live
momentum/breakout policy on a common historical account. The existing nightly
`momentum20` comparator ranks twenty-session returns; it is not the dashboard's
grade-qualified breakout policy. The newer gradient-boosted ranker is a third,
different model. Its disappointing results do not settle the neural comparison.

An immediate bounded retrospective comparison is feasible after the price/share
basis audit. It must be labelled a component or reconstructed-rule study, not a
recovered history of personal Buy instructions. Waiting for prospective labels
is not a prerequisite for that explicitly limited diagnostic.

## Available evidence

| Input | Verified availability | Limitation |
|---|---|---|
| `backend/market/data/opportunity_neural_v1.npz` | Frozen 94-name order: 93 stocks plus SPY; 18 features plus 18 missing indicators; tanh network 36→32→16→1; training medians/scales; `training_source=b92ca4ff46c60ae92b4b387df460cafeb0b26287` | No price-unit declaration, dates or training-input manifest embedded in the bundle |
| Original checked-in neural report | Training 2018–23, last label 2023-12-27; selection on 2024, epoch 10; examined test 2025-01-02..2026-09-11 | Frozen model cannot supply honest out-of-sample 2016–20 or 2021–23 results: it was trained on later/overlapping observations |
| `desk/ml-forward/00000000..00000006.json` | Initialization plus six original input/forecast records, Sep15–22; 94×36 normalized inputs, marks, targets and account transitions | One initial basket, next-close execution, not the personal account; no multi-regime evidence |
| Dated desk records | 13 records, session Sep4..Sep23; 93 grades before Sep21, 94 afterward; actual `written` timestamps retained | No earlier original grade history; Sep14 record was written Sep15 14:18:21Z and cannot be used at that day's open |
| Cached bars and EDGAR frames | 15 snapshot partitions Sep5..Sep23 for bars/facts/events/tone; seven versioned-fact partitions Sep15..Sep23 | Historical rows inside a later snapshot are not proof that all those bytes were observed then |
| `research/learned-price-20260924/inputs.npz` | 2,948 dates, 2015-01-02..2026-09-23; 96 columns; OHLC, adjusted close, 16-feature HGB block, eligibility and market arrays | Not the neural's 18-feature schema; lacks volume and financial inputs needed to rebuild it; known Sep22 missing-bar defect |
| `/tmp/codex-trading-evaluation-inputs-20260921/corrected-exposure-report.pickle` and benchmark NPZ | Existing trusted cached desk-report and SPY/QQQ inputs, used by the allocation harness | Historical grades are reconstructed rule outputs; not original published grades; do not reuse old curves as newly validated performance |

The original neural input/curve artifacts are referenced by checked-in manifests
under Windows `E:/AgentWorkspace/opportunity-learning-20260914` and
`opportunity-learning-asof-20260914`. They were not found in the inspected Spark
research artifact locations. Checked-in JSON contains metrics and fingerprints,
not the daily NAV arrays needed for a new regime decomposition.

## Existing numbers, kept separate

The original frozen-path retrospective report gives neural **+63.7%**, maximum
drawdown **−49.7%**, versus momentum20 **+419.0%**, drawdown **−38.3%**, over
2025-01-02..2026-09-11 at 10 bp. Both use current thematic membership, ten-name
10% caps, twenty-session decisions and next-close accounting. These are prior
reported numbers, not a new rerun and not the live incumbent. The source report
explicitly leaves split/share units unaudited and calls the period examined.
The separately retrained versioned-fundamentals network returned +65.0%; it is
not the frozen bundle used by nightly inference.

The separately audited prospective ledger reports frozen neural **+15.84%**,
momentum20 **−0.20%**, SPY **+2.46%** at 10 bp through Sep22, following the Sep16
close fill. The earlier audit reproduced inference and accounting exactly.
Those four post-fill intervals establish neither a general winner nor a
scenario-switching model. Neither comparison substitutes for live-rule parity.

## Confirmed input-basis defect

`opportunity_learning.features` calls
`ratios(panel.close, levels_pit.trailing_levels(...))`. Its market capitalization
is price times reported shares. `trailing_levels` obtains shares directly from
`edgar._known_series`; it does not call `split_adjusted_shares`. That helper is
used by another levels path. Therefore a split-normalized price history paired
with older filed share units can distort valuation inputs before the network
sees them. The frozen path also chooses a fundamental tag over the whole saved
snapshot and retains earliest-filed values. `fundamentals_asof` fixes the
availability/revision/tag selection separately; it does not by itself prove
compatible price/share units or preserve the frozen model's input definition.

Root reproduced this through the real `features()` path in
`/tmp/test_neural_price_basis_review.py`, logged in
`/tmp/neural-price-basis-review-20260924.log`: economically identical pre-split
history represented as original $100/share versus a later 10-for-1 vintage at
$10/share, with the same dated ten reported shares and TTM revenue 400, gives
sales yield **0.4 versus 4.0**. Adjusted-return features are identical, but the
fundamental invariance assertion fails by **ln(10)** in log sales yield.
`yahoo.py` explicitly documents that its close prices are split-normalized to
the fetch date. This is a confirmed feature-generation defect, not evidence
that the recorded shadow's account arithmetic was wrong or its recent gains
were fabricated. The original training arrays remain unavailable for measuring
the exact affected historical examples here.

Resolve this with dated corporate-action and filing provenance before producing
new profitability numbers. Preregister a corrected feature variant and separate
retraining protocol if the intended candidate learns from corrected inputs.
Do not infer adjustment factors from price ratios, silently fix frozen inputs,
retrain the existing bundle, or rewrite its prospective journal. Corrected
features define a separately named candidate and comparison.

## Smallest supported implementation

1. Freeze the comparison contract and input hashes before scoring. Preserve the
   94-name neural cohort and explicit benchmark additions, source-vintage limits,
   common dates, missing observations, starting cash, costs and execution clock.
   Score only dates after the frozen model's selection period for a historical
   generalization diagnostic; 2025+ has already been examined, so it is not a
   pristine holdout. Do not fill absent historical grades with today's grades.
2. Reuse `opportunity_shadow.predict`, its stored normalizer and exact feature
   ordering for frozen-model inference. Reuse original saved inference where
   available. Reconstruct historical features only after basis validation;
   preserve frozen-path versus corrected-feature results as different studies.
3. For an isolated ranking test, `simulate.run` already accepts an allocator.
   A neural-ranked allocator can be compared with the unchanged allocator using
   the same cached report, `use_exits=False` and `simulate.LIVE_POLICY`, including
   FOMC handling and the actual funded execution rules. This is a **neural-ranked
   hybrid** retaining live grade/entry/exit gates, not the original shadow policy.
   Pin synthetic same-target parity and account funding before historical scoring.
4. For a full-policy test, retain each policy's declared decision logic and use
   a separately specified common account/execution adapter. `growth_pilot.evaluate`
   alone cannot establish live parity: it executes next-close and does not run
   the live grade-qualified breakout/account lifecycle. A common-next-open
   diagnostic is an explicit execution-policy change, not a reproduction of the
   frozen nightly ledger. Report both changes plainly.
5. Use archived actual publication times and existing Sep15–22 neural receipts
   for a short matched replay, then continue a separate prospective comparison
   on the same decision clock. Original personal holdings/cash and screen
   responses are absent, so synthetic accounts must not be called actual user
   outcomes. Do not alter the frozen ledger to add a missing comparator.
6. Report SPY, QQQ, equal weight and the unchanged incumbent with net return,
   drawdown, Sharpe, rolling wins, turnover, cash/exposure and 10/25 bp sensitivity.
   Preserve the original shadow's 10/30 bp record separately. Market regimes
   must be assigned from information available before each return; no tuning a
   selector to already observed winners. Split periods unavailable out of sample
   for this frozen model must say unavailable, not reuse training performance.

VERIFIED: source interfaces, bundle schema, cache/record coverage and prior report
definitions. UNVERIFIED: basis-correct frozen historical features, full live-rule
comparison, superiority, scenario selector and actual midpoint execution.
