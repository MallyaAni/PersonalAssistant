# Stock-conditioned execution risk: fixed timing-only extension

User's main objective is replacing the universal 1% entry/exit trigger, not
changing grading or claiming better timing from different allocations. Source
starts at `002f71d8`; original learned models/results remain immutable.
Existing data/model causality is VERIFIED. A timing-only economic edge and
short-horizon risk calibration are UNVERIFIED. This protocol precedes its
new risk fits and timing-only outcomes; the previously observed recent period
is a reused diagnostic, not a newly untouched holdout.

Reuse the original frozen snapshot, original SIP cubes and prepared feature
arrays. The existing feature set conditions on each stock's prior volatility,
gap, realized prefix volatility, range/VWAP/trend and causal market context.
No fundamental/news history is invented. Reuse both fixed walk-forward HGB
and Ridge waiting-mean forecasts; no refit or alternative mean model. Exclude
SPY/QQQ from stock training and preserve all original missing opportunities.

Fit exactly ONE new HGB head for the conditional second moment of the waiting
label `a = log(immediate next open / one-decision-later open)`, target `a*a`.
Its horizon matches the waiting mean; the ten-session return second moment is
explicitly forbidden as a substitute. Same 64 iterations/15 leaves/lr.05/
minimum leaf200/seed0/no early stopping as the frozen HGB, five original
training clocks, minimum504 and maximum756 preceding exchange sessions,
monthly refit. Retain the original conservative ten-session maturity/purge and
August17 holdout cutoff. Risk training requires finite waiting labels only,
independently of missing ten-session return labels. Prediction eligibility depends only on causal input,
not whether its future waiting outcome is present. Record target/config/source,
all input array hashes, fit dates/endpoints/model files and prediction bytes.
No hyperparameter, window, stock, risk multiplier or clock selection afterwards.

For an ordinary covered trade of current marked notional fraction `w`, a
positive `a` favors waiting for a buy, a negative one waiting for a sell.
Approximate the price saving by `s*(mean(a)-.5*E[a*a])`, with s=+1 buy/-1 sell.
Use the second-order expected-log-wealth increment:
`w*c*expected_saving - .5*(w*c)^2*(E[a*a]-mean(a)^2)`;
`c=1+cost` for buys, `1-cost` for sells. Wait only when it is positive.
Zero chooses execution. This is an expected-utility boundary, not another
percentage distance from open. Reject invalid/inconsistent moments; never
invent zero-risk forecasts. Approximation and absent cross-asset covariance
with delayed execution are disclosed; this is not a claim of exact optimal
stopping or of epistemic forecast uncertainty being calibrated.

Keep each declared v5 target plan/reset phase unchanged. Candidate accounts
carry cash/shares continuously, calculate plan quantities from prior-day marks,
and reserve morning cash across fills; same-day sale proceeds cannot fund buys.
Ordinary intents remain same-session intents. At the existing close-window
deadline, closing execution is a venue/lifecycle constraint, not a learned
price forecast. Do not use clock24's overnight waiting label to claim a closing
price decision. Missing quote/proxy/auction, partial funding and missed attempts
remain explicit. Closure/expiry is not counted as a successful broker fill.
The one-step waiting model plus closing deadline is an approximation: its
terminal behavior is judged by funded results rather than assumed optimal.

Evaluate ONLY the two declared waiting means with this common risk head and
unchanged target plans, all20 phases, costs0/10/25bp. Reuse authenticated saved
control/SPY/QQQ curves from the prior completed report; do not rerun unchanged
baselines. Report every candidate phase, compounded gain, drawdown, Sharpe,
fees/turnover, rolling252 win rates, missing/funding/completion counts, stock
contributions and causal prior-only regime diagnostics. Separately report
waiting-risk out-of-sample calibration; do not tune from it. Conditional
current-vintage grades/universe and fractional research accounting remain
limitations. No exact production `/6` parity, midpoint or broker-fill claim.

Acceptance before real fitting: buy/sell symmetry and ties; stock-risk and
order-notional sensitivity without a price-distance constant; invalid moments
fail closed; ten-session variance cannot satisfy the short-horizon contract;
monthly maturity/holdout mutation invariance; prediction rows survive absent
future labels; no borrowed cash/uncovered sale/duplicate fill/same-day funding;
completed-bar causality; first decision locks its execution attempt regardless
of subsequent missing prices. The original result windows are now known;
passing this reused diagnostic cannot alone authorize live promotion.

Live adoption needs a separately reviewed adapter using causal raw prefixes,
matching model receipt/horizon, finite completion time and actual quotes AFTER
inference completion. Neither source code nor historical next-open proxies
prove a broker fill. Keep this research branch isolated; no orders, dashboard,
production data, paid data or model-service changes.

Primary execution motivation: [Almgren–Lorenz, Adaptive Arrival Price](https://www.cis.upenn.edu/~mkearns/finread/AdaptArrival.pdf)
balances execution cost and waiting volatility. That institutional model is
motivation for the risk trade-off, not evidence that this retail-stock policy
will outperform. Diagram impact NONE: internal existing research boundary.
