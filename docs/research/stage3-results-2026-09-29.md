# Stage 3: level-aware, multi-timeframe models on the board's own decisions: results (2026-09-29)

Pre-registration: [stage3-plan-2026-09-29.md](stage3-plan-2026-09-29.md), with
its two addenda written before any export or run. The research behind it is
[feature-research-2026-09-29.md](feature-research-2026-09-29.md).

## Run

- **Code.** `research/stage3` at `79cf4e2` for the export and training.
  The decision tests ran on the same code; `a986f1c` and `7474dcb` add
  only the verdict command. The post-hoc diagnostics ran on `e2e1bac`.
- **Export.** It ran on spark1 at 06:29Z and took 8 minutes. The files
  are under `data/market/research/stage3/`:

  | File | Contents | sha256 |
  |---|---|---|
  | `stage3_s1.npz` | 88,063 rows x 208 columns, 2016-01-04..2026-09-28 | `7fa24f7e` |
  | `stage3_ti.npz` | 2,081,688 rows (86,737 name-sessions x 24 slots) x 281 columns | `32318049` |
  | `stage3_seq.npz` | 94 names x 2,678 sessions x 27 steps x 12 channels | `e6d1d823` |
  | `stage3_ohlcv.npz` | the adjusted daily bars | `a6c2b718` |

- **Training.**
  - It ran on the RTX desktop. LightGBM used the i9-10900K with 16
    threads; the networks used the RTX 5080.
  - Wall times: M1 T-S1 17 min, M1 T-I 29 min, M2 I5 17 min, M2 I20
    21 min, M3 T-I 18 min, M3 T-S1 87 min.
  - Every run used the registered settings, and each forecast file
    records `registered: true`.
  - The forecasts are kept on spark1 under
    `data/market/research/stage3/forecasts/` (sha256 prefixes: `s1_lgbm`
    `0ff9987f`, `s1_cnn_i5` `efed6f9d`, `s1_cnn_i20` `297e268a`, `s1_seq`
    `c89f17f7`, `ti_lgbm` `e3345129`, `ti_seq` `a16e7b1a`).
- **Decision tests.** They ran on spark1 as registered:
  - T-I: `market_fill_timing` at 10, 16 and 25 bp, a `--next-bar` run and
    five single-seed runs;
  - T-S1: `market_stage3_overlay` at 10, 16 and 25 bp, plus five
    single-seed runs.

  `market_stage3_verdict` read all 42 payloads (none missing) and wrote
  the verdicts. In `docs/research/scorecards/stage3/`:
  - `verdicts.json`, with every seed run's reading;
  - the ensemble payloads;
  - the tree diagnostics (`*_lgbm_diag.json`);
  - the export summary.

  All 42 payloads are kept on spark1 under
  `data/market/research/stage3/decisions/`.
- **Verification.** An independent check found no leak and no mislabelled
  row produced by the stage-3 code. It covered:
  - **Labels.** Every T-I label was recomputed from the cubes; the largest
    difference is 1e-4 bp. Every S1 label and relative return was
    recomputed.
  - **Features.** Sampled intraday features were recomputed.
  - **The rule of the moment.** It was re-run on real cubes by tampering
    with 33 bars, sessions and benchmarks.
  - **Folds and fills.** Every fold's purge, embargo and validation block
    was checked. All 203,974 T-I fills were re-implemented, with 0
    mismatches.
  - **The daily block.** It is joined at t = s−1, never at s.

  The data issues it found are outside the stage-3 code and change no
  verdict:
  - one stale ORCL open in the daily store (2017-06-22), which mislabels
    2 S1 rows;
  - 82 T-I name-sessions whose auction print differs from the daily close
    by more than 1%.

## The verdicts

**Every candidate: RECORD.** The board keeps `dip_or_close`, and
the live executor keeps `graded-equal-weight/4` with the idle-cash
redeploy.

### T-I: now or the close

The table compares each candidate with `dip_or_close` on the `/4` policy's
own orders, over 20 offsets:

- **Model window:** the first forecast session, 2018-01-03, through
  2023-12-29.
- **Paired statistics:** at the median offset, Newey-West lag 20.
- **"Per differing order":** candidate minus control over the orders where
  the two fill at different prices, with the t clustered by date.

| Candidate | Model window, bp/session (t) at 10 / 16 / 25 bp | Next-bar run | 2024-2026 bp/session (t) | Per differing order, bp (t) | Seeds | Verdict |
|---|---|---|---|---|---|---|
| `lgbm_filter` | −0.6 (−1.94) at all three | −0.6 (−1.94) | −0.2 (−1.08) | −40.0 (−1.94) | stable | RECORD |
| `lgbm_free` | −0.6 (−1.55) / −0.6 (−1.54) / −0.6 (−1.54) | −0.6 (−1.54) | −1.5 (−2.96) | −18.5 (−1.41) | stable | RECORD |
| `seq_filter` | −0.2 (−0.57) at all three | −0.2 (−0.58) | −0.4 (−1.60) | +14.8 (+0.60) | 2 sign changes | RECORD |
| `seq_free` | −0.1 (−0.19) / −0.1 (−0.18) / −0.1 (−0.19) | −0.1 (−0.20) | −1.5 (−2.97) | −6.3 (−0.38) | 3 sign changes | RECORD |

Deflated Sharpe at N = 8: 0.00-0.06, against the 0.95 floor. What the
rules did:

- **The `filter` rules.** They vetoed 134-154 of the board's dip and pop
  fills in the model window.
- **The `free` rules.** They moved 55-76% of orders off the close:
  85-88% of buys and 26-65% of sells.

### T-S1: which graded names to hold

The overlay drops the lowest-forecast tenth of the A/A+ book at each
allocator call, and is compared with `ew-redeploy`, the live executor.
Each row reads its model window, from the first forecast date (2017-12-27)
through 2023, with statistics at the median offset.

| Candidate | Model window, bp/session (t) at 10 / 16 / 25 bp | Offsets above control (of 20) | Worst drawdown vs control | 2024-2026 bp/session (t) | Seeds | Verdict |
|---|---|---|---|---|---|---|
| `lgbm` | +0.4 (+0.79) / +0.4 (+0.72) / +0.3 (+0.68) | 11 | +1.0 pt | −0.7 (−0.79) | stable | RECORD |
| `cnn_i5` | −0.4 (−0.91) / −0.4 (−0.93) / −0.4 (−0.97) | 5 | +0.2 pt | +0.7 (+1.26) | stable | RECORD |
| `cnn_i20` | −0.2 (−0.49) / −0.2 (−0.53) / −0.2 (−0.58) | 11 | +0.0 pt | +0.8 (+1.48) | stable | RECORD |
| `seq` | +0.3 (+0.73) / +0.3 (+0.73) / +0.3 (+0.72) | 20 | +2.1 pt | −0.0 (−0.04) | 3 sign changes | RECORD |

Deflated Sharpe at N = 8: 0.01-0.27 (`seq` highest), against the 0.95
floor.

`seq` is the only overlay above the control at all 20 offsets, with the
smaller drawdown. It still fails four criteria:

- **The floor.** It earns about a sixth of the +2.0 bp it needs.
- **2024-2026.** It is −0.02 bp/session there, and the criterion asks
  for zero or more.
- **The deflated Sharpe.** It reaches 0.27.
- **The seeds.** The five single-network runs at 25 bp read +0.53,
  −0.22, +0.05, −0.17 and −0.17 bp/session against the ensemble's +0.33.
  The small edge belongs to the average of five networks, not to any one
  of them.

The overlay changes little by construction. It drops one name (two from a
book of eleven or more), and only from a book of at least five. The A/A+
book with a forecast averages 6.4 names on 2016-2023 and 4.8 on 2024-2026,
and it had five or more on 81% and 56% of those sessions
(`book_diagnostics.json`).

It also leaks. The live executor's breakout entry does not read the
allocator's targets (addendum). So after a reset dropped a name, the book
still held it on 53-64% of the sessions until the next reset, at a mean
7-9% weight across them (the payloads' `drops.held_after_reset_drop`).
The section after the next one measures how much this and the cap cost.

## Out-of-sample information in the forecasts

T-I is scored with pooled Spearman and T-S1 with the mean daily Spearman
IC. The choosing window is 2016-2023 (from each model's first forecast);
2024+ is the later window.

| Model | Choosing | 2024+ |
|---|---|---|
| M1 T-I (LightGBM) | +0.013 | −0.013 |
| M3 T-I (sequence) | +0.019 | +0.011 |
| M1 T-S1 (LightGBM) | +0.018 | −0.021 |
| M2 I5 | +0.013 | +0.006 |
| M2 I20 | +0.001 | +0.001 |
| M3 T-S1 (sequence) | +0.038 | +0.040 |

- **M1 T-S1 by year.** −0.120 in 2018, −0.054 in 2019, then +0.021,
  +0.066, +0.070 and +0.128 for 2020-2023, then −0.012, +0.007 and −0.076
  for 2024-2026.
- **M1 T-S1 significance.** The Newey-West t of the choosing-window IC is
  0.93. The naive 3.2 ignores the 20-session overlap.
- **M3 T-S1 by year.** +0.013 in 2018, −0.012 in 2019, then +0.027,
  +0.033, +0.091 and +0.076 for 2020-2023, then +0.035, +0.063 and +0.013
  for 2024-2026 (2026 through August): positive in 8 of 9 years. Its
  Newey-West t is 2.27 on the choosing window and 1.63 on 2024+. It is
  the only stage-3 forecast with a material IC that held its level after
  2023.
- **Validation versus test.** Each fold's chosen configuration is the
  best of eight on one validation block, so its validation IC is biased
  up.
  - **M1 T-S1.** Validation IC 0.073 on average (−0.022 to 0.139 over 35
    folds); the test blocks delivered 0.018.
  - **M3 T-S1.** Validation IC 0.053 (−0.002 to 0.091 over nine folds);
    the test blocks delivered 0.038.

  The sequence model's gap is under a third of the trees'.

**Late-day index momentum on our own bars** (the registered diagnostic).
It regresses SPY's last half hour (15:30 to the close) on its first half
hour (prior close to 10:00) and on its twelfth (15:00-15:30), Newey-West
lag 5:

| Window | Sessions | First half hour (t) | Twelfth half hour (t) | R² |
|---|---|---|---|---|
| 2016-2023 | 1,996 | +0.021 (+0.64) | +0.079 (+0.83) | 0.54% |
| 2024-2026 | 681 | −0.017 (−0.92) | +0.008 (+0.11) | 0.25% |

Gao et al. found this effect on 1993-2013 SPY. On this sample it is
absent, which is why no index-flow rule was worth registering.

## After the verdicts: the sequence model's laggard (post-hoc)

**This section is not a registered result.** It was run after the eight
verdicts, and after their 2024-2026 readings had been seen. The question
was why the overlay turned the most informative forecast into almost
nothing.

- **The command.** `market_stage3_diagnostics`
  (`backend/market/stage3_diagnostics.py`, tested). Its output is
  `scorecards/stage3/book_diagnostics.json`.
- **The trial count.** It scored 126 drop rules, and they count as
  trials in any later registration's tally:
  - 4 forecasts × 3 book minimums × dropping the lowest or the highest
    name;
  - 17 chart features × 2 directions × 3 minimums.

  The book's cumulative count goes from 282 to 408. The ICs and
  correlations it also reports are descriptive.

It reads each forecast inside the A/A+ book, the names the policy
actually holds, on dates when the book has at least five names. Each cell
is 2016-2023 / 2024-2026; the first window starts at each model's first
forecast, late in 2017:

| Forecast | IC inside the book (t) | Lowest-forecast name vs the book, bp per 20 sessions (t) | Frictionless drop, bp/session (t) |
|---|---|---|---|
| `lgbm` | +0.013 (+0.36) / −0.024 (−0.32) | +25 (+0.48) / +198 (+1.23) | −0.09 (−0.23) / −1.09 (−1.26) |
| `cnn_i5` | −0.001 (−0.09) / −0.009 (−0.33) | +4 (+0.23) / −58 (−0.99) | −0.07 (−0.56) / +0.25 (+0.71) |
| `cnn_i20` | +0.007 (+0.38) / +0.061 (+2.04) | −17 (−0.63) / −169 (−3.32) | +0.15 (+0.76) / +0.85 (+2.55) |
| `seq` | +0.048 (+1.50) / +0.089 (+1.25) | −110 (−2.85) / −328 (−3.45) | +0.78 (+2.80) / +1.64 (+3.04) |

The columns:

- **"Lowest-forecast name vs the book."** The next 20 sessions' return of
  the book's lowest-forecast name, minus the book's mean.
- **"Frictionless drop."** What dropping that name and spreading its
  weight over the rest would have earned, per session. It is averaged
  over every session, counting zero where the book had fewer than five
  names. It is before costs, before the 20% cap and before the executor.
- **The t.** Newey-West at lag 20.

What it shows:

- **The sequence model finds the book's laggard.**
  - **2016-2023.** Its lowest-forecast A/A+ name lagged the book by 1.1%
    over the next 20 sessions (median 1.4%, lagging on 59% of dates).
  - **2024-2026.** It lagged by 3.3% (median 3.1%, on 69% of dates).
  - **By year.** It lagged in 8 of the 9 years from 2018. 2019 is the
    exception, at +0.6%.
  - **Smaller books.** The reading holds with books of three or four
    names: −94 and −104 bp on 2016-2023, −283 and −281 on 2024-2026.
  - **The top name.** Its highest-forecast name is weaker: +36 bp (t 0.7)
    and +252 bp (t 1.8).
  - **The other forecasts.** They show nothing on 2016-2023. `cnn_i20`
    finds a laggard on 2024-2026 only.
- **It is not a chart rule.**
  - **What it leans on.** Inside the book the forecast leans toward
    trend. On 2016-2023 its rank correlation is +0.25 with 12-1
    momentum, +0.22 with the 60-day return, and +0.27 and +0.22 with
    the weekly and monthly trend slopes. On 2024-2026 it also leans away
    from stretch: −0.27 to −0.34 with RSI, Keltner and Bollinger
    position, the distance above the 20-day average and closeness to the
    52-week high.
  - **What the features do alone.** Take the book's weakest name by any
    one of seventeen chart features. Over the next 20 sessions it did
    between 0.9% worse and 1.1% better than the book (books of five; 1.2%
    worse to 0.8% better with books of three or four). No such rule's |t|
    exceeds 1.2 in either window.
  - **The strongest name instead.** Picking it by one feature reaches |t|
    1.7 on 2016-2023, in both directions. On 2024-2026 it reaches 2.8,
    with the strongest names winning.
  - **Stretched names kept winning.** Dropping the most stretched name
    by 20-day return would have cost 4.5% per 20 sessions on 2024-2026
    (t +2.4).
- **Why the registered overlay could not use it.**
  - **Too few sessions.** It acts only on books of five or more: 81% of
    2016-2023 sessions and 56% of 2024-2026.
  - **The cap turned the drop into cash.** With exactly five names, four
    at the 20% cap hold 80%. The drop then swapped the laggard for cash,
    not for the other four, and gave up the book's own rise on that fifth
    of the money. That was 12% of 2016-2023 sessions and 22% of
    2024-2026.
  - **The executor bought dropped names back.** It did so on 53% of the
    sessions after a reset drop (above).
  - **Net.** On the model window, after costs, the overlay kept +0.33
    bp/session of the +0.78 available before them. It kept none of the
    +1.64 on 2024-2026.
- **The ceiling is below the floor.**
  - **2016-2023.** Even captured whole, the drop is worth +0.78 bp a
    session (t 2.80), less than half the +2.0 bp the plan set for a
    selection change. It is +0.82 (t 2.46) with books of four and +0.77
    (t 2.05) with books of three.
  - **2024-2026.** It would have been worth +1.6 to +3.2 bp a session
    (t 2.4-3.0), but that window has now been read twice.

The laggard looks real in both windows, but its t alone proves nothing.
At 408 cumulative trials the expected best null t is 2.99 (the plan's
formula), and the laggard's t of 2.8-3.5 sits at that level. What makes it
worth a forward test is that it holds in both windows and at every book
size. It is small on the window the floor is judged on, and the window
where it is large is no longer a clean test. The honest next step is a
forward shadow ([laggard-shadow-plan-2026-09-29.md](laggard-shadow-plan-2026-09-29.md)):

- record the model's laggard each night in a shadow ledger;
- change nothing the board shows;
- judge it on sessions nobody has seen, against criteria written before
  the first one.

## Reading it

1. **The operator's hypothesis, tested fairly: the inputs were not what
   was missing.**
   - **Inputs.** Every model now saw:
     - the EMAs, Bollinger and Keltner bands, RSI, stochastics, MACD and
       ADX;
     - trend on 15-minute, hourly, daily, weekly and monthly bars, with
       their alignment;
     - 22 support/resistance levels across timeframes, with zones and
       confluence;
     - the VWAP, opening range, prior-day levels, floor and Camarilla
       pivots, relative volume by slot and relative strength against the
       sector ETF and SPY;
     - the overnight gap inside the path.
   - **Training.** Hyperparameters and epochs were chosen by nested
     validation with early stopping, and ensembled over five seeds.
   - **Result.** The decisions came out the same as every earlier stage.
     Nothing beats the board's 1% dip rule. On 2024-2026 the models' own
     timing is worse than it: `free` loses 1.5 bp a session, t −3.0.
     Nothing beats holding the whole graded book.
2. **What the models did learn is market-level, not name-level.**
   - **Timing trees.** M1 T-I's permutation importances are led by
     date-level inputs:
     - the VIX's 20-day change and level;
     - breadth, the AI-drawdown regime and intraday breadth;
     - turn of month, QQQ since the open, SPY's first half hour and the
       FOMC clock.

     The name's own levels, VWAP, opening range and pivots are not in the
     top thirty. The trees learned a noisy read of where the whole market
     closes. Applied to one order at a time, that read cost money.
   - **Selection trees.** M1 T-S1's importances are led by filings and
     tone, not charts:
     - book to market, the change in release demand tone and revenue
       quarter on quarter;
     - the desk's value stance and bullish count.

     Momentum follows: 12-1 is 6th and the 20-session return 8th. The
     first trend or oscillator feature is the monthly 10-SMA slope, at
     18th, and ADX is 26th.
3. **The charts' simplest consistent signal, a one-month reversal among
   graded names, does not hold inside the A/A+ book.**
   - **Which features.** Univariate ICs against the 20-session relative
     return have the same sign on 2016-2019 and 2020-2023. All of these
     are negative, in both halves, at about −0.03 to −0.05:
     - the 20-session return;
     - the EMA 9/21 slopes;
     - the distance above the 20-day average;
     - Keltner position, RSI(14) and stochastic %D.

     Graded names that are stretched above their short averages lag their
     peers over the next month, and stretched-down names lead.
   - **How big it is.** It is consistent but small. Across every graded
     name its |IC| is 0.03-0.05. That is in-sample and univariate, not
     walk-forward, and not the increment within the A/A+ book that the
     floor needs. It is the monthly form of "buy the good stock on a
     dip". LightGBM already had these columns, and its walk-forward IC
     reached 0.018. It could not turn them into a better book.
   - **Inside the book.** The post-hoc section tested the A/A+ names
     alone. Dropping the most stretched one by 20-day return was flat on
     2016-2023 (−14 bp per 20 sessions, t −0.25). It would have cost 4.5%
     on 2024-2026 (t +2.4).

     The reversal separates graded names at large, not the A/A+ names
     from each other, so a tilt inside the book has nothing to work with.
     The reversal tilt is withdrawn as a next step.
4. **The support/resistance and VWAP effects of this morning's study did
   not survive the decision test.**
   - The inputs were in the model: the isolated-level bounce, and VWAP as
     a momentum pivot.
   - The sequence model's filter gains +14.8 bp on the orders it changes
     (t 0.6). That is a whisper of the isolated-level effect, and it
     reverses on 2024-2026 (−52.7 bp).
   - The effects are intraday and last hours, and they do not move a book
     that places 0.38 orders a session.
5. **The prior was right, and so is the board.** The registration gave
   12-15% odds of any pass. The eight candidates are four timing rules,
   all at or below zero, and four selection overlays within 0.4 bp a
   session of the live executor, none with |t| above 1.
   - **Where the information is.** In this book it sits in the grades,
     the filings and release tone, and in holding the whole graded book
     fully invested.
   - **What the charts add.** Nothing on top of that has survived an
     honest decision test, at any horizon or level of sophistication
     tried since 2026-09-05.
   - **The one open lead.** The sequence model's A/A+ laggard (post-hoc
     section). Even at its frictionless ceiling it sits below the floor
     on the window the floor is judged on.

## What changes

Nothing live changes. The board keeps BUY = the 1% dip (`dip_or_close`)
and SELL/TRIM = the 1% pop, else the close. The live path stays frozen at
`checkpoint-2026-09-28`.

Deliberately open for a registered next step:

- **A forward shadow of the sequence model's A/A+ laggard** (the post-hoc
  section).
  - It is recorded nightly and changes nothing the board shows.
  - It is judged on unseen sessions, against criteria registered before
    the first one.
  - It needs the nightly export and saved network weights; the training
    kept only forecasts. So it is an engineering change on spark1 as well
    as a registration.
- **Gating the executor's mid-cycle breakout entry on the allocator's
  targets**, so that any selection overlay can hold at all. It is a design
  fix the T-S1 test exposed. It touches the frozen live path and needs
  the operator's go-ahead.

Withdrawn: the one-month reversal tilt inside the A/A+ book (point 3).
