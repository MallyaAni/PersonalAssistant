# Forward paper and RL research

## Actual evidence

Read-only audit of the live market store on September 14: 22 immutable research
observations, one distinct trading session, two policy groups. Nineteen records
have no execution quotes; three carry IEX. None has a full point-in-time feature
snapshot. These are correlated observations, not 22 independent episodes or
93 independent market histories. The new state snapshot is prospective only.

The existing universe contains 531 stock members, but the AI/software book admits
93. Corning is present in the universe but excluded by the book's theme filter.
SNDK's 19:00 UTC live record retained its nightly value rank (0.949) while its
technical rank moved to 0.9677. The plain intraday value reader produced a value
rank, but it is intentionally rejected for an expectations-blended nightly rule.
Therefore the current board is not a comprehensive current-price valuation screen.
The reported GLW daily loss was not independently verified by this audit.

## First RL experiment

User clarified that maximum cumulative gain, not Sharpe, is the objective.
`growth_objective` therefore uses incremental log net NAV: summing rewards gives
log(final NAV / initial NAV), exactly the terminal-wealth ordering for a fixed
initial balance. Cash gives zero before interest; transaction costs already in
NAV reduce the reward once. Drawdown and Sharpe are diagnostics and existing
exposure/position/cash limits are constraints. Deposits/withdrawals require
flow-adjusted NAV and cannot be counted as investment gains.

Existing source research includes `market_allocation_rl` (Sharpe-shaped window
reward), `market_offline_rl` (a contextual-bandit rather than sequential account
simulator), `market_intraday_rl`, `market_execution_rl`, `market_interactions`
and `market_xsect_net`. Their recorded results are not fresh measurements in
this task. Their objectives, universe, execution model and turnover assumptions
differ from this requested account objective. They are baselines to reproduce,
not grounds to dismiss growth-oriented learning. Do not silently replace their
reward and reuse the old result headings as if those experiments had been rerun.

Research allocation and USD exposure using the existing analyst inputs, holdings,
cash, elapsed holding time, market regime, event state and execution availability.
Use bounded allocation changes; keep action gates outside the learner. Optimize
net log equity growth under the adopted exposure, position and cash constraints.
Do not add a volatility penalty that silently changes the user's objective.
Do not optimize hindsight-perfect entries/exits or use future highs as fill prices.

Chronological train/validation/test blocks must isolate overlapping holding-period
labels. Hold out whole market regimes and evaluate the proposed post-guidance
period separately without pretending a short regime has enough independent FOMC
meetings. Compare cash, SPY, the adopted desk and a simple supervised allocation
baseline under identical starting capital, delayed fills, costs and action rules.
Repeat across seeds and higher-cost/missing-data scenarios before any paper
challenger earns consideration for adoption. No live exploration or auto-promotion.

The paper ledger uses $100,000 synthetic starting capital, whole shares, delayed
quotes, displayed-size caps, bid/ask plus 10 bp extra per side. It preserves the
old Alpaca account. It is an engineering experiment, not a brokerage replica:
settlement, queue position, market impact and partial execution latency need more
validation. Overnight marks are withheld without complete corporate-action
coverage. Unknown dividend payment dates accrue receivables rather than cash.
SIP unavailability blocks buy eligibility just as it does on the dashboard.

## Research basis

[FinRL](https://arxiv.org/abs/2011.09607) provides a useful framework for market
environments with transaction costs, liquidity and risk constraints; its existence
does not establish that an RL strategy will beat this desk.
[ICML 2024](https://proceedings.mlr.press/v235/wang24aj.html) discusses offline-RL
overestimation under distribution shift. That is directly relevant to trying
actions or regimes poorly represented in a short recommendation log.

Status: data capture and readiness audit implemented; training and superiority
unverified. Complete broad-universe and current-price valuation research before
choosing the state and reward contract for a training run.
