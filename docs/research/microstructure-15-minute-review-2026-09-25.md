# Microstructure ideas at a 15-minute decision cadence

Reviewed September 25, 2026. This answers whether HFT ideas can help a slower
long-only stock/index/cash system. It is research, not an implemented strategy,
a new fitted experiment or a claim that 15 minutes is the optimal horizon.
Decision cadence and holding duration are separate: assessing a completed bar
does not require trading every bar or exiting after 15 minutes.

## Two current primary papers

**TradeFM — Kawawa-Beaudan et al., February 27, 2026, v1.**
[Versioned full text](https://arxiv.org/html/2602.23784v1).
The model learns event-level trade flow on proprietary US equity data from
February 2024–September 2025. January–September 2025 is a temporal holdout;
Japan/China January 2025 supplies separate geographic tests. Inputs include
event/action types, initiating side and price depth, not just OHLCV. A simulator
maintains the synthetic book from partial event information.

Its statement that 1,024 events span roughly 15–60 minutes for medium-liquidity
assets is a **simulation duration**, not a profitable trading horizon (§9.1).
Reported fidelity is mixed: Table 3's spread Wasserstein distance is 0.400 for
TradeFM versus 0.302 for Hawkes and 0.375 for the zero-intelligence control.
The paper does not demonstrate net portfolio returns, reduced drawdown or
SPY/QQQ outperformance. RL execution applications are prospective (§D.6), and
the conclusion leaves downstream usefulness for future validation.

Transferable ideas: scale-aware normalization, separating event time from
wall-clock time, and separate chronological/cross-asset tests. The event data
needed to reproduce this approach cannot be reconstructed from our bar cache.
Synthetic simulations are not additional independent historical observations.

**Mesfin, Structural Limits of OHLCV-Based Intraday Momentum Signals in MNQ
Futures, May 5 / revised September 15, 2026, v3.**
[Versioned primary PDF](https://arxiv.org/pdf/2605.04004v3).
The study reports 947 sessions, December 2021–August 2025, with expanding
training windows and main test folds in 2023, 2024 and partial 2025. Signals use
bar-close information and next-bar-open entries with a fixed two-MNQ-point
round-trip cost. None of fourteen signal families passes all the author's
gates; this does not establish that all intraday trading fails.

The London positive control uses 15-minute bars and a maximum 60-minute hold:
N=247, reported mean net +4.09 points, T=4.30. One additional 15-minute entry
delay changes those figures to −2.91 points and T=−2.78 (pp.10–11, 16–17).
That is evidence of timing sensitivity in this study, not an effect size to
import into equities. The RTH positive control discloses 53+ combinations,
overlapping GMM training/test data and forward-looking ATR normalization.
Both controls assume exact-stop fills, lack fold-matched out-of-sample passive
controls, and do not establish dependence-adjusted significance or funded
wealth/drawdown superiority. Abstract/table significance thresholds and the
ORB year-stability narrative also disagree internally.

Transferable lesson: stress entry delay, costs, causal preprocessing and
regime stability independently. Futures/session-specific nominal costs do not
qualify cash-equity execution. Neither paper establishes the best 15/30/60-minute
cadence. Both are preprints; peer review and independent replication were not
established. The claims above are checked against retained primary artifacts,
not independently replicated empirical results.

## Fit to the current implementation

Source at `d12cfbec9ffad8f980306bc3706329351e2c4017` uses completed 15-minute
bars for intraday technical evidence, while `/3` is a once-per-session policy
with 20-session resets and specified between-reset actions. That is not an
arbitrary 15-minute trading engine or a general price-stop system. Scheduler
cadence and deployment remain separate runtime questions.

Qualified OHLCV can support coarse range, volume, volatility and activity
features using only completed prefixes and earlier comparable sessions.
Time-of-day normalization matters: ordinary opening volume is not automatically
unusual activity. These remain proxies, not true order-flow imbalance, trade
aggressor classifications, transaction VWAP, quote spreads or queue position.
Those require suitably timestamped trade/quote/book data and execution evidence.
The display collector retains only a latest snapshot; it is not a historical
quote archive. Monitoring overnight/premarket/postmarket prices is a separate
coverage requirement, not permission to apply an unvalidated RTH signal there.

The older [ML review](trading-ml-path-2026-09-22.md) likewise separates
prediction from execution. Existing LightGBM expectations and experimental
neural/RL pilots do not establish that more complex models improve this desk.
The current allocation gate loses its matched comparator in 10/14 examined
folds at 10 bp and 11/14 at 25 bp. No top-tier edge is established.

## One prospective hypothesis, not a launched experiment

Keep stock selection and the holding policy fixed, and separately register
one completed-bar entry veto/delay using causally normalized range and volume.
This tests whether avoiding a narrowly defined entry condition helps after
costs, rather than fitting a new portfolio model. It can lose by missing rallies.
Related timing/volume features were already examined in the September 20 pilot;
this is an attribution hypothesis, not a claim of an unexplored feature class.

Before outcomes, specify the exact condition, permitted delay, maximum waiting,
unavailable-data behavior, full opportunity denominator, session coverage,
cost stresses and review window. An intraday-capable funded ledger must use
subsequent executable fills with explicit latency, spread/slippage and missing-
fill treatment; the existing daily next-open ledger does not validate this.
Keep matched incumbent, SPY and QQQ accounts, plus predeclared cash/exposure
controls. Report net compounding, maximum drawdown, time under water, tail losses,
turnover, fees, exposure, false defensive switches and missed rallies.

Use chronological outer tests and training-only inner selection if anything is
fitted; purge actual overlapping outcome intervals and fix any embargo before
scoring. Report predeclared regimes without stitching them into a fictitious
tradable return path. The user's unacceptable drawdown is still unanswered;
no risk limit, future drawdown guarantee or winning cadence is assumed.

Do not modify the frozen September 22 reclaim comparison (20-session primary /
5-session secondary labels), its separate six-symbol single-source diagnostic,
the 10-session stock-relative ML specification, or the frozen rank blend.
Examined history cannot become a fresh holdout through more folds. This note
does not authorize threshold/horizon searches, new provider calls, fitting,
historical reruns, strategy promotion or order placement.

Evidence: `/private/tmp/anios-2026-microstructure.pOTlBB/RECEIPT.md`, SHA256
`9778a11d2c8758e75829ee8dcecebbc422889b1f4c5173d28bb8c511d4eaf43c`.
Primary HTML/PDF artifacts and their hashes are retained there. Independent
read-only review confirmed the quoted values and frozen-study boundaries.

## Execution and acquisition boundaries clarified after journal inspection

At source `c42ace690ac960750acaa5c70e12981a9ea8d673`, the ordinary `/3`
simulation constructs quantity using the decision close, assigns buys
`opens[t + 1]`, and settles that order before recording the next closing NAV
(`agents/trading/desk/simulate.py`). Therefore a signal from the completed
09:30–09:45 ET regular-session bar cannot veto a buy already filled at 09:30.
An entry challenger using that bar must explicitly defer the initial order.
Its permissible fill must follow actual bar availability plus declared latency;
15-minute OHLCV alone does not prove an executable quote or broker fill there.

Include an **unconditional-delay control** with the same entry clock, costs,
missing-fill rules and opportunity set. This separates the value of the range/
volume condition from the effect of waiting. The conditional and unconditional
accounts must each propagate their own cash, remaining order intent, holdings,
reset and event state. Deleting fills from the incumbent journal is not an
equivalent account simulation: one skipped buy can change later funding and
eligible actions. This does not prescribe a new threshold or launch a test.

The six independently verified frozen daily journals now define an exact
baseline-revaluation request: 77 symbols, 19,316 symbol/session cells and 426
sparse holding ranges, January 7, 2020–September 18, 2026. The first common
closing mark, January 6, is cash-only. Full regular-session 15-minute acquisition
is 500,440 bars including 12 early-close sessions. The saved scope is
`/private/tmp/anios-intraday-request-scope.9kVcT9/required-scope.json`, SHA256
`7f55f84e3bf97e54ad0087302754948c90571384be052ea643903f7cf28a1afc`.

That is **not a sufficient challenger dataset**. A condition using historical
same-clock activity additionally needs its causal warm-up, every considered
opportunity (including unfilled/skipped buys), and prices for holdings the new
account would carry outside the incumbent's ranges. Register this larger scope
before observing challenger outcomes. The existing packet still requires feed/
instrument identity, bar-clock definitions, documented compatible adjustment
basis and reconciliation to every original closing NAV. No such price delivery
was acquired or qualified in this inspection. No fit, strategy rerun or new
performance result was produced; the original producer OOM/missing root manifest
and biased historical-universe limits remain unchanged.

**Diagram impact: NONE — research assessment only; no architecture change.**
