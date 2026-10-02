# Fixed pretrained forecast scorecard

Registered before this evaluator reads forecast outcomes, 2026-10-01.
This extends the frozen common protocol `f133cd88`; no model, threshold,
cohort, horizon, cadence or seed is selected from results.

Fixed source: `forecasts-v2.json`, SHA256
`e880fad45d38a1d52880f3aae54b7a306b49a7372661d58cd777553d424e6e13`.
Fixed cohort: AAPL, MSFT, NVDA, AVGO, AMD, AMZN, META, GOOGL, TSLA, AAOI,
SPY and QQQ. Nineteen completed-close decisions, 2026-09-03 through
2026-09-30; forecast horizon ten sessions, context 252 completed sessions.

At decision offsets 0 and 10, choose at most four dated eligible book names
with strictly positive predicted return relative to separately forecast SPY,
ordered by predicted excess descending and ticker ascending. Each receives
25%; unused capacity remains cash. Hold between resets. Eligibility means
the supplied dated membership mask; SPY/QQQ are not ranked book members.
A missing, unavailable or model-error required basket/SPY forecast makes that
model's entire reset basket unavailable/cash; failures remain in the table.
Absent records, duplicates, mismatched hashes/context/horizons/units or
checkpoint/code provenance are hard refusals, not inferred cash signals.

All funded accounts start NAV 1, next adjusted open, zero cash yield,
10/25 bp added costs, no leverage and no same-batch sale financing, through
the existing `allocation_replay` ledger. Controls share the same ten-session
phase: all-eligible capped equal weight, SPY, QQQ, and `/5` A/A+ grade targets.
The `/5` control has changed cadence and omits intraday/event behavior;
it is not an exact live strategy reconstruction.

Terminal adjusted-close error relative to SPY is separate from executable
funded return. Mature ten-session labels are scored; immature/missing labels
remain counted. TTM is risk-only: mean squared log return against the
trailing 20-session squared-log-return mean, with prediction MSE separately
reported. No TTM ranker or risk-derived sizing is invented.

Primary short-window outcomes: total return, positive-loss maximum drawdown,
fees, actual funded turnover and exposure. Annualized CAGR/Sharpe are
descriptive only. A 252-session rolling win rate and 2016–20/2021–26 split
are unavailable in this slice. No OOS, live tradability, superiority or
adoption claims: current-vintage reconstructed inputs, unknown pretraining
membership/cutoffs and later implementation vintages remain explicit.

No production, provider, broker or model-service writes.

## Engineering acceptance

Fifteen owned synthetic cases and three unchanged independent review cases
passed together on the isolated Spark CPU runtime (18 passed, no skips or
failures, 3.15 seconds). Checks exercise the actual funded ledger through
opening gaps, delayed sale funding and future-prefix invariance. They pin
deterministic ranking, full/immature opportunity counts, missing/duplicate
records, checkpoint/context/horizon/source/seed bindings, distinct risk units,
the exact final-close publication cutoff, and refusal to overwrite an input
or previous outcome. Ruff and source hash comparisons pass for all three
owned Python files. No model services or production files are changed.

The first actual CLI invocation stopped in input validation before computing
labels or account outcomes: the original 96-symbol portfolio snapshot does
not include TSLA, although the fixed forecast cohort does. The parent verified
that the original frozen membership history has no TSLA interval and no TSLA
grade records. An additive cohort snapshot carries its adjusted forecast
source prices, unknown grade (-1) and explicitly false dated membership;
known cohort grades/membership are copied from the original snapshot. This
preserves the declared cohort, all forecast opportunities and original files.
No stock, window, threshold or result is selected from economic outcomes.

## Fixed numerical result

The full four-model scorecard ran once after the additive cohort preflight
passed. Common interval: 2026-09-03 through 2026-09-30, 19 closing NAV
observations and 18 daily return intervals. Reset decisions: September 3 and
September 18. The final September 30 decision has no next-open outcome in
the frozen source and is explicitly retained without an execution claim.

| Fixed account | Net total return, 10 bp | Net total return, 25 bp | Maximum drawdown, 10 bp | Mean exposure, 10 bp |
|---|---:|---:|---:|---:|
| Chronos-2 | +0.612% | +0.462% | 2.038% | 34.28% |
| Kronos-small | −3.385% | −3.499% | 4.876% | 31.79% |
| TimesFM-3, non-commercial research | −0.077% | −0.153% | 2.038% | 13.10% |
| Dated membership equal weight | +3.930% | +3.594% | 3.555% | 91.65% |
| `/5` grade control, changed 10-session cadence | −2.151% | −2.189% | 2.814% | 10.36% |
| SPY | −1.068% | −1.217% | 2.423% | 94.71% |
| QQQ | +2.843% | +2.689% | 2.157% | 94.74% |

None of the three price forecast accounts beats QQQ, hence none beats both
benchmarks in this slice. At 10 bp, Chronos trails QQQ by 2.231 percentage
points, Kronos by 6.228 points and TimesFM by 2.920 points. At 25 bp, the
differences are −2.228, −6.188 and −2.842 points. The equal-weight control's
favorable result is a fixed-cohort retrospective observation, not a selected
new live policy. No account is promoted and no parameters change.

Actual funded turnover sums at 10/25 bp: Chronos 1.0037/1.0038; Kronos
0.7606/0.7606; TimesFM 0.5037/0.5038; equal weight 2.1846/2.1824; grade
control 0.2572/0.2572; SPY 0.9990/0.9975; QQQ 0.9990/0.9975. Full costs,
cash, exposure, instruction hashes, net benchmark differences and explicitly
descriptive annualizations are stored in the strict JSON artifact.

Each model retains 228 requested opportunities, 165 dated eligible book
opportunities, 108 mature labels and 120 immature labels. The error comparison
uses 75 mature eligible labels. None is missing or an inference error. Ten-session
labels overlap, so these are not 75 independent holdout observations.

TTM is not an alpha account. Its eligible mature squared-log-return prediction
MSE is `1.0476547489958385e-6`, against the trailing-20 baseline's
`1.1541290942860513e-6` (about 9.23% lower). That is a risk forecast diagnostic,
not evidence of higher trading gain. Eligible terminal SPY-relative return
MSEs are Chronos `0.010590716018541585`, Kronos `0.021672561234675227`, and
TimesFM `0.012565519770952405`; they do not decide policy adoption.

### Reproduction and bindings

The original fixed forecast JSON and model files remain unchanged. The
additive cohort NPZ/manifest live in
`/home/animallya96/scratch/open-source-cohort-20261001/`; NPZ SHA256
`fc5de14531c0f438995079d4f8aa3c117eac651c54ce1066868ed53756d760f6`.
Its producer checkpoint is `9c80a154`, verified by six export cases and
original membership-history hashes before deriving TSLA's false membership.

The output is
`/home/animallya96/scratch/open-source-inputs-20261001/forecast-scorecard.json`,
SHA256 `4dccc43f3fa216dd8ab1bef11851769daad24f63fff3f7e54d039a49e7b8e98a`.
Model file hashes stored and independently matched in that output:

- Chronos: `87e395d0b1e6453b99b7f5acf1dbda80b90537c9bff3092bf88de907a27b64de`
- Kronos: `8eaf4e51d11b6914f1135f693f97fdf691e9044ce409cf7618a2c520c28fc8f8`
- TimesFM: `f2f308583dabf3a751075079f4d01d1b99d66d66404d702aa1fba8f211fc3485`
- TTM: `b94a258c0c1fe0c663a3e360db382a56b89649000dd6126ee9603c2d924e7fb0`

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 CUDA_VISIBLE_DEVICES='' \
python -m backend.cli.market_open_source_forecast_evaluation \
  forecasts-v2.json cohort/portfolio.npz cohort/portfolio.json \
  forecast-chronos2.json forecast-kronos.json forecast-timesfm3.json \
  forecast-ttm.json --output NEW-scorecard.json
```

The CLI refuses an existing output and uses an exclusive create. It validates
frozen input and portfolio hashes, all contexts, horizons, seed and checkpoint/
implementation provenance before measuring anything. No provider fetching,
inference, training, orders or production changes occur during evaluation.

The three independent failed-before/fixed-after review cases are now included
in the committed test module; CI retains all eighteen acceptance cases without
adding a duplicate test file. No economic source or score was recomputed.
