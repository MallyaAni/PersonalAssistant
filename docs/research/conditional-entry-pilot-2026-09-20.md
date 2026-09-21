# Conditional entry timing pilot — registered before training

User objective: entries during the session for positions held several days to
a few weeks. This first bounded experiment fixes the holding horizon at five
sessions. It asks whether to enter, wait one hour, or leave the allocation in
cash. It does not refit the production desk or change any account.

Starting source: 09ee4a06fc04096e619ee5a6df25bb2a813e82f2, main, one existing
local commit ahead of origin/main; pre-existing untracked routing evaluations
are unrelated. Research source files and input arrays will be hashed.

VERIFIED before implementation: RTX 5080 available through PyTorch
2.14.0+cu130; 130 existing focused tests passed. Local daily panel spans
2015-01-02 through 2026-09-04. Historical universe is today's 94 thematic
names, plus SPY. FAILED acceptance properties in existing production code:
combined rotation and entry can exceed the name cap; the board and nightly
planner disagree on zero-target entries. Those defects are separate work.
UNVERIFIED: profitability, untouched out-of-sample performance, broker fills,
and superiority to the adopted desk.

## Fixed experiment

- Decision times: after the 10:15–10:30 and 11:15–11:30 New York bars.
- Immediate entry: open of the bar starting 15 minutes after the decision.
  Waiting entry: one hour later than that immediate entry. Both have the
  same exit at the daily close five trading sessions after the decision day.
- Candidate selection: the five strongest positive 20-session momentum names
  with available causal features at each decision. Selection is fixed across
  every policy. This is a price-only timing pilot, not a replay of the desk's
  A-grade selection. No model may win by selecting a different stock basket.
- Action set: enter, wait, skip. A second evaluation forces enter/wait only,
  isolating timing from the decision to carry cash.
- Labels: gross log return of immediate entry, and the incremental log return
  from waiting instead. The latter directly measures the value of waiting.
  Features use prior daily bars and current intraday bars already closed.
- Features: eight compact price/context inputs as an ablation; a wider block
  of daily trend, band/level distances, volatility, market/theme context,
  intraday shape, time-normalized volume and time of day; a sequence of the
  observed intraday bars for the small GRU. No future daily high/low/close,
  no reconstructed historical release-tone or unversioned fundamentals.
- Train through 2023; select neural checkpoint on 2024; report 2025–2026 as
  previously examined retrospective evaluation. Purge by label exit date.
  Never describe those years as an untouched holdout.
- Models: ridge; histogram gradient boosting on basic and full features;
  small GRU plus full static features, seeds 0 and 1, twelve epochs maximum,
  checkpoints at epochs 4, 8, 12, selected on validation funded NAV at 10 bp.
  No test-driven parameter changes, seed selection, or threshold sweep.
- Controls: enter every candidate, wait every candidate, and cash. Allocation
  uses equal fixed cohort budgets across policies. A skipped slot stays cash.
  Five-day overlapping cohorts share one fully funded cash ledger; holdings
  drift, cash cannot go negative, costs apply at entry and exit, and all
  positions are liquidated by the evaluation endpoint.
- Costs: 10 and 30 bp per side. IEX bar opens approximate executable prices;
  they do not establish consolidated quotes, queue priority, impact or fills.
- Metrics: net return, daily arithmetic Sharpe (zero cash yield explicitly),
  drawdown including initial capital, exposure, turnover, enter/wait/skip
  counts, and paired session-block bootstrap intervals against immediate
  entry. Report forced-investment timing separately from skip-enabled policy.
- Missing historical execution prices leave the candidate's slot unfilled in
  cash, with an explicit count. A missing held-asset price invalidates NAV;
  never remove a selected candidate because its future return is missing.
  Feature eligibility uses information available at the decision only.
- Artifacts: frozen dataset, candidate flags, dates, source/data hashes,
  model files, validation scores, test predictions, decisions and NAV paths.
  Reloaded models must reproduce predictions and account paths.

The acceptance test is an executed, reproducible research result on the GPU,
not a profitable result. Promotion requires a separate untouched forward
record and a repaired production-policy replay. No RL training in this first
stage: isolate learnable conditional rewards before adding sequential control.

## Why this differs from earlier negative results

Cross-sectional rank prediction, a top-ten monthly portfolio, a Sharpe-shaped
allocation reward, and a strategy forced flat every evening each answer a
different question. They remain useful controls; none rules out a conditional
entry model for multi-day holdings. Features are judged through ablations on
the same action problem, not through a larger network on a different task.

## Results

VERIFIED: the amended run trained ridge, basic/full histogram boosting and a
two-seed GRU on the desktop RTX 5080. 129,823 causal setup observations;
63,811 labelled training rows; 23,478 validation rows. The 2024 validation
account selected neural epoch 8 of 12 (epochs 4/8/12 returned
100.119%/103.243%/82.595%, biased retrospective simulations). The common
retrospective test spans 2025-01-02 through 2026-09-04, 420 sessions and
4,082 selected stock/decision opportunities. These are not 4,082 independent
market realizations. GPU reload reproduced all four methods and all 66
account paths, with exact decisions and NAV tolerance 1e-10.

At 10 bp per side, forced entry-or-wait policies on identical candidate slots:

| Policy | Mean daily improvement vs immediate entry | 95% paired block interval |
|---|---:|---:|
| Fixed one-hour wait | +0.769 bp | [-0.278, +1.954] bp |
| Ridge | +0.012 bp | [-0.819, +0.799] bp |
| Trees, 8 inputs | -0.189 bp | [-0.816, +0.426] bp |
| Trees, 28 inputs | +0.234 bp | [-0.289, +0.792] bp |
| GRU + 28 inputs | +0.142 bp | [-0.570, +0.864] bp |

**No robust timing improvement demonstrated.** None excludes zero, and the
full tree's paired advantage changes sign between 2025 (+0.581 bp/day) and
2026 (-0.372 bp/day). At 30 bp per side, full trees are +0.237 bp/day
[-0.288, +0.794]; GRU is +0.146 [-0.567, +0.868]. A fixed wait also does
not demonstrate an edge. These intervals are descriptive, not corrected for
all past research trials. No new configurations were fit after these results.

The large absolute returns reflect a current-winner universe, concentrated
positive-momentum selection and approximate IEX execution. For transparency,
pooled 10-bp period returns were immediate +382.29%, fixed wait +402.25%,
full trees +388.43%, GRU +386.30%; corresponding daily-close maximum drawdowns
were -35.99%, -35.79%, -35.74%, -36.49%. These are not achievable-return
forecasts. Average exposure was approximately 80% in all four. Missing-price
unfilled opportunities numbered 6/12/9/9 respectively, remained cash, and were
not removed from the 4,082 decisions. Real consolidated execution is unverified.

Allowing skip cut exposure and return: full trees held 60.5% average exposure,
returned +192.18%, and drew down -30.66%; GRU held 52.3%, returned +154.71%,
and drew down -27.82%. This does not establish superior risk management; cash
explains part of the difference and needs exposure-matched controls before any
such claim. The forced-investment comparisons above are the timing result.

VERIFIED: 16 new causality/accounting/normalization/sequence tests; Ruff clean.
The audit also ran 130 existing focused tests. No trading policy, account,
broker, model-serving process or deployed UI was changed.

FAILED: strict CPU replay of CUDA GRU predictions at rtol/atol 1e-5. Maximum
prediction difference is 0.007436 percentage-log-return units. Ridge and both
tree forecasts match exactly. A separate diagnostic found zero changed timing
or skip decisions among the 4,082 selected test opportunities, but this does
not turn a failed numerical tolerance into a pass. Use the pinned CUDA replay;
the numerical cause and general cross-device portability are UNVERIFIED.

Artifacts: `E:/AgentWorkspace/entry-timing-pilot-20260920/run-02/`, including
manifest, dataset, preprocessing, four methods' weights, frozen predictions,
validation, summary, all 66 paths, and CPU diagnostic. Source revision is the
starting HEAD plus the two new modules fingerprinted in the manifest:

- `market_entry_pilot.py`: `76ebc6578ac07993eaf649ac90472cd63c2a01c54dbb9c60bd8c2f2fe782fcea`
- `entry_pilot.py`: `505bafeb3106169bfaf1a1885f142cf00f70785e57da876ec0fa018b874342f6`
- Frozen dataset: `f519461e784c2b48be4b8cd5438ca54d34400e132e5b55f2758e23d9abf42597`

```powershell
.venv/Scripts/python.exe -B -m backend.cli.market_entry_pilot --device cuda --output E:/AgentWorkspace/entry-timing-pilot-20260920/run-02 --verify
```

The next independent experiment should compare event-conditioned opportunities
(breakouts, retests and thesis-preserving pullbacks), with the setup definition
and holding/exit alternatives frozen before training. The current test samples
positive-momentum names at two fixed times, not the full set of the operator's
level-specific decisions. Add as-of fundamental/event evidence only after its
data boundary is verified. Position-sizing and sequential exit/RL experiments
remain separate, unperformed work; none is dismissed by this result.

Diagram impact: NONE — the pilot is an internal experiment using the existing
market-store-to-isolated-research-artifacts path; no live component or boundary
was added. No verified Git checkpoint or production deployment is claimed.

### Data preflight amendment, before any fit

Run-01 stopped before training: 89 of 6,592 candidate decisions in 2024–2026
had at least one missing execution bar (65 immediate, 64 waiting), including
13:00 decisions on scheduled half days. No model result was examined. Both
decisions now occur in the morning, so the latest possible fill is 12:45,
before a 13:00 early close. Execution requires an observed price at that time;
without one the order is not placed and its allocation stays cash. Missing
held marks still invalidate NAV. This is a revised execution contract, not
evidence that a missing vendor print would prevent a real broker fill.
Run-01's dataset is preserved; the amended protocol runs in a new directory.
