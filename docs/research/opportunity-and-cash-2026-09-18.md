# Is the opportunity score a signal, and is cash ever one? — 2026-09-18

Two questions the operator asked, neither of which had ever been measured.

Everything below is the desk's own 93-name book, 2015-01-02 to 2026-09-17,
2,944 sessions. Labels are 20-session forward returns, the desk's own
rebalance horizon. All statistics are computed on **non-overlapping**
windows, 147 of them, because 20-session windows otherwise share 19 of every
20 observations and make noise look like skill.

## 1. The price-to-opportunity score

It had never been backtested, and it never claimed to be a forecast:
`opportunity.py`'s first line reads "not a return forecast", and the card
repeats it. It is a weighted mean of the five analysts' cross-sectional
ranks, bent through `conviction_from_ranks` at `SHARPNESS = 2.0`, on a
0-to-10 scale. It is nevertheless displayed on every row and sorted on, so
the operator reads it as a signal.

Reconstructed for every session from the same analyst ranks the live version
uses, including its missing-analyst renormalisation:

| Signal | Rank IC | t | Quintile spread |
|---|---:|---:|---:|
| Opportunity, as shown | +0.0408 | +2.67 | +1.26% |
| Same, sharpness removed | +0.0416 | +2.76 | +1.16% |
| Desk score (grade basis) | **+0.0457** | **+3.21** | **+1.46%** |

Correlation of opportunity with the desk score: **+0.920**.

**It is a real signal.** IC 0.041 at t=2.67 is modest in absolute terms but
ordinary for a cross-sectional equity signal, and the top quintile beat the
bottom by 1.26% per 20 sessions.

**It is the weaker of two nearly identical numbers.** The grade basis wins
on IC, on t, and on quintile spread, and the two correlate at 0.92. There is
little to combine: they are one signal measured twice.

**The sharpness curve earns nothing.** Removing it *raises* the IC slightly.
`SHARPNESS = 2.0` has been bending every displayed score for no measured
benefit. It is a presentation choice, and should be described as one or
dropped; it should not be defended as calibration.

## 2. Is holding cash ever an opportunity?

The board scores 93 stocks and never scores the alternative, so it cannot
express "being out beats being in". Before inventing a cash score, the
honest question is whether any condition the desk already computes forecasts
a bad stretch.

Forward 20-session return of the equal-weight book, split by whether each
condition was true at the decision close:

| Condition | While firing | While not | Difference | t |
|---|---:|---:|---:|---:|
| Benchmark under a falling 21-day | +3.57% | +2.40% | **+1.17%** | +0.70 |
| Benchmark under its 50-day | +3.92% | +2.29% | **+1.63%** | +0.94 |
| Breadth under 40% above the 50-day | +3.99% | +2.09% | **+1.90%** | +1.25 |
| Volatility in its top quartile | +3.32% | +2.54% | **+0.78%** | +0.38 |
| Benchmark 5% or more off its high | +4.77% | +1.89% | **+2.87%** | +1.66 |
| Volatility top quartile and under the 21 | +2.75% | +2.71% | +0.05% | +0.02 |

Always invested: **+2.71%** per 20 sessions.

**Every single risk-off condition was followed by better-than-average
returns.** Not one is negative. A cash score built from any of them would
have taken the desk out of the market precisely when the next twenty
sessions paid most. The strongest reading, a benchmark five percent off its
high, preceded +4.77% against a +2.71% baseline.

No t-statistic reaches significance, so strictly none of these is a reliable
timing signal in either direction. But the *sign* is unanimous across six
independent constructions, and unanimity across six is itself evidence that
the effect is not noise around zero: on this book, weakness has been an
entry, not an exit.

**So cash should not be scored as an opportunity on this evidence.** It would
be a number that looks like analysis and loses money.

## What this says about the FOMC policy

`fomc-3-session-weakness/2` cuts exposure 50% when SPY's five-session return
is negative going into a meeting. That is the same shape as the conditions
above, and the same conditions all preceded above-average returns. The
registered gate needs six meetings before it can be judged, and it should be,
but the prior from this study is that the policy costs money rather than
saving it. It should not be extended or copied until that gate reports.

## Caveats that matter

The book is AI and software growth names, and the window is 2015 to 2026.
It contains exactly one sustained drawdown for that cohort, 2022. A cash
signal that would have helped in 2000 or 2008 cannot be detected here and
this study says nothing about it. What it does say is that on *this* book,
over *this* period, the desk's available regime evidence did not identify a
time to be out.

The opportunity study inherits whatever look-ahead the analysts themselves
carry. They are causal by construction and the harness is the same one the
grade uses, so the comparison between opportunity and the grade basis is
apples to apples even if both share a bias.

## What should change

1. Stop describing the sharpness curve as anything but presentation, or
   remove it. It costs a little IC and buys nothing measured.
2. Do not build a cash score from regime evidence. The measurement says it
   would be harmful on this book.
3. Treat opportunity as a readable restatement of the desk score rather than
   an independent input, because at 0.92 correlation that is what it is.
   Sorting the board by it is harmless; weighting it into a decision
   alongside the grade would be double-counting.
