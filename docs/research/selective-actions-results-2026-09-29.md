# Selective action advantage around /4 — historical evaluation

Status: COMPLETE. Both learned candidates **DO_NOT_PROMOTE**. No live change
or deployment; no post-result retuning.

## Result

The selective overlay did not establish an improvement over /4. Median across
the four registered 2019 start offsets, through 2026-09-28:

| Account | CAGR, 25 bp/side | Max drawdown, 25 bp/side | CAGR, 10 bp/side |
| --- | ---: | ---: | ---: |
| Unchanged /4 | 30.61% | -45.03% | 33.39% |
| Matched selective momentum | 26.27% | -42.89% | 29.75% |
| Past-only action mean | 30.51% | -46.10% | 33.32% |
| Selective ridge | 29.89% | -46.32% | 32.74% |
| Selective boosted tree | 29.78% | -45.55% | 32.61% |
| SPY buy-and-hold | 16.88% | -33.72% | 16.90% |
| QQQ buy-and-hold | 22.62% | -35.12% | 22.65% |

Each cell summarizes a complete, continuously funded account; it is not an
average of separately restarted annual simulations. Median drawdown is the
median of the four accounts' maximum drawdowns, not a guarantee of that loss
limit. /4's stronger historical return comes with materially deeper drawdowns
than either index; the ML overlay did not solve that tradeoff.

At 25 bp, ridge beat unchanged /4 at **0/4** offsets; trees at **1/4**. Median
CAGR gaps were -0.72 and -0.83 percentage points, respectively. Offset-zero
paired daily-excess HAC(20) t-statistics were -1.74 and +0.24, both below the
registered +2 floor. Recent (2024+) excess was negative for both. Both beat
the deliberately untrained momentum control at all offsets, but neither met
all its uncertainty/drawdown checks either. No floor was relaxed.

Predictive evaluation also failed: on **4,597 mature outer labels**, ridge's
MSE was 1.35% worse than the past-only action mean and trees' was 1.50% worse.
The 69 remaining outer prediction rows have no mature endpoint and were not
erased. Total teacher rows: 6,622; mature labels: 6,553.

These are genuinely different trade decisions, not an unchanged baseline
mislabelled ML. Across four 25 bp accounts, ridge selected 90 Buys, 87 Adds,
89 Trims and 5 Sells; trees selected 19/8/27/12. These are selected
interventions, not a claim that every one filled. Whole-account orders,
actual fills, linked immediate selected-symbol fills, cancellations and
subsequent lock retries remain separate in the archived evidence.

## Years and regimes

Calendar-year total returns below are from the registered **offset-zero**
account at 25 bp, not the offset median above. 2026 is year-to-date through
September 28, not an annualized forecast.

| Year | /4 | Ridge | Trees | SPY | QQQ |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2019 | 15.04% | 15.84% | 17.63% | 31.79% | 40.12% |
| 2020 | 35.41% | 31.62% | 35.16% | 18.33% | 48.41% |
| 2021 | 46.31% | 45.42% | 46.31% | 28.73% | 27.42% |
| 2022 | -33.44% | -34.92% | -33.71% | -18.18% | -32.58% |
| 2023 | 59.78% | 59.50% | 59.78% | 26.18% | 54.86% |
| 2024 | 58.24% | 59.31% | 58.24% | 24.89% | 25.58% |
| 2025 | 34.17% | 30.68% | 33.63% | 17.72% | 20.77% |
| 2026 YTD | 79.84% | 76.87% | 80.73% | 13.15% | 20.30% |

Mean daily return in basis points by causal prior-close SPY regime, also
offset zero/25 bp. These are discontinuous regime slices, not standalone
funded returns or CAGRs. High volatility means >=25% annualized over 20 sessions.

| SPY regime | Sessions | /4 | Ridge | Trees | SPY | QQQ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Above 200-session mean, high vol | 25 | 11.50 | 9.94 | 11.46 | -8.36 | 16.76 |
| Above 200-session mean, low vol | 1,559 | 11.38 | 11.11 | 11.34 | 6.28 | 8.13 |
| Below 200-session mean, high vol | 182 | 22.08 | 21.67 | 22.40 | 9.95 | 15.39 |
| Below 200-session mean, low vol | 178 | 26.38 | 24.62 | 27.23 | 13.63 | 14.12 |

The 25-session regime is too small to claim robust behavior. These are
descriptive splits of chronological outer predictions, not random regime
k-folds. Annual purged folds prevent later labels entering earlier fits;
they cannot undo prior research on the same historical period.

## What was implemented

Source `91e0946399b05c0049d7f59902a6e31078ac2e7b`, on research branch
`research/selective-actions-20260929`. Protocol preregistered at `75a04af`;
execution-floor clarifications were committed before any historical label
generation or fitting. See [the specification](selective-actions-plan-2026-09-29.md).

Unlike the rejected daily-reset experiment, this preserves /4's 20-session
reset cadence. Ridge and boosted trees estimate the difference in net portfolio
value from a feasible Buy/Add/Trim/Sell versus accepting /4's current plan.
They use 22 causal daily features and 11 account/action features, including
actual holdings, cash, holding age, target gap and proposed size. No intervention
means accept /4; it is not a promise that the underlying account will Hold.
Sizing remains a registered menu (up to +2% NAV, half-position Trim or full Sell),
not a learned unconstrained optimizer. This experiment uses ML, not DL or RL.

Exact counterfactuals resume the same simulator from pre-decision account state,
then recalculate future plans from the changed holdings and cash. Fixed-unit
reduction instructions persist until the actual reset, respect the ordinary
execution floor, and never override event ownership. Buys remain cash-funded
at the next open; ordinary sells remain next-close and may be cancelled at a
green open. One intervention at most per actual cycle, considered at ages
0/5/10/15, with a fixed predicted advantage floor of 5 bp NAV.

## Frozen run and validation

The focused offline gate passed **446 tests**, with five existing empty-window
warnings and no skips/expected failures. Ruff and whitespace checks passed.
This is not a full repository or deployed-browser gate. Tests exercise actual
synthetic fits, current-account inference, all action verbs, funding, events,
cancellations, floors, locks, reset timing, future-data tampering, no-op parity,
full-prefix versus resumed forks, and independent journal accounting.

Existing public input cache was generated at `0e1d84d`, with no new provider
requests. Cache SHA-256:
`dbe55808a0be2ea01932f5212da28cf72dffffa0fe3ea8b097727b304f8a8b91`.
It contains 95 symbols and history from 2015-01-02 through 2026-09-28.
Trusted pickle bytes are hash-checked before deserializing those same bytes.

Actual run:

- Code: `/home/animallya96/scratch/selective-actions-code.daPM9f`.
- Inputs: `/home/animallya96/scratch/selective-actions-inputs-0e1d84d-20260929`.
- Output: `/home/animallya96/scratch/selective-actions-91e0946-20260929`.
- Log: output path plus `.log`.
- CPU-only Spark research venv, two BLAS/OpenMP threads; no runtime settings changed.

Historical label generation completed: **6,622 candidate rows from 535 teacher
opportunity dates**, in 41.3 seconds for the fork loop. Labels use a 20-session
endpoint and 25 bp per-side costs; incomplete future rows remain present with
missing labels. All eight annual folds 2019–2026 fitted, using prior-year
validation, strictly matured label endpoints, and the fixed 2-ridge/6-tree
setting grid. Every learned outer account uses its own actual state, not
teacher holdings. All **56 funded outer accounts** completed and archived
their journals, and all eight cost/offset result files plus `summary.json`
were written. Every journal was reconciled during the run. The SSH client
later reported a broken connection, but the remote process completed: the
final artifacts and verdict were independently reopened, no run process
remained, and the source worktree stayed clean at `91e0946`.

`summary.json` SHA-256:
`12ac2995a832a6f092454ddf704e029a708c5ce2b20f7f27a2c01a34327bf26b`.
All 24 unchanged /4, SPY and QQQ control curves (eight configurations each)
match the previous immutable `3b89edc` study **exactly**, session by session.
This checks that the new experiment did not quietly weaken its controls.

The separate read-only artifact audit passed on the actual run: all 6,622
candidate rows, 532 mature baseline forks, 11 recorded full-prefix checks,
eight annual folds, 16 reloaded models and 48 reproduced prediction samples.
Each model has 4,666 outer prediction rows. It independently reconstructs
teacher cash/positions/NAV, entry ages and reset clocks, checks all 33 feature
columns, the two initial trade-floor tests, t+20 endpoints and label arithmetic,
and rebuilds the chronological masks/scalers/selection/mean controls. This
does not claim an independent economic execution replay of every action fork.

A separate read-only audit reproduced four saved economic paths from scratch,
without checkpoint/resume or `ForcedAction`. It chose the earliest mature
2020+ example of each action by date, not outcome: ADSK Buy and AMD Add on
2020-02-13; AMAT Trim and Sell on 2020-01-08. Full-prefix runs began in 2016
and matched baseline NAV, acted NAV and saved labels with **maximum absolute
error 0.0**. This covers four sampled paths, not all 6,622 rows or every event.

Eight additional earliest/latest selected-model reload checks at 25 bp,
ridge/trees and offsets 0/15, reproduced recorded predictions from the actual
account feature vectors with maximum absolute difference 4.34e-19.
The independent audit also checked 876 selected interventions across 14
earlier-written account artifacts; no fitting or evidence rewriting occurred.

A separate saved-account audit reopened six accounts: /4, ridge and trees
at 25 bp/offset zero; momentum, SPY and QQQ at 25 bp/offset 15. All **11,625
closing marks**, **15,490 intermediate states** and **181 selected actions**
reconciled with the saved curves, fees and actual own-account feature state.
Selected predictions reloaded correctly, and one selection per reset was
confirmed. No material overdraft or shorting: the smallest reconstructed
cash was -2.83e-16, within the pre-existing 1e-12 accounting tolerance.

Reopen label/model evidence without fitting or changing files:
`python -m backend.cli.verify_selective_actions --run <output> --trust-local-models`.
The trust flag is necessary because joblib can execute code; use only these
known, locally generated, hash-matched artifacts.

Selected-state range diagnostics at 25 bp: 30/271 ridge choices and 17/66 tree
choices lay outside at least one marginal feature range in their year's
teacher refit data. Account/action columns alone were outside for 3/271 and
0/66, and no selected action category was wholly absent from training.
Being inside marginal ranges does not establish joint-state or off-policy
coverage; these checks do not rescue the failed performance screen.

During this run, GitHub main advanced separately to `511297f` with Fable's
stage-4 timing research. Its /4 allocation, simulator, paper execution and
control-options source are unchanged from this study's base. The new raw-SIP
split-basis warning does not alter this daily-only, consistently adjusted
input path. That work was not overwritten or merged into the frozen run.

## Limits

This is reused historical development data, not a pristine final test. The
historical membership/grade reconstruction and adjusted-price revisions are
not proven original point-in-time availability. Fifteen former members lack
bars: ANSS, BRCM, CA, CDAY, CTXS, DAY, ENPH, JNPR, LLTC, MXIM, PAYC, QRVO,
RHT, SEDG and XLNX. Several modern names enter only in September 2026.
Teacher-state action values do not prove coverage of states visited by the
intervention policy. Fixed costs do not model dynamic spreads, impact or
real broker settlement, and adjusted continuous units are not whole shares.

No parameters, action menu, model grid or screening floors were changed after
the historical run began. A research pass would not authorize live deployment.

Keep the experiment isolated. Do not deploy either model, rerun this failed
grid, or choose a favorable offset as a replacement strategy. This result
rules out these tested daily features/models/action choices as an improvement
under the registered evaluation; it does not prove that ML can never help.

Diagram impact: NONE — the full-system, market-data and trading-desk views
retain the same offline model, simulator, benchmark and journal boundaries.
