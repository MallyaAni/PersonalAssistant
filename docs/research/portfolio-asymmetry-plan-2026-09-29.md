# Portfolio downside versus upside: one predictive gate

Registered before extracting labels or fitting these models. This is the third,
lower-confidence priority, not permission to change `/4` or the frozen laggard
shadow. It does not rescue a failed partial-laggard test by retuning its weights.

## Question and distinction

Earlier volatility sizing and single-stock drawdown trims sacrificed upside.
Ask whether daily information can distinguish the **whole funded portfolio's
next five-session losses from its gains**, not merely predict large moves of
either sign. No neural-network or RL sweep follows an uninformative target.

Use the existing registered cache and the unchanged `/4` account at 25 bp,
offset 10, from the partial-laggard run. Its journal must first independently
reconcile. Both the account and all history are development evidence: hundreds
of previous trials and retrospectively assembled source snapshots rule out any
claim of an untouched test set. The other 19 offsets are not independent
training observations and will not be pooled to inflate sample size.

## Frozen construction

One row per decision close with at least 200 preceding sessions. Five-session
net funded return is `NAV[t+5]/NAV[t]-1`. Its positive and negative parts are
`max(return,0)` and `max(-return,0)`. The model predicts both magnitudes; their
difference is the net-return forecast. Labels include the baseline's actual
subsequent decisions and costs, not a frozen buy-and-hold basket. Missing tail
labels remain visible and unscored. Do not winsorize labels or remove crashes.

At close t use only prices/marks/grades through t. Sixteen features:

- SPY and QQQ trailing 5/20/60-session simple returns (six).
- SPY trailing 20-session annualized volatility and distance from its 200-close
  moving average (two).
- `/4` trailing 5/20-session funded returns, 20-session downside and upside
  realized second moments, and current drawdown from its trailing 60-close peak
  (five).
- Current closing stock exposure, sum of squared stock weights, and share of
  currently eligible members graded A/A+ (three).

The realized second moments are the mean of squared negative/positive daily
returns, including zero for the opposite sign; they are not conditional means
over only falling/rising days. Weights come from the reconciled journal, not
ideal allocator targets. Cash is excluded from the concentration sum. No new
market-data request, macro revision, private account or model-server call.

## Models and chronological validation

Annual expanding fits, scored 2019–2026. Every training label must end strictly
before January 1 of the scoring year. For tree-count selection, the preceding
calendar year is validation; inner training labels end strictly before that
year begins, and validation labels end before the scoring year begins.

Comparators: expanding historical mean of both magnitudes; fixed Ridge with
alpha 10; LightGBM with two regression heads, each seven leaves, depth 3,
minimum 100 rows/leaf, learning rate 0.03, L2 10, feature/bagging fractions 1,
seed 7 and two threads. At most 300 trees/head; early stopping after 30 rounds
on validation head MSE, then refit to all eligible history with that tree count.
No grid. Minimum fit 504 rows, validation 126. Each head's forecast is clipped
at zero, never the observed labels. Training-only median/IQR normalization,
0.5th/99.5th percentile feature clipping and missing indicators reuse the existing
tested financial-study transform. No random k-folds across dates.

Archive every input, target endpoint, prediction, fitted scaler/model and tree
count. Exercise real fits, model reload, exact feature/label arithmetic and
future-data tampering before trusting output. This is a small CPU job; it does
not need the desktop GPU or interfere with serving models.

## Fixed advancement screen and stop

On common scored dates report head MSE, net-return MSE/MAE, every year, and the
two windows 2019–2023 / 2024–2026 separately. Use chronological rows, not
restarted annual portfolios. Point forecasts are not a distribution forecast or
a calibrated probability that tomorrow will be red.

Advance LightGBM to a *separately registered execution test* only if:

- at least 500 scored dates in 2019–2023;
- net-return MSE improves at least 2% over both the mean and Ridge there;
- net-return MAE does not worsen versus either;
- it improves net MSE over the mean in at least three early calendar years;
- the lower 95% bound of paired squared-error benefit over the mean is positive
  (63-calendar-day blocks, 2,000 draws, seed 7);
- later-window net MSE and MAE do not worsen versus either comparator.

Head accuracy alone cannot pass. No protective cash/index strategy is priced or
promoted from this predictive result; costs of exiting, re-entering and missed
rebounds need their own funded decision comparison against `/4`, SPY and QQQ.
If this screen fails, stop this model/feature/horizon combination without a
threshold, horizon, architecture or regime search.

Diagram impact: NONE — existing offline cache, model and research-journal
boundaries; no live data flow, deployment or account integration changes.

Pre-implementation correction: the referenced existing transform uses the
0.5th/99.5th percentiles, not 1st/99th. Corrected before extracting any labels
or fitting any portfolio-asymmetry model; the helper itself is unchanged.
