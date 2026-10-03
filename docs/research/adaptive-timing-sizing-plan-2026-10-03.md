# Adaptive timing and funded sizing — fixed implementation protocol

Registered after reading the completed timing, retention and cash-selection
diagnostics. This is a new combined component experiment on reused data, not
an untouched holdout or full live-policy reconstruction. No new fitting or
parameter selection is permitted in this experiment.

Objective: replace equal-weight purchase quantities and fixed distance-from-open
execution with stock-conditioned funded growth allocation and the saved
normalized continuation buy/sell forecasts. Optimize carried net wealth, report
CAGR, drawdown loss, Sharpe, fees, gross traded notional per year, rolling wins
and excess gain versus SPY/QQQ. No claimed broker/midpoint fills.

At each existing 20-session reset, use only the preceding completed close and
the already cross-fitted ten-session relative-return plus SPY log forecasts.
Covariance is Ledoit-Wolf on exactly the preceding 252 daily log returns,
ending at that close, multiplied by ten. Arithmetic mean approximation is log
mean plus half that covariance diagonal; second moment is covariance plus the
outer product of these means. These are local approximations, not calibrated
probability/confidence forecasts. The ten-session forecast versus 20-session
reset mismatch remains explicit.

Minimize half the target second-moment quadratic minus expected arithmetic
return plus per-side proportional transaction cost times absolute weight
change. Long-only, total weight at most one, maximum requested target per name
25%, cash permitted. Purchases plus their fees must fit cash held before any
sales; proposed sales cannot fund buys. Protected held positions are fixed
inside the optimization, including their covariance cross-term. Only known,
eligible A/A+ stocks may be increased; mandatory grade/membership exits remain
zero. Missing forecast/history on an otherwise eligible held name preserves
its weight up to the existing hold cap; missing held valuation or an
uncertified solve returns an explicitly unavailable incumbent-safe plan.
No future fill/open/close is visible to allocation. Desired quantities are
frozen once and go through the existing funded fill, first-attempt lock,
missing-outcome and expiration accounting unchanged.

Four arms: saved equal-weight/1% gate, saved equal-weight/adaptive timing,
new growth-sizing/1% gate, new growth-sizing/adaptive timing. Reuse the two
authenticated saved controls and ETF accounts; compute only 120 new accounts
(two arms × 0/10/25bp × all twenty phases). Same original prepared SIP evidence,
daily panel, grades, point-in-time membership, calendar and zero cash yield.
Period 2018-02-01 through 2026-09-30, common prior-close NAV anchor; report full,
2018–20, 2021–26 and the explicitly reused recent window. Preserve all missing
opportunities and unsupported early-close sessions. Do not refit, refetch,
repeat old accounts, mine windows/thresholds or promote from a favorable arm.

Acceptance: default replay remains exactly unchanged; differing risk and
correlation change quantities under otherwise equal forecasts; cash and
covered sells reconcile including fees; mandatory/protected/missing cases are
explicit; optimizer rejects infeasible/uncertified output; future-prefix changes
cannot alter earlier targets/actions; actual funded traces retain quantities,
attempts and expirations. Authenticate source and original model/input bytes,
verify new saved ledgers and metrics independently. Production policy and
dashboard are unchanged until a separately reviewed promotion is justified.
