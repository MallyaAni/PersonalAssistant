# Learned entry/exit timing: measured result

The stock-conditioned continuation model is implemented and its funded
comparison is independently reconciled. It does **not** establish a reliable
replacement for the live1% gate. Removing the delay without a forecast also
fails the comparison. Live trading remains unchanged.

The model predicts the benefit of executing now versus following a learned
remaining-session continuation policy, separately for buys and sells. Features
include each stock's volatility, trend, gap, completed15-minute path, range,
VWAP distance and prior grade, plus market context. Monthly Ridge models use
only matured past outcomes; whole-session crossfitting keeps continuation
labels separate from their nuisance fits. The trading decision uses the
forecast's sign, rather than a universal price-distance threshold.

## Fixed comparison

Same94-stock current-vintage universe, selection/target book, morning funding,
covered sells, first-attempt locks and terminal15:45next-open proxy for every
method. Start2018-02-01, end2026-09-30;2177sessions. Twenty carried account
phases, NAV1, zero cash yield, costs0/10/25bp per side. Fractional quantities
and hypothetical subsequent opens are research conventions, not broker fills.
The model/current-gate comparison was registered before fitting. The single
first-available control was registered after primary outcomes, before its own
outcomes; it is an exploratory interpretation check.

Full-period median account metrics at10bp:

| Method | Total gain | CAGR | Max drawdown loss | Sharpe | One-way turnover |
|---|---:|---:|---:|---:|---:|
| Learned timing |746.46%|28.05%|37.54%|1.068|58.12|
| Current1% gate |723.39%|27.64%|37.15%|1.060|58.57|
| First available |725.58%|27.68%|36.81%|1.069|57.34|
| QQQ |364.83%|19.47%|35.12%|0.865|1.00|
| SPY |209.52%|13.97%|33.72%|0.782|1.00|

These current-vintage component returns do not establish historical live-policy
performance or an investable advantage over the ETFs. In particular, this
selection book is not the current cash-bounded/6 whole-share live executor.

## Paired timing effects

Compare each phase with the **same phase** before taking the median. Subtracting
separate method medians can give a different answer, even a different sign.
Numbers below are percentage points of cumulative net gain; they are not
annual returns or execution-price improvements.

| Cost per side | Learned−current, full | Winning phases | Learned−current, recent | Winning phases | First-available−current, full | First-available−current, recent |
|---|---:|---:|---:|---:|---:|---:|
|0bp|+17.45|11/20|−0.690|5/20|−15.41|−1.254|
|10bp|+17.22|11/20|−0.689|5/20|−13.60|−1.251|
|25bp|+16.87|11/20|−0.687|5/20|−11.09|−1.248|

The recent window is2026-08-17..2026-09-30,32sessions, already reused in prior
research. It is not an untouched holdout. At10bp, learned−first-available is
+18.41points full-period,12/20phases, but only+0.040points recent,10/20.
Learned−current is−1.035points over2018–2020 and+10.832points over2021–2026.
The original score field calls the first split2016–20; actual coverage starts2018.

The learned model's median252-session rolling win rate is49.45% against the
current gate,53.79% against first-available,77.02% againstSPY and67.96% against
QQQ. Phases and rolling windows overlap; they are not independent samples.
The slight overall CAGR improvement accompanies slightly worse full-period
drawdown and inconsistent subperiod results.

## Mechanism and remaining gap

At10bp, the learned model's median attempted buy is09:45and sell10:00;
the current gate's median attempts are15:45on both sides. Common same-side
attempts have only small, uneven price improvements: equal-intent mean4.17bp
for buys and0.99bp for sells, median0and−0.437bp. This price diagnostic also
includes unfunded attempts and is not realized gain. Removing the delay alone
does not reproduce the model's full-period benefit.

Across all twenty10bp books, the model retains2203unfilled and6152partially
expired intents; current retains1958and5923; first-available307and10051.
Missing held observations and unsupported plan sessions remain explicit.
Cash constraints and carried holdings affect later plans, so execution-price
averages cannot substitute for the funded portfolio comparison.

Four regimes are defined from **prior**SPYtrend and volatility. The model's
median daily excess over the current gate at10bp is+0.324bp in down/quiet,
+0.359bp in down/volatile,−0.253bp in up/quiet and+0.115bp in up/volatile.
These are descriptive mean-return differences, not compounded regime wealth
or evidence for retrospectively switching policies. The stock universe,
allocation, regime and cost selection must not be tuned from these outcomes.

This implementation changes **when an already selected order is attempted**.
It does not decide whether a stock should remain held, change its grade, or
prove that a specificCOHRexit orAAOIentry was correct. Before a live replacement,
the same candidate needs evidence on actual current-policy intended orders,
publication-aware inputs, whole-share funding, partial fills, cancellation and
supported early closes. A new forecast family is not the immediate next step.

## Verification and artifact identity

VERIFIED:116monthly fitted numeric models,120primary carried account curves,
103342primary intent rows and90842fills, six reusedETFcurves. Independent
primary accounting verifier reconciles recorded state and metrics without
account resimulation. New first-available verifier separately reconciles60new
accounts,52434intent rows and51515fills, reusing original model/control/ETF
evidence. A supplementary byte audit confirms all116monthly saved archives
and receipts remain unchanged; it repeats no fits or model certificates.

FAILED then corrected: the independent primary verifier narrowed float32
quote products and its cash accumulator. The actual ledger is float64.
Casting the verifier's price resolves the first cash mismatch; assertion
tolerances are unchanged and original failure evidence is preserved.

Exact fitting source:b37c2b689b903f7b37e506041ed542d77af175af.
Primary evaluation source:ffa0a1578f03cdcf971b63baa59346e9d3a34a9d.
First-available source:248bf5ad9b0bbba4e6ab586b914d6dd392c4d94a.
Primary report SHA256:
`2a8276f0c5e677292a600c260e87016d39029ee33359cdfae9c228c70fe22f11`.
First-available report SHA256:
`9cac7247ffe28847a1d83ffa7a976f575a5d687115e71163102d7b06a78b15c8`.

Private original evidence remains under Spark scratch:
`sequential-execution-results-20261002-b37c2b68`,
`sequential-first-available-results-20261003` and supervision
`sequential-execution-supervision-20261002`. Source-image27new-control
acceptance cases pass. No production strategy, dashboard, orders, model
services, source histories or frozen input caches were changed.

UNVERIFIED: dependable future advantage, broker/midpoint fills, full historical
live parity and live replacement. Keep this candidate experimental; do not
replace an imperfect existing gate with an unproven model based on its best
headline. The companion JSON preserves all costs, windows, benchmark metrics,
causal regimes, rolling comparisons and missing-opportunity denominators.

Independent compact-summary SHA256:
`17ca69d030eb6158d4e4335d29d175b69b8d3194421fbd59b4e6a03c9b00fe65`.
Read [all measured metrics](sequential-execution-results-2026-10-03.json).
