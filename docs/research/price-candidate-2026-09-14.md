# The price-sensitive candidate — specification and evaluation, 2026-09-14

**Closed 2026-09-14: no demonstrated improvement.** The results below are
preserved as measured; no further variants are run; production sizing is
unchanged and the tilt stays disabled. The diagnostic that produced them is
kept for the dashboard's explanation of each stock's size.

Research only. Production, the nightly and the frozen shadow ledger are
unchanged; the tilt stays disabled; no parameter was searched and no
model trained. Code: `backend/market/attractiveness.py`,
`backend/cli/market_price_candidate.py`, tests in
`backend/tests/test_attractiveness.py`.

## 1. The magnitude, exactly, and what it cannot see

For name i on session t with side s(i) and point-in-time log
price-to-sales x_i(t):

    d_i(t) = median over j in s(i) of x_j(t)  −  x_i(t)      distance below the side's median
    m_i(t) = tanh( d_i(t) / c(t) ),   c(t) = median over eligible j of |d_j(t)|

so m is in (−1, 1), zero at the side's median and scale-free across
sessions. **Whole-book repricing, algebraically:** under x_j → x_j + log k
for every j, every side median shifts by log k, so every d_i is
unchanged; c(t) is a median of unchanged |d_j|, so it is unchanged; so m
is unchanged. The test `test_whole_book_repricing_leaves_the_relative_
magnitude_unchanged` asserts this on the real `relative_to_group`. A
contemporaneous peer-relative measure cannot detect market-wide
expensiveness, by construction. It is a **relative valuation magnitude**,
not an expected return.

**One reference independent of today's cross-section:** the name's own
log multiple against the median of its own trailing window,

    h_i(t) = median over u in [t−W+1, t] of x_i(u)  −  x_i(t),   W = 756 sessions, ≥ 250 known,

from that name's past prices and its as-of fundamentals only. Under a
whole-book repricing on the last session h falls by exactly log k for
every name (tested), so it sees the level. Its limitations, stated: a
multiple can re-rate for good reasons, so a low h is not a mispricing by
itself; three years is short after a structural break and undefined for
a young listing; the window's fundamentals are as-of versions, so h is
honest but moves when a restatement becomes available; and it is not an
expected return. It is defined and tested here and deliberately not yet
used in the candidate, so that the candidate has one new input.

## 2. Candidacy uses signed evidence

The candidate's ordering score is Σ_a w_a · conviction_a with every
conviction signed in [−1, 1] and the value leg the average of the rank
conviction and m. `test_strengthening_a_bearish_opinion_never_helps`
shows that making any analyst more bearish, or the magnitude more
negative, lowers the score, cannot lift a name across the candidacy cut,
and cannot raise its tilted weight. **When no name passes the original
grade rule** the cut is undefined and nobody is admitted: the score never
bootstraps a book on its own; the desk stays in cash as today (tested).

## 3. Both books read corrected as-of fundamentals

The baseline rule and every variant run on the same report whose value
analyst reads `fundamentals_asof.levels` from the stored filing versions
(all 93 names); the rule on the frozen path is printed once as the
production reference. Risk is matched ex ante by the engine's own
volatility target on trailing returns; the table also shows each series
scaled by the rule's trailing sixty-session volatility over its own,
both lagged one session. Full-period realised volatility is not used.

## The candidate, and the ablations that explain it

One design: the magnitude in the ordering score (half rank conviction,
half magnitude on the value leg); candidacy = the grade rule's admissions
plus any name whose score reaches the weakest admitted name's, nobody
when the rule admits nobody, score-admitted names sized as B; the engine
weight tilted by m at 0.5, gross restored, cap re-applied. The ablations
below explain which part does what; they are not a menu, and none was
chosen on its result.

| book from 2018-06 | CAGR | lag-matched CAGR | vol | Sharpe | worst DD | turnover | top | invested |
|---|---|---|---|---|---|---|---|---|
| rule (frozen fundamentals) | +25.2% | +24.8% | 16.3% | 1.46 | -23.4% | 5.8x | 19% | 49% |
| rule (as-of fundamentals) | +25.4% | +25.4% | 16.4% | 1.47 | -22.9% | 5.8x | 19% | 50% |
| magnitude-score | +26.5% | +26.5% | 16.4% | 1.51 | -24.9% | 5.6x | 18% | 49% |
| +candidacy | +25.5% | +26.2% | 16.3% | 1.48 | -24.1% | 5.7x | 19% | 47% |
| candidate | +25.6% | +26.3% | 16.2% | 1.49 | -22.4% | 5.6x | 19% | 47% |
| tilt-only | +26.0% | +25.9% | 16.4% | 1.49 | -21.7% | 5.6x | 18% | 50% |

| by year | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|
| rule (frozen fundamentals) | +4.0% | +22.9% | +20.9% | +20.1% | -14.8% | +37.2% | +31.4% | +52.9% | +46.5% |
| rule (as-of fundamentals) | +0.2% | +28.3% | +23.2% | +15.7% | -13.4% | +44.7% | +28.7% | +56.2% | +40.0% |
| magnitude-score | +1.2% | +27.7% | +24.4% | +16.6% | -15.7% | +48.9% | +29.7% | +56.7% | +44.8% |
| +candidacy | +6.2% | +24.9% | +20.3% | +18.2% | -14.4% | +43.6% | +25.8% | +54.1% | +44.8% |
| candidate | +5.5% | +23.7% | +19.9% | +18.3% | -12.6% | +43.9% | +26.6% | +51.8% | +46.7% |
| tilt-only | +0.7% | +28.4% | +22.4% | +15.4% | -11.7% | +47.4% | +29.3% | +54.5% | +41.7% |

Years better than the rule on as-of fundamentals, of 9:
rule (frozen fundamentals) 4, magnitude-score 7, +candidacy 3, candidate 4, tilt-only 6.

## Reading

- The candidate is indistinguishable from the rule: +0.2 points of
  CAGR, +0.9 lag-matched, Sharpe 1.49 against 1.47, a slightly shallower
  worst drawdown, four years of nine ahead. Over eight years that is
  noise.
- The one piece with a consistent sign is the magnitude in the ordering
  score alone: +1.1 points, seven years of nine, and a deeper drawdown
  (−24.9% against −22.9%). Adding the candidacy rule gives most of that
  back, and the tilt adds nothing the selection did not.
- The tilt-only control, more of what the rule already selected, sits
  at +0.6 with the shallowest drawdown, which says the modest gains here
  come from where the book is, not from price-sensitive selection.
- So: a cheaper price now strengthens the case and moves the size in
  this design, and the tests prove the direction and the bounds, but
  nothing in these numbers establishes that the resulting allocation is
  better. That was the question, and the answer is not yet.

## What would establish it

Untouched sessions, not this period: the candidate as a second shadow
track beside the rule and the frozen network, the same real days, the
same costs, judged after a season. Before that, the history reference h
can be measured the same way, alone, since it is the only input here
that can see the book being dear as a whole.
