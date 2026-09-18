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

## Decision: signed

`none` edges the return and the Sharpe. That margin — 0.76 points of CAGR and
0.023 of Sharpe over eight years — is well inside the noise of a single
sample, and taking it would leave the desk with no mean-reversion reading at
all. A name resting on support below its averages would be scored on trend
alone, permanently. That is the exact complaint that started this work: the
operator looked at CRWV near an $80 support under its lower band and could
not see why the desk called it bottom-of-book.

`band` is by far the most stable and is the measure a trader actually reads,
but it gave up both return and Sharpe against `signed`.

`signed` fixes the discontinuity, takes the best drawdown of the four, and
keeps the mean-reversion read. It ships.

## Verification across the book

Re-scored all 94 columns and compared the leg's behaviour on quiet sessions:

| | old | new |
|---|---|---|
| Quiet sessions moving the leg > 40 pts | 3.98% | **2.61%** |
| Mean leg move on a quiet session | 10.05 pts | **7.40 pts** |
| 99th percentile move | 66.12 pts | **60.49 pts** |
| Down days > 1% where the leg's rank *rose* > 5 pts | 51.7% | **47.5%** |

Per name: 85 improved, 2 unchanged, 7 slightly worse (ANET, CRWD, GLXY, MOD,
SNOW, SPY, TSM). The worst regression is GLXY at 4.92% → 6.56%; every other
regression is under a point. The aggregate is a 34% reduction in violent
flips.

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
