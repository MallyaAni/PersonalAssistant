# The stretch leg: replacing a discontinuous measure — 2026-09-18

## What was wrong

The technical analyst blends four legs while the AI theme is falling:

```
rank_blend(weekly_trend, daily_trend, residual_momentum_120, -support_distance)
```

`support_distance` is `(close - support) / close`, where `support` comes from
`levels._nearest(swing_low, close, below=True, lookback=250)`. That helper
takes the highest swing low **strictly below** the close. So the session a
price ticks under its own support, that level is discarded and the measure
snaps to the next level far beneath.

The leg therefore sawtoothed. It is not a smooth function of price at all:
it is a step function whose steps land wherever swing lows happen to sit.

The operator found it on CRWV. Four consecutive sessions from the production
record on spark1:

| Session | Close | Price move | Technical rank |
|---|---|---|---|
| 2026-09-11 | 88.99 | | 0.258 |
| 2026-09-15 | 80.92 | −9.1% | 0.086 |
| 2026-09-16 | 83.35 | **+3.0%** | **0.065** |
| 2026-09-17 | 79.88 | **−4.2%** | **0.179** |

The rank fell when the price rose, then nearly tripled when the price fell
4.2%. On a longer window the leg's own percentile swung between 4 and 96 on
price moves under one percent:

| Date | Close | Move | Leg percentile |
|---|---|---|---|
| 2026-08-28 | 84.23 | −2.96% | 4.3 |
| 2026-08-31 | 84.89 | **+0.78%** | **91.3** |
| 2026-09-01 | 81.85 | −3.58% | 4.3 |
| 2026-09-03 | 84.56 | +4.49% | 96.8 |

This was never a CRWV problem. Book-wide, 3.98% of *quiet* sessions — ones
where the name moved less than 1.5% — moved this leg more than 40 percentile
points.

## Candidates

Three replacements were measured against the original through the desk's own
harness, 2018-06 to 2026-09, decided at each close and filled at the next.

- **signed** — `levels._nearest_signed`. Keeps whichever swing low is nearest
  in absolute terms and signs the distance: positive above the level,
  negative below it. Continuous through the crossing.
- **band** — `levels.band_position`. Where the close sits in its own
  20-session Bollinger band, 0 at the lower edge. Continuous by
  construction: it has no levels to lose.
- **none** — drop the leg; blend the three trend legs alone.

## Results

| Leg | CAGR | Sharpe | Max drawdown | Quiet-session flips > 40 pts |
|---|---|---|---|---|
| support (shipped) | 26.70% | 1.448 | −21.98% | 14.6% |
| **signed** | **27.07%** | **1.470** | **−19.02%** | 10.8% |
| band | 26.07% | 1.407 | −20.42% | **2.6%** |
| none | **27.83%** | **1.493** | −20.59% | — |

The shipped leg lost on every dimension that matters. It had the worst
drawdown of the four and the worst stability, and two of the three
alternatives beat its return.

## First decision: signed. It was wrong.

`signed` was adopted on the table above and shipped. It is a better measure
than the original, and it does fix the case that was diagnosed. It also
introduced a second discontinuity that the adoption test did not cover.

`_nearest_signed` keeps whichever swing low is nearest **in absolute
terms**. So the level it is measuring against switches the moment price
passes the midpoint between two levels, and the sign flips with it:

| Swing lows | Price move | Gap before | Gap after | Jump |
|---|---|---|---|---|
| 90 and 100 | 95.1 to 94.9 (0.21%) | −0.0515 | +0.0516 | 49x the price move |

The deterministic guard missed it because its fixture put both levels
*below* the price, so the midpoint case never arose. The harness missed it
because a noisier leg can still earn a return.

Measured properly across the book, on the percentile the blend actually
consumes rather than on the raw measure, `signed` barely moved the needle:

| Leg | Quiet sessions moving the leg > 40 pts | Mean step | Names still unstable |
|---|---|---|---|
| support | 3.98% | 10.06 pts | 92 of 94 |
| signed | 2.61% | 7.40 pts | 89 of 94 |
| **band** | **0.83%** | 8.62 pts | **17 of 94** |

A name counts as unstable when more than one quiet session in a hundred
reshuffles it by more than 40 percentile points.

## Decision: band

`none` edges the return and the Sharpe. That margin — 0.76 points of CAGR and
0.023 of Sharpe over eight years — is well inside the noise of a single
sample, and taking it would leave the desk with no mean-reversion reading at
all. A name resting on support below its averages would be scored on trend
alone, permanently. That is the exact complaint that started this work: the
operator looked at CRWV near an $80 support under its lower band and could
not see why the desk called it bottom-of-book.

`band` selects no level at all. It is where the close sits in its own
twenty-session range, so no level can drop in, drop out, or be switched
away from, and neither discontinuity can occur by construction. It cuts
violent flips roughly five-fold and unstable names from 89 to 17.

It costs about a point of CAGR against `signed` (26.07% vs 27.07%) and 0.06
of Sharpe. That trade is worth taking: `signed`'s edge was measured on a leg
that was still jumping, `band` still beats the shipped original on drawdown
(−20.42% vs −21.98%), and it is the reading a trader actually has in front
of them on the chart. The operator's original complaint was precisely that
the desk could not see a name sitting on its lower band.

## Verification across the book

Re-scored all 94 columns on production data and compared each candidate's
behaviour on quiet sessions, as the percentile the blend consumes:

| Leg | Flips > 40 pts | Mean step | p99 step | Names still unstable |
|---|---|---|---|---|
| support (was live) | 3.98% | 10.06 pts | 66.17 pts | 92 of 94 |
| signed (briefly live) | 2.61% | 7.40 pts | 60.56 pts | 89 of 94 |
| **band (ships)** | **0.83%** | 8.62 pts | **38.55 pts** | **17 of 94** |

`signed` reduced the average but left 89 of 94 names unstable by the same
standard, which is why "fixed" was the wrong word for it. `band` is the
first candidate that changes the answer for most of the book.

The 17 names `band` leaves unstable are a different problem: the band is
narrow for a name whose twenty-session range has collapsed, so a small move
is a large fraction of it. That is a property of the measure rather than a
defect in it, and it is not a level dropping in or out. It is not addressed
here.

## The defect the deploy gate caught

The first deploy of this change failed the gate on
`test_technical_analyst_switches_on_theme_trend`, and it was right to.

`support_distance` takes the highest of the nearest swing low *and* the 50,
200 and weekly 21 averages below the close, so it is almost never absent.
`support_gap` reads swing lows alone. A name that has climbed for a year
without printing a swing low therefore has no value at all, and it fell out
of the blend: that name scored on three legs while the rest of the book
scored on four, silently.

The original code already handled this for its own measure, treating "no
level beneath you" as the stretched end of the scale rather than the
supported end. That rule now applies to whichever measure is selected, in
`technical._fill_with_the_most_stretched`, and
`test_a_name_with_no_swing_low_is_still_scored_on_every_leg` pins it.

This is the second time in this change that the safety net rather than the
reasoning caught the error, and both were worth the cycle.

The harness was re-run afterwards to check the fallback had not moved the
result, and it returned the same figures to every decimal place: signed at
27.0739891063996% CAGR, 1.469525705533127 Sharpe, −19.016597514819866%
drawdown, against support at 26.70091205253433% / 1.4477984264436379 /
−21.97652504096569%. So no name in this book over these eight years was
both unreadable by the swing-low measure and large enough in the traded
portfolio to shift a return. The table above therefore describes the code
that ships, fallback included.

## Guard

`backend/tests/test_market_stretch_leg.py` pins the mechanism rather than a
threshold. An earlier attempt used random paths and percentile limits, and
on real prices every candidate has some quiet session where it moves the
width of the cross-section, so a threshold either passed everything or
failed everything.

The guard instead builds two swing lows and steps a close across the nearer
one, in four rows. It asserts that the original measure jumps (so the guard
cannot silently go blind), that the signed measure moves by roughly the
price move and changes sign, that the shipped selector is never `support`,
and that `live_technical` still scores by calling the nightly analyst's own
`opine` — which is what makes one constant enough to fix both the nightly
grade and the 15-minute board read.

## Note on the live path

`backend/market/live_technical.py` does not reimplement the score. Its
`_live_read` calls `technical_analyst.opine(live, view.ai_trend)` on the
nightly analyst module directly, so the 15-minute read inherited the defect
and inherits the fix from the same constant. A test now pins that, because
a future fork of the scoring into the live path would reintroduce the
divergence silently.

## Still open

`support_distance` remains published in `LEVEL_NAMES` and is still what the
reads quote in words ("nearest support is 1.1% below the price"). That is
correct for a sentence describing where the level is; it is only wrong as a
*score*. It is no longer blended into any score.
