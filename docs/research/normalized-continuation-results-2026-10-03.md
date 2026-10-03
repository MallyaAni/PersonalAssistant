# Stock-specific nonlinear timing: measured result

A model without the universal1% price gate is implemented and independently
verified. It improves full-period funded gains modestly over that gate, but
does not improve the reused recent window. The evidence does not justify live
replacement. This result also does not establish that1% is optimal.

The candidate uses two fixed gradient-boosting heads, for buys and sells.
It predicts the price advantage of acting now against a frozen learned
remaining-session policy. Training labels are normalized by the stock's prior
volatility and remaining session time; forecasts are converted back to relative
price units before decisions. It uses all21 causal features and monthly
matured, whole-session crossfitted targets. This is one conditional-mean
improvement over an existing continuation policy, not optimal stopping or a
calibrated forecast distribution. Sparse late-clock training remains explicit.
Read the [registered protocol](normalized-continuation-plan-2026-10-03.md).

## Funded comparison

Fixed2018-02-01..2026-09-30,2177sessions,94current-vintage stocks,20carried reset
phases, NAV1, fractional shares, zero cash yield and0/10/25bp per side. Selection,
targets, morning cash budget, covered sells and first-attempt locks are common.
Only the new60candidate accounts were replayed. Existing1% gate, linear model,
first-available and ETF evidence were reused; no providers, old fits or old
accounts were rerun. Future opens are research execution proxies, not fills.

Median full-period account metrics at10bp:

| Method | Total net gain | CAGR | Drawdown loss | Sharpe | One-way turnover |
|---|---:|---:|---:|---:|---:|
| Nonlinear stock-specific |735.77%|27.86%|37.86%|1.069|57.75|
| Current1% gate |723.39%|27.64%|37.15%|1.060|58.57|
| Prior linear timing |746.46%|28.05%|37.54%|1.068|58.12|
| First available |725.58%|27.68%|36.81%|1.069|57.34|
| QQQ |364.83%|19.47%|35.12%|0.865|1.00|
| SPY |209.52%|13.97%|33.72%|0.782|1.00|

These current-vintage reconstructed selection-book returns do not establish
investable historical alpha or exact performance of today's live executor.
The ETF gap includes the shared stock selection, not just the timing model.

Compute each paired phase difference before taking its median. Differences
are percentage points of cumulative net gain, not CAGR or fill-price benefit:

| Cost per side | Nonlinear−gate, full | Winning phases | Nonlinear−gate, recent | Winning phases | Nonlinear−linear, full |
|---|---:|---:|---:|---:|---:|
|0bp|+13.31|13/20|−0.952|6/20|−16.58|
|10bp|+13.16|13/20|−0.949|6/20|−15.64|
|25bp|+13.48|13/20|−0.944|6/20|−14.28|

At10bp, paired nonlinear−gate is+0.821points in2018–2020 and+2.031points in
2021–2026. Nonlinear−first-available is+6.382points full-period,11/20phases.
The recent32sessions,2026-08-17..2026-09-30, have been reused; they are not an
untouched test. Recent nonlinear−linear is effectively zero,10/20phases.
Full-period drawdown worsens slightly, while turnover falls slightly.

Median252-session rolling win rates are49.66% against the gate,47.95% against
linear,51.30% against first-available,77.36% againstSPY and67.52% againstQQQ.
These windows and phase accounts overlap and are not independent trials.
Prior-only SPY trend/volatility diagnostics show median mean daily excess over
the gate of+0.086bp down/quiet,+0.521bp down/volatile,−0.086bp up/quiet and
+0.138bp up/volatile. These descriptive means do not validate regime switching.

Across twenty10bp accounts, retain all17427intents:7581completed,9149expired
partially filled and697expired unfilled. There were16730fills,225missing-held
observation incidents and18unsupported plan sessions. These are aggregated
account counts, not independent stock opportunities. Missing inputs and
unsupported early-close plans remain unavailable; no artificial closing fill.

## Verification and next boundary

VERIFIED evaluated source7575711c1684f7fac48dc5e055d3a16855194cc4:111pinned-image
tests, no skips, Ruff clean;28independent timing and19independent retention
cases included. Image sha256:5c6c560537b3e7c70202edd6dfc872d299e2a268aa302ec23c3f48a3f49d099d.

Independent saved-evidence verification passes all116monthly model receipts,
one fixed observed state per fitted side/month,60new account ledgers,
52282intent rows,50195fills and all saved metrics. It authenticates the reused
180comparison accounts and sixETFcurves through their prior verified receipts.
No refitting, account resimulation or original-model verification was repeated.

FAILED first verifier boundary: comparison metadata was dropped when converting
original reference accounts into curves. Production scores retained counts and
stock attribution. The verifier now retains the same metadata for gate, linear
and first-available; ETFs preserve its absence. Strict equality/tolerance did
not change. Independent20synthetic corruption cases pass. The failed log and
first verifier bytes are preserved alongside the corrected proof.

Report SHA256:f11a413568e7d4f9b78633d842299426681e569c7d482bbcde5f275af5109646.
Verifier SHA256:72863ceae736f4099723864d4cf6d6ed149e66a79cb231925387e2fe92e8a3b2.
Corrected log SHA256:aa1a3d2ad2dbd2fbedc0bd686f5d23f97ee0364c73769ffcdc7517ae03111d5c.
Private Spark output: `normalized-continuation-results-20261003-7575711c`;
proof in `sequential-execution-supervision-20261002/normalized-independent-finalization-20261003.json`.
The [compact evidence](normalized-continuation-results-2026-10-03.json)
preserves all costs, windows, paired ranges, benchmark metrics and denominators.

UNVERIFIED: future reliability, actual live-intent advantage, broker/midpoint
fills, early-close execution parity and adoption. Live policy and UI remain
unchanged. Timing an existing sell cannot answer whether it should be sold.
The next separate deliverable is the preregistered mature daily stock-relative
forecast for the [held-B retention planner](learned-retention-plan-2026-10-03.md),
followed by a matched account-aware rotation/reset comparison. Old timing
curves cannot serve as controls for that selection change. No tuning of this
timing model from these results is authorized by this report.
