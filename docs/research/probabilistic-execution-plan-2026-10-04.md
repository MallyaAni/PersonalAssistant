# Probabilistic stock-conditioned execution

Objective: implement and measure probabilistic act-versus-wait decisions from
the existing causal intraday structure and stock volatility forecasts. Separate
the timing decision from the target-position allocator. No production change.

VERIFIED: existing intraday features include prior stock/market context, gap,
session/last-bar returns, prefix range/location, VWAP distance, prefix volatility
and session time. Existing monthly out-of-sample mean and second-moment heads
describe one-decision log immediate-open over later-open advantage. The daily
holding learner cannot observe an evolving15-minute path. The AAOI September28
episode is a retrospective regression fixture, not untouched edge evidence.
UNVERIFIED: calibrated probabilities, reliable intraday advantage or live parity.

Freeze before new calibration or economic outcomes: reuse authenticated saved
intraday OOS means/second moments and raw outcome labels. Do not refit the old
heads, change their features, select a market family/window or refetch history.
New module is pure supplied-input statistics and a decision function. A caller
must authenticate original model/data receipts; array shape alone is not OOS
proof. Preserve explicit target/horizon, basis, observation and maturity clocks.

For each stock/month, collect genuine prior OOS standardized residuals
(outcome-mean)/sqrt(second_moment-mean_squared). Reject inconsistent moments;
never replace missing variance with an invented floor. Use preceding756 actual
exchange-session indices, at least252 distinct mature sessions, and equal total
weight per session across its available completed-bar observations. Outcome
endpoints must be strictly before the month's first session and August17,2026
freeze. Do not use current/future labels or outcomes to admit scoring rows.
No residuals means explicit unavailable evidence, not a default probability.

The weighted empirical residual distribution, shifted/scaled by the current
stock/structure-conditioned mean and variance, supplies estimated positive
waiting-advantage probability and10/50/90% quantiles. These are forecast
estimates, not calibrated confidence guarantees. Measure genuine subsequent
OOS Brier/log loss, reliability counts and interval coverage; retain missing
labels and cold-start opportunities. Both a learned estimate and historical
reference must use identical causal support for comparisons. Do not claim a
holding-profit probability from this different execution target.

Act-versus-wait uses the full forecast distribution and actual funded trade
fraction, side and per-side cost; it does not multiply size by a win percentage
or impose a new percentage dip target. Compute expected log incremental NAV
under the explicitly approximate fixed-quantity price-advantage contract.
Unsupported nonpositive hypothetical wealth is unavailable, not a clipped
sample. Future broker funding/fills remain an accounting-engine responsibility.
Existing closing deadlines and mandatory safety exits remain external and
authoritative. Existing allocation/cash/covered-share constraints remain intact.

Acceptance: correct weighted probabilities/quantiles and probability bounds;
stock-specific variance/path forecasts; strict maturity/freeze and future-prefix
invariance; missing tail labels retained; invalid/forged horizon/variance refused;
no confidence claim; correct buy/sell directions, quantities/costs and unsupported
wealth; explicit default isolation. All functions/tests have purpose comments.
Native and pinned-image tests, then independent saved-artifact evaluation.

Begin with forecast calibration/decision diagnostics on the immutable existing
cohort, all stocks and registered windows. A full funded timing comparison is
a separately registered next step once source/data/support are verified. No
strategy adoption from calibration alone; no repeated old studies, parameter
mining, hindsight AAOI bottom, real orders, paid data, service changes or UI work.
