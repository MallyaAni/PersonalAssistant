# ML forward-paper evaluation: the specification

Written 2026-09-14 after the acceptance review, so that every later number
is read against the same definitions. Nothing here changes the frozen
production experiment.

## What each strategy is

| Strategy | Decision | Universe | Position cap | Fully invested? |
|---|---|---|---|---|
| `neural` | frozen NumPy network's forecast, top ten positive | bundle names, eligible that session | 10% of net per name | no: 10 names × 10% at most, else cash |
| `valuation_rule` | fixed sum of three normalized value ratios, top ten positive | same | 10% | no, as above |
| `momentum20` | 20-session return, top ten eligible | same | 10% | no, as above |
| `equal` (proposed control) | every eligible name | same | 10% | no: min(1/N, 10%) each |
| `SPY` | the benchmark column | SPY only | **exempt: 100%** | yes |
| `USD` | nothing | none | none | no: 100% cash |

SPY is the fully invested market benchmark and is deliberately exempt from
the stock cap; it is the reference for excess return. Every stock strategy
carries cash whenever fewer than ten names qualify, so **cash and gross
exposure are reported for every strategy on every session** alongside
return, and a comparison between a 60%-invested strategy and SPY is a
comparison of two different exposures until it is said otherwise.

## Execution and accounting

- Targets are **weights of account equity**, decided after the close of
  session t from data available at that close (prices through t; filings by
  the availability rule of the data path in use).
- The fill happens at the **close of session t+1**, in dollars: each name's
  dollar position becomes weight × net, where net solves
  `net + fee × Σ|weight × net − held| = equity`, so the fee on dollars traded
  is funded from the same account and cash never goes negative. There is
  no share rounding, no intraday price and no market impact: positions are
  fractional adjusted-price units.
- Between decisions positions **drift** with adjusted closes; nothing is
  rebalanced back to target.
- Decisions recur every **20 sessions** from the last decision. A missed
  observation cancels the standing intent rather than filling it at a price
  already seen; a missing price on a held name fails the account closed.
- Costs: **10 and 30 basis points per traded dollar**, kept as separate
  accounts; no borrowing, no shorting, no dividends beyond what adjusted
  prices carry.

## Metrics, each reported with the number of observed sessions

Net return, maximum drawdown, turnover (dollars traded over equity),
average cash and gross exposure, excess return versus SPY, and excess
return versus the equal-weight control. Untouched sessions are reported
separately from previously examined ones.

## Periods

- **Previously examined**: 2018–2023 training, 2024 model selection, and the
  retrospective test 2025-01-02 to 2026-09-11 on which the research curves
  were computed and looked at. A replay over these sessions checks that the
  production path reproduces the research result; it is not new evidence.
- **Untouched**: sessions after 2026-09-11, accumulated by the production
  ledger from its first observation. Only these count as prospective.

## Data paths

- **Frozen production path**: earliest-filed value per period, tag chosen
  once per snapshot, filing date plus one day as availability. Unchanged.
- **Versioned as-of path** (`backend/market/fundamentals_asof.py`, research
  only): every filing kept; at each session the latest-filed version
  available by then; tag chosen from the periods available then; filing
  date plus one day where the source has no acceptance time. The audit CLI
  reports where the two paths disagree. A retrain on the as-of path is a
  separate, later decision.
