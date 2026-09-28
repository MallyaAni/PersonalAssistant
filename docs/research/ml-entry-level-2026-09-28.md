# ML entry level: the model sets the buy/sell level - results (2026-09-28)

Pre-registration: [ml-entry-level-plan-2026-09-28.md](ml-entry-level-plan-2026-09-28.md).
Run on spark1 from `e89033b2` (`market_fill_timing --workers 8 --offsets 20
--cost 10 --forecasts docs/research/scorecards/vol_forecasts.npz --only
next_open,dip_or_close,vol_dip_0.5,vol_dip_1.0,vol_limit_0.5,trail_dip`),
forecast file sha256 `9fc8421b...` (the CNN's next-session volatility,
trained on the RTX 5080), payload `docs/research/scorecards/ml_entry_level.json`.
The orders are the `graded-equal-weight/4` policy's own (about 945 per
offset), filled from the SIP 15-minute cube; the engine reproduces
`simulate.run` to 0.09 bp a day. The model's level is open·exp(∓k·σ̂),
σ̂ = the forecast of the fill session's volatility made at the decision
close (median 1.58% a session, so k = 0.5 waits about 0.8% under the open,
k = 1.0 about 1.6%); `trail_dip` is the same rule with trailing volatility
instead of the model. Forecasts start 2018-02-21; earlier orders fill as
`dip_or_close` (about 32% of 2016-2023 orders).

## The table (10 bp; median CAGR across 20 offsets; bp/d and t paired against `dip_or_close` - the board's rule - at the median offset, Newey-West lag 20; "dip%" = orders filled at the level before the close; "bp/fill" = the dip fill's price against that session's close, positive = better than waiting for the close)

| convention | 2016-2023 CAGR | vs dip bp/d (t) | dip% | bp/fill | 2024-2026 CAGR | vs dip bp/d (t) | dip% | bp/fill |
|---|---|---|---|---|---|---|---|---|
| next_open | 29.2% | +0.1 (+0.2) | — | — | 48.0% | -1.0 (-2.2) | — | — |
| dip_or_close (board) | 29.3% | — | 41% | -8.7 | 47.9% | — | 49% | +36.0 |
| vol_dip_0.5 (model) | 29.3% | -0.0 (-0.3) | 47% | -14.8 | 48.1% | +0.3 (+2.1) | 55% | +45.1 |
| vol_dip_1.0 (model) | 29.3% | -0.3 (-1.5) | 29% | -29.9 | 47.3% | -0.0 (-0.1) | 29% | +38.8 |
| vol_limit_0.5 (model, resting limit) | 29.2% | +0.1 (+0.7) | 54% | -9.0 | 48.1% | -0.2 (-0.8) | 66% | +25.2 |
| trail_dip (no model) | 29.3% | -0.0 (-0.2) | 44% | -11.3 | 48.1% | +0.3 (+2.2) | 49% | +59.9 |

The model against its no-model twin at the same rule (`vol_dip_0.5` -
`trail_dip`): -0.02 bp a session (t -0.28) on 2016-2023, -0.07 (t -0.59) on
2024-2026.

**Verdict: every convention RECORD; the board keeps `dip_or_close`.** No
level beats the board's rule by 2 bp a session with t >= 2 on the choosing
window, and the model's level is indistinguishable from the same level set
by trailing volatility.

## Reading it

1. **Buying the dip depends on the regime, and it nets to zero.** On
   2016-2023 a dip fill was on average 9 bp *worse* than simply buying at
   that day's close - these names kept falling into the close after a 1%
   dip (the session-anatomy finding, again). On 2024-2026 the same fill was
   36 bp *better* - dips recovered within the day. Over the full span the
   board's rule is neutral against the open and against the close, which is
   what makes it safe to show: it lets the operator wait for a level without
   paying for it, but it is not an edge.
2. **The model knows how far a name will move and not which way.** A level
   scaled by the CNN's forecast fills a different set of orders than a
   fixed 1% (dip% 29-66% against 41%) and prices them no better. Every
   deep-learning result this week has the same shape: volatility and
   drawdown are forecastable from these bars (R² 0.27, IC 0.09-0.15), the
   *direction* of the next move is not (IC 0.01), and a level needs the
   direction.
3. **What would change the answer.** A direction signal intraday - the
   index-level late-day momentum the literature documents is the one with a
   record - or a book whose names mean-revert within the day. Neither is
   this book on this evidence. The board's rule stays the measured
   `dip_or_close`, and the next registered ML question is not a level but
   the late-day index flow as a close-vs-dip switch.
