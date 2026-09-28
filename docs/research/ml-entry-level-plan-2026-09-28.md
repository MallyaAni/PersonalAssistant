# The model's volatility forecast as the entry level: pre-registration (2026-09-28)

The operator asked whether a machine-learning model can decide a better
buy or sell level than a fixed rule. The live board's rule is
`dip_or_close`: a buy fills at the first fifteen-minute bar close at least
1% under the session's open, else at the close; a sell mirrors it 1% over
the open. This plan fixes the test before any rule is run. The book, its
orders and when they are decided do not change; only the price each order
waits for does.

## What is already measured

- **Fill timing** ([execution-timing-2026-09-27.md](execution-timing-2026-09-27.md)):
  on `graded-equal-weight/4`'s own orders, seven fill conventions sit
  within ±0.2 bp a session of the next open on 2016-2023. `dip_or_close` is
  -0.1 bp a session (t -0.2) there and +1.0 (t 2.2) on 2024-2026. The book
  places about 945 orders per offset over the whole history, roughly one
  every three sessions, each at most about a tenth of the book.
- **Session anatomy**: a 2% dip by 11:30 is followed by slightly *less*
  return to the close, not more (t -2.5 on 2016-2023, same sign on
  2024-2026). A dip fill buys below the open, but on average not below the
  close.
- **The forecast** ([vol-sizing-2026-09-27.md](vol-sizing-2026-09-27.md)):
  the stage-1 temporal CNN's volatility head forecasts the next session's
  log realized variance with out-of-sample R² 0.271 on 2016-2023 and 0.260
  on 2024-2026 against the trailing 20-session baseline. As a sizing input
  it lost to equal weight; that note says the forecast belongs in
  execution. This trial puts it there. The file is
  `docs/research/scorecards/vol_forecasts.npz`
  (sha256 `9fc8421be69abfd09481f323d79f3709c543e5d3a82d4c1790acead3d5cbb131`):
  81,612 rows for 94 names from 2016-02-01, of which 69,920 are scored,
  starting 2018-02-21 after the 500-session warm-up.
- **The scale.** On the scored rows, σ̂ = exp(F/2) has a median of 1.58%
  (5th-95th percentile 0.95-2.81%). The trailing σ̂ has a median of 1.78%
  (1.03-3.44%). So k = 0.5 puts the level about 0.8% from the open
  (0.5-1.4%), and k = 1.0 about 1.6% (0.95-2.8%), against the fixed 1%.
  These are the inputs' scale only; no fill or return was computed to get
  them.

## The trial

**Question.** On the `/4` policy's orders, does a buy or sell level scaled
by the model's forecast of how far the name will move tomorrow fill better
than the board's fixed 1% rule? And if it does, is that the model, or
merely scaling by volatility?

**σ̂ and its alignment.** F is the forecast in the file's row
(name, t). It is made from bars through t's close and targets session
t + 1's log realized variance: the sum of squared fifteen-minute log
returns over the 26 bars, with bar 0 measured from the open, so the
overnight gap is excluded. `vol_forecast.align` puts row (name, t) at the
panel's row of t, exactly as the vol-sizing trial reads it. An order
decided at t's close fills in session t + 1 and reads σ̂ from the row
dated t, never from a later row (`fill_timing.fill_sigma`). The tests
check this in two ways. Shifting the forecasts by one session changes
the result. Altering every forecast row from session s on leaves every
return through s bit-identical.

**Conventions, fixed now (four registered trials):**

1. `vol_dip_0.5`: a buy fills at the first bar close ≤ open·exp(−0.5·σ̂),
   else at the official close. A sell fills at the first bar close ≥
   open·exp(+0.5·σ̂), else at the close.
2. `vol_dip_1.0`: the same with k = 1.0.
3. `vol_limit_0.5`: a resting limit at open·exp(−0.5·σ̂). It fills at the
   *limit price* if some bar's low is strictly below the limit, else at the
   close. The inequality is strict so that a bare touch never counts as a
   fill. Sells mirror it on the highs.
4. `trail_dip`: `vol_dip_0.5` with σ̂ = exp(B/2), where B is the file's
   `baseline` column: the log of the mean realized variance over the 20
   sessions through t. That is the quantity the R² 0.27 is measured
   against, and the vol-sizing trial's trailing twin. No model is
   involved. It is the control for "the model knows the scale".

Controls, not trials: `next_open` (the simulator's fill) and
`dip_or_close` (the board's rule).

**Fallback.** Where the forecast is missing, the order fills as
`dip_or_close` and is counted per convention and window. The forecast is
missing before 2018-02-21, and on a (name, session) the dataset has no
row for, such as a name out of the membership file. `trail_dip` uses the
trailing σ̂ on exactly the cells where the forecast exists and falls back
everywhere else, although the baseline itself starts in 2016. So its
fallback share is the model's by construction, and `vol_dip_0.5` against
`trail_dip` differs only in where σ̂ comes from.

Two consequences follow, both stated now:

- About 26% of the choosing window's sessions (2016-01 to 2018-02) carry
  identical fills in every level convention and `dip_or_close`, so their
  paired difference is exactly zero. On the covered sessions, the 2 bp
  floor therefore corresponds to about 2.7 bp. The t statistic is
  unaffected to first order, because the mean and its standard error
  shrink together.
- The model predicts the log of realized variance. The baseline is the
  log of its mean. So the trailing σ̂ is about 11% larger at the median
  (1.78% against 1.58%), and at the same k `trail_dip`'s level sits about
  0.1 points deeper than `vol_dip_0.5`'s. The twin comparison measures
  the model's σ̂ against trailing σ̂ exactly as the R² does, centring
  included. If a win over the twin comes only from centring, the dip fill
  rates will show it, because the model's rate would be higher at the
  same k.

**Fills and everything else.** The engine is `backend/market/fill_timing.py`
unchanged, and the new conventions extend it:

- Orders are the plain simulator's.
- The ledger is `simulate._Book`.
- The cost is 10 bp one way on every fill.
- Raw SIP prices move to the adjusted basis by the session's own
  official close.
- Marks are at the panel's adjusted close.
- A fill session with no complete cube session fills at the panel's
  open, which is the existing fallback, counted separately.
- "The close" is the closing auction's print, else the last bar's close:
  the price `dip_or_close` already falls back to.

**Statistics.** For each convention and each window (2016-2023
choosing, 2024-2026 reported, and all), at 10 bp:

- median CAGR across the 20 offsets;
- at the median offset, the paired daily difference against
  `dip_or_close` and against `next_open`, in bp per session, with a
  Newey-West t at lag 20;
- the offsets whose CAGR is above `dip_or_close`'s;
- the level conventions against `trail_dip`, paired the same way;
- from the median offset's orders filling in the window:
  - the dip fill rate: the share of orders filled at their level before
    the close;
  - the mean gain per dip fill over that session's official close, in bp,
    positive when it is better for the trader. This is what the operator
    would feel per trade. Buys score (close − fill)/close and sells
    (fill − close)/close;
  - the same gain averaged over every order, where an order filled at the
    close scores zero;
  - the share of orders with no σ̂.

The best level convention against `dip_or_close` is reported with its
deflated Sharpe against four trials.

**Kill criteria, fixed now.** A convention REPLACES the board's rule only
if all three of these hold:

1. On 2016-2023 it beats `dip_or_close` by at least **2 bp a session**
   (about 5 CAGR points a year on a fully invested book) with Newey-West
   **t ≥ 2.0**.
2. It is not worse than `dip_or_close` on 2024-2026: its mean paired
   difference is ≥ 0.
3. It beats `trail_dip`: its mean paired difference against `trail_dip`
   on 2016-2023 is above zero.

A convention that passes the first two and fails the third is **RECORD
(vol-scaling, not the model)**. `trail_dip` itself can never replace the
rule in this trial, because the question is the model's. If it passes
the first two, it too is recorded as vol-scaling, not the model, and a
fixed vol-scaled rule would then need its own registration. Anything else
is **RECORD**. Four trials are counted. A REPLACES verdict would change
the board's rule as a separate change, never inside this one.

## Prior

The forecast's R² of 0.27 means a scaled level should fill dips more
selectively than a fixed 1%. It would wait deeper on the days the name
will range widely and shallower on quiet days, so fewer of its dip fills
would be the ordinary noise of a wide day. Against that:

- The orders are few, about one every three sessions and each at most a
  tenth of the book. A 20 bp better price per order is worth under 1 bp a
  session.
- Dips continue slightly on average (session anatomy), so a deeper level
  buys lower, but not lower than the close.
- The fixed rule itself earns nothing over the open on the choosing
  window.

**Expected: at most 1 bp a session over `dip_or_close`, below the 2 bp
floor, and RECORD on every convention.** A 2 bp session edge would need
upwards of 60 bp per order on average (2 bp ÷ (0.35 orders a session ×
a 9% slice)), which is several times what any fill-timing rule on these
orders has shown.

**What would make the prior wrong.** A model convention clearing
2 bp a session over `dip_or_close` with t ≥ 2 on 2016-2023, not worse on
2024-2026, and above `trail_dip`. That would mean the forecast's
knowledge of tomorrow's range is turning into entry prices tens of basis
points better per order. It would show first as a positive gain per dip
fill where `dip_or_close`'s is near zero or negative. If only `trail_dip`
cleared the floors, scaling by volatility would help and the model would
add nothing to it.

## Not in this trial

- What is held and when it is decided are unchanged.
- k is fixed at 0.5 and 1.0 and is not tuned after the run.
- No other σ̂ source or model is scored.
- The live board keeps `dip_or_close` unless the verdict names a
  replacement, and then only as a separate, registered change.

## Run

On the Spark, from the store:

    python -m backend.cli.market_fill_timing --root data/market --workers 8 \
        --offsets 20 --cost 10 \
        --forecasts docs/research/scorecards/vol_forecasts.npz \
        --only next_open,dip_or_close,vol_dip_0.5,vol_dip_1.0,vol_limit_0.5,trail_dip

This prices six conventions from 20 offsets (120 ledger walks against the
fill-timing run's 140) and writes `<root>/desk/ml_entry_level.json`. The
payload carries the forecast file's sha256.
