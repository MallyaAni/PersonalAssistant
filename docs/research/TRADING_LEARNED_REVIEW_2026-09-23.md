# Trading desk continuation — 2026-09-23

The current live rule remains `cash-bounded-breakout-rotation/2` in deployed
source `8ce637b4`. The reviewed candidate branch includes Fables' rule
corrections and OpenCode's browser/backend first step. Those changes have not
been promoted to the live account. The learned rank and brake are named
**shadow-only** policies; they submit no orders and change no personal or paper
account.

## Verified implementation boundaries

- The full desk browser suite ran against the isolated candidate Vite source:
  **76/76 passed**. Its first run was 75/76 solely because the first navigation
  started before Vite listened; the full warm-server rerun was 76/76.
- The relevant combined backend acceptance was **414 passed** before the new
  shadow/membership modules. The shadow acceptance adds strict publication-time
  checks, a next-open to open-at-t+11 SPY-relative label, training-label purge,
  monthly refits, deterministic model hashes, a 20-session QQQ crash label,
  L2 logistic risk model, and a 0.45/0.30 hysteresis state. Synthetic tests
  include future-prefix invariance and the shared sizing/ledger path.
- The fixed trend brake and an externally supplied learned ceiling share the
  simulator's next-open accounting and FOMC minimum. The override is opt-in;
  the default path is unchanged.
- Historical research membership now fails closed when its dated source CSV is
  absent. It never substitutes today's live constituents for an earlier date.

## Adoption evidence gate

The local bar archive has **14** `asof=` vintages, earliest **2026-09-05**
and latest **2026-09-22**. It has no sourced historical membership file.
Earlier OHLC rows inside those recent snapshots are retrospective, adjusted
restatements. They cannot prove what a 2016–2026 decision saw on its day or
recreate delisted names. The existing Fables proxy also uses a different cash
convention and price-only selection. None of these sources supports an
adoption-grade learned-policy comparison under the registered protocol.

| Policy | CAGR | Max drawdown | Sharpe | Rolling QQQ win rate | Turnover | 10/25 bp cost sensitivity | 2016–20 / 2021–26 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Learned rank | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified |
| Learned blend | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified |
| Learned brake | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified |
| Incumbent, SPY, QQQ, equal weight on a common point-in-time book | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified |

The prior retrospective controls may be shown as **survivor-selected
diagnostics**, but filling this table with them would imply a like-for-like
comparison that has not happened. No training metric, single backtest or
prediction accuracy is an adoption signal. The incumbent remains recommended
until a historically sourced common universe and archived input vintages can
be evaluated, or sufficient prospective shadow outcomes mature under the
predeclared accounting and comparison protocol.

## Remaining work before adoption

1. Assemble dated listing/index/theme membership with original announcement
   dates, delisted outcomes, and reproducible sources. An after-the-fact
   change log alone is not point-in-time membership evidence.
2. Archive the daily feature values and adjusted-price/corporate-action basis
   as they were known on each decision session. Connect the existing
   filing-version and earnings-tone sources through those dated snapshots;
   the pure learning kernel accepts them but no historical adapter can be
   certified from the current store.
3. Freeze one common eligible cohort and the registered 10-session/20-session
   labels, run monthly/quarterly refits without overlapping labels, then run
   the shared funded ledger against the incumbent, SPY, QQQ and equal weight
   at 10 and 25 bp. Report missing labels and membership explicitly.
4. Start a prospective shadow with timestamped features, forecasts, intended
   weights and failures. Do not select a review date after observing returns.

## Prospective input capture added after this review

`backend.market.learned_inputs` now freezes each ordinary current nightly
record's price, range, momentum, volatility, breadth, regime, as-of filing
ratios, analyst fundamental rank and release-tone scores under
`data/market/learned_inputs/asof=DATE.json`. Each row names its bar, filing and
tone source partition; the snapshot records the desk record's byte hash,
source revision, actual capture timestamp, raw/adjusted price basis, and
whether the current bar is complete. Missing data is JSON null. The writer
refuses to overwrite a prior capture and skips historical or forced desk runs.
It does not fit a model, make a recommendation, or place an order.

A read-only build against the actual 2026-09-23 saved desk record produced 95
rows: 95 complete current bars, 89 known tone records and 82 available
earnings-yield features. This validates the adapter's real schema, not a
historical forecast. Future labels still need a mechanically reconciled price
basis across daily vintages; an old adjusted close restated by a later split
cannot be compared blindly with a new vintage. There is still no sourced
historical membership or 2016–26 point-in-time training set, so the table
above stays unverified and the learned policies remain shadow-only.

## Frozen archive-to-model bridge, pending release

`backend.market.learned_archive` now reads only nightly observations actually
captured on their decision session. It keeps missing sessions, grades and
features explicit. A stock outcome is its next-session adjusted open to the
open eleven exchange sessions after the decision, less SPY's log return on
the same endpoints. Both adjusted opens are computed from one first mature
bar partition using each bar's own adjusted-close/raw-close ratio. The
20-session QQQ crash label likewise reads one mature partition. A missing
name or endpoint in that first partition stays missing; a later partition
cannot rescue it. Labels retain their actual source publication date, and
monthly rank/quarterly brake fits accept them only after publication and the
fixed label-overlap purge. Missing feature columns are handled inside each
past-only fit. `fit_shadow` produces no forecast before its registered
training minimum rather than substituting a hindsight fit.

The prospective 20-session high-low range is adjusted bar by bar with the
same capture-vintage `adjusted_close / close` ratio. A synthetic pure-split
test now confirms that the range does not become a false price shock. There
were no `learned_inputs` observations before this correction, so no saved
feature was rewritten. A source bar vintage may still be restated after
capture, and absent delisted-name endpoints remain missing. These controls
make future shadow evaluation causal; they do not create an adoption-grade
2016–26 history or evidence that the learned policy beats the live rule.

## Independent review of the separate OpenCode groundwork

The shared development checkout has local commit `fc703b0` adding
`rank_features.py`, `rank_ranker.py` and `rank_brake.py`. Its 60 owned tests
pass, but the commit remains outside remote `main` and the guarded deploy.
Do not import it as a valid learned policy yet:

- `rank_features._atr` divides a true range from raw high/low by adjusted
  close. On a flat adjusted-price series of 10 with raw high/low 101/99,
  the result is **9.1**, a price-basis error rather than volatility.
- `forward_labels` divides later raw close by earlier raw open. A pure 10:1
  split with no adjusted-price change produces **−0.9**. Reading both raw
  prices from one later snapshot does not mechanically adjust a corporate
  action between the entry and exit. The label is also the stock's own
  next-open to D+10-close return, not the registered next-open to D+11-open
  return relative to SPY.
- `Ranker.walk_forward_rank` receives arbitrary train/test arrays and does
  not accept dates or enforce a ten-session label-end purge. Its output is
  out-of-sample only if the caller independently supplies valid folds.
- `AdaptiveBrake` applies fixed numerical thresholds; it does not learn
  market drawdown risk in a walk-forward fit. The new feature contract also
  omits the dated fundamentals and earnings-tone inputs captured above.

These are counterexamples to the claimed backtest/live parity, not evidence
that gradient boosting cannot work. Keep the incumbent as the live rule and
repair the input/label/fold contract before attempting an adoption table.
