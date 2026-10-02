# Funded forward execution comparison

Registered before collecting or scoring this experiment. Source starts at
`14f61a0f`. No new timing thresholds are searched and no live orders are sent.

One regular-session cohort retains every ordinary, unsent paper plan present at
the start. Starting cash and whole-share holdings must be observed consistently
across two broker reads. Plans, starting account, code hashes and first received
quote packet are frozen before subsequent observations. This is an execution
component experiment with fixed selection, not a reconstruction of the entire
live strategy. A mid-session start is disclosed; earlier opportunities are not
recreated.

Compare the unchanged actual intraday decision with `bounded-execution/1`.
Entries and trims retain the supplied session dip/pop level as a price bound.
Full exits, identified by the planned quantity covering the starting holding,
can act without waiting for a pop. Their floor is the first observed bid less
25 bp, an explicit execution budget. Missing anchors retain an unavailable
opportunity. The same raw quote feed, 30-second maximum age and 25-bp spread
budget apply to both arms. Entry/trim trigger age is capped at one 15-minute
candle; permission expires at the regular close. No market fallback from a
blocked bounded attempt. These budgets are fixed before outcomes.

Original source-event and receipt times, completed candles, latches and source
byte hashes are retained. Unknown, stale, inconsistent and thin-venue evidence
is not synthesized. Quote-event identity cannot replenish displayed liquidity.
Both arms make at most one conditional IOC-style attempt per order; partial or
unfilled attempts remain terminal and visible. No queue priority, midpoint or
closing-auction fill claim is made. Incumbent MOC opportunities are retained as
unsupported without auction evidence. Same-observation sale proceeds cannot
fund buys; proceeds are available only to a later observation. Long-only cash
accounting forbids borrowing and uncovered sales.

Report at 10 and 25 bp per side: marked account value and total gain, paired
gain, drawdown loss, cash, exposure, turnover, fees, missing marks, missing or
blocked opportunities, partial fills and unfilled quantities. SPY and QQQ are
fractional buy-and-hold quote references from the same starting marked wealth,
paying the same entry cost. They are reference returns, not liquidity simulations.
Missing starting or ending quotes leave benchmark results unavailable.

An intraday cohort has no meaningful CAGR or annualized Sharpe; neither will be
reported. The first partial session is an engineering/forward diagnostic and
cannot justify adoption. Longer funded evaluation must carry original decisions,
cash and corporate-action evidence across sessions before claiming a robust
gain improvement. The candidate remains experimental and the live policy is
unchanged. Research output stays outside the production market root.
