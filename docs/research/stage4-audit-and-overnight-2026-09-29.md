# Stage 4 follow-up: did the ML work, and where does each order's move happen? (2026-09-29)

This note answers the operator's questions after
[stage 4](stage4-results-2026-09-29.md):

- "Are you sure you didn't make mistakes in the ML implementation?"
- "Do you have enough training data? Are the evaluation metrics improving
  during training over epochs? Are you doing a train/val/test split?"
- "There's a good chance it's losing because at the open, within the
  first 15 minutes, most of the move has already happened?"

Both parts are diagnostics, not trials. They change no verdict, and nothing
is chosen from them. The files are under `scorecards/stage4/audit/`.

## 1. The ML audit: the same code learns when there is something to learn

**Splits.** Every model walks forward. It fits on the past and tunes and
early-stops on the last 252 sessions of each training window. It then
forecasts a later test block it never saw: 63 sessions for M1, 252 for the
networks. An 11-session gap sits at each boundary, and no label reaches
across one; an independent check found a margin of at least 7 sessions.

**A positive control.** Everything was kept the same: the code (`dabd3f5`),
the rows, the inputs, the folds and the settings. Only the label changed,
from the gain of waiting, g, to its size, |g|. How big a name's next five
sessions will be is known to be predictable, because volatility is.

- M1 (LightGBM) ran the full walk-forward.
- M2 and M3 ran their first three folds, with tests from 2017-12-27 to
  2020-12-28.

The Spearman figures are out of sample:

| Model | Test rows | \|g\|: pooled Spearman | \|g\|: mean daily IC | g (registered run, same rows): pooled | g: daily IC |
|---|---|---|---|---|---|
| M1 buy | 71,334 | +0.283 | +0.272 | +0.002 | −0.005 |
| M1 sell | 71,334 | +0.257 | +0.270 | +0.025 | +0.013 |
| M3 buy | 18,981 | +0.266 | +0.202 | +0.004 | +0.006 |
| M3 sell | 18,981 | +0.219 | +0.219 | +0.004 | +0.018 |
| M2 buy | 19,203 | +0.077 | +0.019 | +0.015 | −0.001 |
| M2 sell | 19,203 | +0.064 | +0.027 | −0.044 | −0.004 |

- **The trees and the sequence model learn.** The same pipeline that finds
  nothing in the sign of g finds a daily IC of +0.20 to +0.27 in its size.
  A bug in the rows, labels, features, splits, training or forecast
  alignment would have shown up here as well.
- **The chart CNN (M2) is a weak learner at this data size.**
  - It reaches a daily IC of only +0.02 to +0.03 even on |g|.
  - Stage 3 found the same for it (IC about 0.001).
  - The published model it copies was trained on millions of chart images;
    here each fold has 5,000 to 64,000.

**Learning curves.** This is the validation loss of the chosen
configuration, epoch by epoch, from the forecast files' records (M3, first
three folds):

| M3 | Target | Improvement, first to best epoch | Best epoch |
|---|---|---|---|
| buy | \|g\| | 23%, 27%, 10% | 5, 7, 3 |
| buy | g | 2.3%, 0.6%, 0.0% | 2, 3, 1 |
| sell | \|g\| | 20%, 20%, 25% | 5, 4, 7 |
| sell | g | 0.0%, 1.8%, 0.0% | 1, 3, 1 |

- **On |g|, M3's validation loss falls for several epochs.** On g it barely
  moves, then rises as the network starts memorising noise. Early stopping
  catches this and keeps the early-stopped weights.
- **M2's validation loss falls by up to 23% even on g** (5-23% in most
  folds). That is consistent with the untrained output layer shrinking
  toward the mean, not with signal: its test IC on g is zero.
- **Validation MSE is therefore not a skill metric here.** Rank IC out of
  sample is.

**Enough data?** Each model trains on up to 64,000 labelled name-days, but
the independent information is far smaller:

- names move together on the same date;
- five-day labels overlap.

The model window holds about 1,500 sessions, roughly 300 non-overlapping
five-day periods.

- **Enough for a real effect.** Volatility is found at IC 0.2-0.3 with
  room to spare.
- **Too little for a very small one.** An edge in the direction of the
  wait at IC 0.02 would need several times more history, or many more
  names, to separate from noise.
- **The daily timeframe was already covered.** M1 reads only daily
  features, and M2 reads only daily charts. Only M3 reads 15-minute bars.
  Moving the question to the daily timeframe alone does not change the
  answer.

## 2. Where each order's move happens

This measures the live executor's own orders at offset 10, the same orders
as stage 4. Each order's price is followed from the decision close (C_t)
to:

- the next session's open;
- the close of its first 15-minute bar (09:45);
- the board's fill (dip_or_close);
- the close five sessions later.

A positive number is a move against the order: a buy's price rising, or a
sell's price falling.

**The submitted basis is used, not the executed one.** The executor holds a
sell back when the name opens green, so the executed sells are selected on
red opens. On that basis 97% of sells show an adverse overnight gap by
construction. The submitted basis counts every decision as it was made.

| Window, side | Orders | Overnight (C_t to the open) | First 15 minutes | C_t to the board's fill | The fill to t+5 | C_t to t+5 |
|---|---|---|---|---|---|---|
| 2018-2023 buys | 1,065 | +14.6 (t 3.1) | −1.2 | +22.3 (t 3.4) | +31.3 | +53.6 |
| 2024-2026 buys | 389 | +44.1 (t 3.2) | −7.8 | +51.9 (t 2.9) | +23.0 | +74.9 |
| 2018-2023 sells | 777 | −10.5 (t −2.2) | +0.3 | −15.9 (t −2.1) | −66.8 | −82.7 |
| 2024-2026 sells | 344 | −40.3 (t −3.1) | +0.3 | −52.4 (t −2.9) | +61.2 | +8.8 |

Means are in bp, and the t values are naive (orders treated as
independent).

- **The operator is half right.** Much of a buy's move happens before the
  board can act: about a quarter of the five-day rise in 2018-2023, and
  more than half in 2024-2026. It happens overnight, not in the first 15
  minutes. After the open prices dip slightly (−1 to −8 bp), which is what
  the board's 1% dip rule uses.
- **For sells the delay helps.** Prices also rise overnight after a sell
  decision, so selling at the next session gets a better price than the
  decision close would have: 16 bp in 2018-2023, 52 bp in 2024-2026.
- **Why the multi-day waits lost is a different matter.** After the open,
  buys kept rising (+23 to +31 bp more by t+5), so waiting longer for a dip
  paid the drift again.

**What this points to (post-hoc, so it is a lead, not a result):**

- **Buying at the decision day's close** (a market-on-close order), instead
  of at the next session, would have avoided the overnight rise. That is
  about 22 bp per buy in 2018-2023 and 52 bp in 2024-2026.
- **At the book's size:** 0.6-0.7 buys a session at 6-8% of equity
  makes that roughly +0.9 and +2.2 bp a session. That is more than any
  timing candidate stage 4 tested.
- **Sells stay on the next session.**
- **It needs the decision before the close.** The board would have to
  decide at about 15:45 ET, on the 15:45 price, for an order before the
  15:50 cutoff. Decisions caused by after-hours news (an earnings release
  at 16:05) cannot be made that way and would keep the next-session fill.
- **The next registered study should test it.** It would decide from
  15:45 data, fill at the official close, compare with the board's fill,
  and use stage 4's criteria. Everything it needs (the 15:45 bars and the
  official closes) is already in the SIP cubes.
