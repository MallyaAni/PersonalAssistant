# Daily arithmetic bridge — fixed implementation and comparison

Registered after verified saved-forecast diagnostic27c19d5e and its readback,
before fitting the bridge or reading its outcomes. This is one targeted model
calibration and decision-horizon correction on reused data, not a new strategy
family or an untouched test. No parameter, name, period or regime selection.

VERIFIED: original OOS forecasts, inputs and mature monthly receipts; daily
forecast diagnostic38 native/image cases and independent20 native/image cases;
all920 diagnostic cells and141 clocks reconciled. FAILED adoption evidence:
uncalibrated growth sizing loses versus the saved rule with either clock;
A/A+ ten-session absolute/relative MSE exceeds the zero prediction reference.
UNVERIFIED: whether horizon-matched calibration improves compounded net wealth.

The only original inputs are the authenticated source95ee8708 daily panel,
grades, eligibility, saved relative/SPY forecasts and original receipts. Keep
all94 stocks plusSPY/QQQ, original bytes/calendar and price basis. Grades and
membership remain current-vintage reconstruction, not historical publications.
No provider request, new base-model fit, source-history rewrite or live change.

At completed close t, x is the original relative[t,stock]+SPY[t] log forecast.
The new target is one-session ARITHMETIC return adjusted_open[t+2] /
adjusted_open[t+1] −1. This deliberately retargets an existing ten-session model;
it does not claim its raw output was a one-session forecast. Adjust opens once
as daily open * adjusted_close / close. Use no SIP scaling. The first comparison
uses this same next-session official-open proxy, not selected intraday fills.

Fit one pooled A/A+ stock bridge on each month's first supplied exchange session.
Use the preceding756 decision sessions with endpoint STRICTLY BEFORE the earlier
of fit date and2026-08-17, finite original forecast/label, original eligible A/A+
stock status, no benchmarks. Require504 distinct mature forecast-valid decision
dates. Each included date has total weight one, divided equally among its known
stock rows. Fit a single affine monotone shrinkage by constrained least squares:
beta=clip(weightedCov(x,y)/weightedVar(x),0,1), beta=0 for a constant predictor;
alpha=weightedMean(y)−beta*weightedMean(x). No fitted inversion, grid or validation
choice. Record selected dates/names/forecasts/labels/weights, their hashes,
maximum label endpoint, fit/freeze clocks and support. Later inputs/labels may
not change earlier fits or predictions. Missing scoring forecasts remain missing.

The calibrated head is alpha+beta*x. Its required ablation is exactly the same
past-trained weightedMean(y), not a new fitted family. Both heads see identical
causal opportunity masks and training dates; predictions do not require future
labels. No finite forecast before warmup; unavailable support stays explicit.
The common account start is the first completed close with a fitted bridge and
at least one known eligible A/A+ stock; all arms begin NAV1 on that causal date,
execute on the following session and share its availability boundary. It is
chosen from support, never performance. Report pre-start unavailable sessions.
Do not pretend this supplies2016–20 or an untouched recent evaluation.

Refresh targets daily using actual carried shares and cash marked at the previous
completed close. Feed ARITHMETIC means directly into the certified existing
allocator; no half-variance addition. Estimate one-session Ledoit-Wolf covariance
from the preceding252 daily log returns, ending at that close; this remains a
declared local arithmetic-risk approximation. Use Q=Cov+mu*mu' and the same
net-growth quadratic, per-side fee penalty, long-only gross<=1 and operator25%
name limit. These are risk/feasibility controls, not entry/profit percentages.
Only eligible A/A+ may receive additions; mandatory grade/membership exits remain.
Missing held cross-risk or uncertified solutions prevent additions, preserve
covered positions subject to the existing cap and retain mandatory exits.

Freeze desired shares and buy budgets from the previous-close plan. At the next
official open, covered sells may execute but their proceeds cannot fund that
plan's buys. Scale known desired purchases to pre-sale cash including fees;
missing open outcomes remain unfilled/explicit and the plan expires. Do not
invent a missing held NAV mark or end mark. Keep all trade intents, price/clock,
covered quantity, pre-sale funding, fees, carried cash/shares and original source
identity. Maintain fee-inclusive cost basis and realized-sale profit separately:
an exit decision is based on expected holding benefit, not a claim that the
position already made a profit. No same-plan sell and rebuy of a name.

Three fixed arms: calibrated daily risk allocation, past-mean daily risk
allocation, and the unchanged grade-equal TARGET RULE at this same daily refresh
and next-open clock. The last is explicitly a rule component, not exact live
twenty-session cadence/FOMC/intraday reconstruction. Both risk arms use the same
inputs, cash controls and certified solver. Compute only these new daily books,
costs0/10/25bp, zero cash yield, fractional shares; do not rerun any saved study.
SPY andQQQ use opening purchases at the common account start, same per-side cost,
held through the same final close with no terminal liquidation. No phase search.

Primary metrics are compounded net gain and excess gain versus the rule, SPY
andQQQ. Also CAGR, positive drawdown loss, Sharpe, rolling252-session win rate,
gross trading/year, total fees, average exposure, missed/unavailable intentions
and realized/unrealized profit reconciliation. Preserve fixed all/2018–20/
2021–26/reused2026-08-17..09-30 windows, with their actual available anchors and
counts. Every comparison uses identical dates and carried initial state; never
reset accounts merely for a favorable regime. Publish all fixed arms/costs and
all stock contributions, not selected winners. Overlapping windows are not
independent proof. Current-vintage/reused inputs and official-open proxies cannot
justify live promotion by themselves.

Acceptance before real fitting: supplied-array target/basis/date validation,
whole-date purge, strict maturity/freeze, balanced row weights, beta boundaries,
constant/missing inputs, future-prefix invariance and actual sklearn/NumPy runtime.
Daily account tests cover prior-close causality, frozen quantities, original
default allocator parity, presale funding, covered exits, fee-inclusive basis,
missing/unavailable marks, repeated plan expiry and no same-plan rebuy. Pin exact
source before one bridge fit and nine new books; independently verify original
artifacts, calibration receipts and saved funded ledgers/metrics without a
model/account rerun. No dashboard/model services/orders/deployment in this task.
