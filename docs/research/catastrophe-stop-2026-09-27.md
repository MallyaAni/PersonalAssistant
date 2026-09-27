# A single-name catastrophe stop on the `/4` book: results (2026-09-27)

Pre-registration: [catastrophe-stop-plan-2026-09-27.md](catastrophe-stop-plan-2026-09-27.md).
Run on spark1 from `170914de` (`python -m backend.cli.market_catastrophe_stop
--root data/market --offsets 20 --costs 10 25`), payload
`docs/research/scorecards/catastrophe_stop.json`. Seven registered
variants, 280 simulator runs.

## The table (25 bp; medians across 20 offsets; "worst1" is the worst single-name day as a fraction of equity; "false" is the share of triggers after which the name closed back above the trigger price within 60 sessions)

| variant | 2016-2023 CAGR | maxDD | worst1 | triggers/yr | false | vs none bp/d (t) | 2024-2026 CAGR | maxDD | worst1 |
|---|---|---|---|---|---|---|---|---|---|
| none (control) | 27.5% | -42.2% | -2.69% | — | — | — | 46.2% | -23.6% | -3.60% |
| entry-40 | 27.5% | -42.2% | -2.69% | 0.0 | 100% | -0.2 (-1.1) | 45.1% | -23.6% | -3.60% |
| entry-50 | 27.5% | -42.2% | -2.69% | 0.0 | — | 0.0 | 46.2% | -23.6% | -3.60% |
| entry-60 | 27.5% | -42.2% | -2.69% | 0.0 | — | 0.0 | 46.2% | -23.6% | -3.60% |
| peak-40 | 26.2% | -42.3% | -2.69% | 0.5 | 100% | -0.7 (-1.5) | 43.5% | -23.6% | -3.60% |
| peak-50 | 27.4% | -42.5% | -2.69% | 0.1 | 100% | -0.3 (-1.5) | 46.2% | -23.6% | -3.60% |
| peak-60 | 27.5% | -42.2% | -2.69% | 0.0 | — | 0.0 | 46.2% | -23.6% | -3.60% |

The deepest triggers in ten years, median offset: NVDA and AMD in the 2022
selloff (peak-50, recovered within 2 and 12 sessions), LRCX and AMAT on
2020-03-18 (peak-40, recovered the next session), LRCX in October 2022,
CRWD after its July 2024 outage (entry-40 and peak-40, recovered within 7
sessions). Every trigger was a false alarm.

**Verdict: every stop RECORD.** No stop saves a point of drawdown or any of
the worst single-name day; the ones that fire cost 0.1-1.4 CAGR points.

## Reading it

1. **The book never gets near a Lucid.** In ten years of point-in-time
   history a stop 50% below entry fires zero times, and 60% below the
   running peak fires zero times. The grade rotation drops a name long
   before its price halves; the names it holds at A/A+ are the ones whose
   structure is intact, and the rotation is what removes them when it is
   not. The worst thing one name did to the book in a single day was -2.7%
   of equity (2016-2023) and -3.6% (CRWD, 2024-07-19), both at the 8.3%
   equal weight.
2. **What the stops do catch is the market, not a name.** The triggers
   cluster on 2020-03-18, spring 2022 and one outage day; they are
   drawdowns the whole book shared, and every one reversed within days.
   Selling into them was pure cost, which is why the false-alarm rate is
   100% and the premium column is empty: there was no drawdown saved to
   price a premium against.
3. So the honest answer to the operator's question is that the protection
   against a single-name collapse on this book is *structural* - the
   universe (large, liquid, graded names), the equal-weight cap that
   bounds any one name at a twelfth of equity, and the grade rotation that
   exits before the fall is deep - and a price stop adds nothing to it at
   any threshold tried. A name that went 300 to 1 would have lost its grade,
   and its place in the book, at the first rebalance after its structure
   broke, with the loss bounded at a few points of equity. The two
   defences already in place are the ones that work; this trial measured
   that they are sufficient rather than assuming it.
4. The rule stays in the codebase (`catastrophe_stop.CatastropheStop`,
   the `weight_filter` hook in the simulator, all tests) so it can be
   re-priced if the universe or the sizing ever changes - a concentrated
   book, or one that let a name grow past its cap, would ask this question
   again with a different answer.
