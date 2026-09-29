# Daily ML actions: implemented, trained, evaluated — do not promote

The registered experiment is complete. Both candidates are **DO_NOT_PROMOTE**.
They produced real daily target positions and funded trades, but neither beat
the unchanged `/4` account or its matched daily-cadence control. This is not a
live strategy upgrade. No model, dashboard, broker account or service was deployed.

Protocol: [daily-actions-plan-2026-09-29.md](daily-actions-plan-2026-09-29.md),
committed `07bdeec` before fitting. Actual run source:
`3b89edc7babc4219cfc1f98d026b65b766b81ac0`, a clean detached Spark worktree.
No thresholds, features or search settings were changed after seeing results.

## Measured results

Eight outer annual blocks, 2019–September 28, 2026; four starting offsets;
10/25 bp per traded side; eight accounts per offset/cost: **64 funded accounts**.
Capital and holdings carry continuously across model refits. The table reports
medians across four offsets at **25 bp per side**, not a selected best start.
CAGR is annualized net of modeled trading costs; drawdown is measured from the
starting NAV and subsequent account peaks. No terminal liquidation or cash yield.

| Account | CAGR | Maximum drawdown |
| --- | ---: | ---: |
| Existing `/4`, 20-session cadence | 30.61% | −45.03% |
| Unlearned `/4`, daily cadence | 27.28% | −46.87% |
| Daily momentum forecast control | 13.63% | −45.64% |
| Daily past-only mean forecast | 27.28% | −46.87% |
| Daily ridge forecast | 26.55% | −46.83% |
| Daily boosted-tree forecast | 25.66% | −47.23% |
| SPY buy and hold | 16.88% | −33.72% |
| QQQ buy and hold | 22.62% | −35.12% |

Both models beat each `/4` control at **0 of 4 offsets** at 25 bp. The
lower-cost comparisons also favored both controls at every offset. Relative
to original `/4`, ridge lost 4.06 annualized percentage points at the median,
tree 4.95. Relative to daily `/4`, the gaps were −0.74 and −1.62 points.
Thus changing cadence cost return before asking whether ML added value.

Offset-zero paired daily excess at 25 bp (Newey–West lag 20):

| Candidate vs control | Excess bp/session | HAC t | Excess bp/session, 2024+ |
| --- | ---: | ---: | ---: |
| Ridge vs original `/4` | −2.218 | −2.059 | −4.910 |
| Ridge vs daily `/4` | −0.327 | −1.031 | −0.168 |
| Tree vs original `/4` | −2.571 | −2.608 | −5.082 |
| Tree vs daily `/4` | −0.680 | −2.184 | −0.339 |

Forecast MSE over **11,769 mature outer observations** was 0.00374522 for
the past-only mean, 0.00375085 for ridge and 0.00381594 for trees. Skill against
the mean was **−0.15%** and **−1.89%**, respectively. More elaborate forecasts
did not improve this registered error metric or funded returns. This is a
negative result for these features, horizon and policy mapping, not proof
that every ML/DL/RL strategy must fail. Do not extend the grid to rescue it.

## Regimes and actions actually exercised

All annual blocks and causal regime tables are retained in `summary.json`.
Regimes use the prior decision's SPY close relative to its trailing200 mean
and prior trailing20 volatility, annualized, above/below 25%. These are not
shuffled cross-validation folds or predictions of the next session's color.

At offset zero/25 bp, conditional mean net returns in bp per session:

| Prior SPY state | Sessions | Original `/4` | Daily `/4` | Ridge | Tree |
| --- | ---: | ---: | ---: | ---: | ---: |
| Above200, low volatility | 1,559 | 11.38 | 9.04 | 8.72 | 8.70 |
| Above200, high volatility | 25 | 11.50 | 5.07 | −0.70 | 5.31 |
| Below200, low volatility | 178 | 26.38 | 26.47 | 26.34 | 25.03 |
| Below200, high volatility | 182 | 22.08 | 22.71 | 22.85 | 19.69 |

These discontinuous slices are not separately executable accounts or CAGRs;
the 25-session cell is especially weak evidence. A below200 state includes
subsequent rebound days. Neither model demonstrated reliable red-day avoidance.

The models were not merely scored without execution. At offset zero/25 bp,
ridge executed 426 new buys, 2,669 adds, 1,418 trims and 414 full sells;
trees executed 453 buys, 2,251 adds, 1,206 trims and 441 sells. These counts
include the inherited eligibility and event rules, not just changes attributable
to ML. The unchanged green-open rule cancelled 2,244 ridge reduction intents
and 1,985 tree intents. Cancelled sells are not executed sells or model Hold.
The 0.5%-NAV minimum trade can retain small residual holdings.

Average closing cash was 11.93% for original `/4`, 11.83% daily `/4`, 13.77%
ridge and 13.85% trees. Gross turnover, summed traded notional/prior NAV,
was 109.35x, 158.80x, 176.84x and 181.14x across the complete account period;
these are not annualized or one-half-turnover measures. Ordinary model
decisions had no missing forecasts in the observed execution coverage.

## Verification and artifact receipt

- **VERIFIED implementation:** 297 focused tests on the run's code; final
  test/wording-only follow-up: **299 passed**, Ruff and whitespace checks clean.
  Includes real synthetic ridge/tree fitting, saved-model reload, future-data
  tampering, both `/4` execution parity controls, funding, gaps, cancellations,
  residuals and journal replay. Full-repository gate not run; no merge/deploy.
- **VERIFIED actual run:** CLI completed successfully. All 64 accounts were
  independently reconstructed by the existing journal replayer before output;
  archived bytes were read back. A separate read-only audit reopened six
  offset-zero/10-bp archives and recomputed all 1,945 marks, returns, CAGR,
  drawdown, fees and fill/cancellation counts. Cash deviations below 5e−16
  were floating-point roundoff, not economic borrowing.
- **VERIFIED actual training evidence:** independent reconstruction of all
  231,044 finite panel labels and endpoint dates; eight chronological fit,
  validation and refit boundaries; 16 saved models and hashes; 48 reloaded
  prediction samples; all eight ridge scalers' past-only means. Each forecast
  family has 11,835 eligible outer predictions, including 66 newest observations
  whose labels are not mature. Their missing futures did not remove input rows.
- **UNVERIFIED historical completeness/generalization:** 15 dated constituents
  are missing from today's panel: ANSS, BRCM, CA, CDAY, CTXS, DAY, ENPH, JNPR,
  LLTC, MXIM, PAYC, QRVO, RHT, SEDG, XLNX. Reconstructed historical grades and
  revised adjusted prices do not establish original historical availability.
  The reused 2016–2026 history is not a pristine untouched final test. The
  synthetic adjusted-unit ledger is not broker whole-share/settlement parity.
  Taxes, variable market impact and a remunerated cash alternative are absent.

Spark artifacts (outside Git and the live market store):
`/home/animallya96/scratch/daily-actions-3b89edc-20260929`.
Log: same path with `.log`. Model files are under `training/models`, with
per-fold receipts, predictions, original input arrays, 64 journals, eight
curve files and complete account/year/regime/action summaries.

SHA256 receipts:

```text
summary.json
fa87c487a16bfa10584bded00f263047c700b4f0b12e5dadcd6e1181bd92b17d
inputs.npz
9ade6453b7e1700b89a6cf90b2e693dcb18749acdafc38e324242ec77da9b063
training/training_receipts.json
3764aaf64dd49068c67f7c97103ca76f7843e56258c44d8bede8722a4adaba66
training/predictions.npz
abda37a49663a0b22419db3aba7df1ade915f14173eb242fbab55fd2e070a1e4
```

The post-run code follow-up only clarifies diagnostics and adds fee/gap tests.
The archived `learned_desired` key means **forecast-covered desired actions**,
including supplied control forecasts; it is not attribution of trades to ML.
New output calls this `forecast_covered_desired`. Financial calculations,
models, strategy behavior and the immutable run artifacts are unchanged.

## Decision

Keep these candidates off main and live execution. The working daily research
implementation is complete; a profitable live ML upgrade is **not** achieved.
Do not add DL/RL or increase epochs merely to replace this failed result with
another search. A further strategy question needs a distinct, economically
motivated information source or hypothesis and a new pre-registration, not
post-hoc retuning of this candidate. None of these results certifies the
incumbent's advertised historical return as future achievable performance.

Diagram impact: NONE — the existing offline research/model/account/journal
boundaries in the market-data and system diagrams remain unchanged.
