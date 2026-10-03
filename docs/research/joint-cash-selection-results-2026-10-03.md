# Joint buy and cash-exit selection: verified result

Both decision sides are implemented. The joint overlay protects the reused
recent period and lowers drawdowns, but loses paired full-period cumulative
gain and increases turnover. It does not justify replacing live rules.
The next study isolates purchase vetoes, covered cash exits and the shared
reset-quantity correction, using the same saved forecasts without refitting.

The [registered contract](joint-cash-selection-plan-2026-10-03.md) was committed
at01ccf9d9 before new source or account results. Eligible ordinary A/A+ purchases
require the causal absolute mean log-return to exceed modeled buying cost.
Held A/A+ stocks receive covered cash-exit proposals when that mean prefers
zero-yield cash after selling cost. Missing forecasts preserve incumbent behavior;
mandatory risk/event decisions retain priority. Cost basis is not available, so
these are forecast cash exits, not assertions that a sale realizes a profit.

## Fixed comparison

Sixty new carried accounts:0/10/25bp per side, twenty reset offsets0..19,
2018-02-01..2026-09-30, NAV1, zero cash yield and fractional adjusted units.
All sixty prior learned-B, sixty incumbent and sixty simple-B accounts, and six
SPY/QQQ accounts were authenticated and reused. No model refits or prior-account
replays. Common2,177 NAV marks/2,176 returns; no missing evaluated NAV returns.
Daily next-open buys and legacy next-close sales differ from today's intraday
executor. Universe/grades are current-vintage reconstructions; recent32sessions
August17..September30 have already been examined. This is component evidence,
not historical live reconstruction, broker fills or an untouched test.

Values below are median matched differences in cumulative net gain, in
percentage points. Compute each same-cost/phase difference first, then its
median. Overlapping phases are not twenty independent experiments.

| Cost/side | Joint−learned B, full | Winning phases | Joint−learned B, recent | Winning phases | Joint−incumbent, full | Winning phases |
|---|---:|---:|---:|---:|---:|---:|
|0bp|−280.29|7/20|+2.967|18/20|−31.12|9/20|
|10bp|−183.38|5/20|+2.519|18/20|−113.10|9/20|
|25bp|−493.96|2/20|+0.942|14/20|−279.30|3/20|

At10bp, joint−learned B is+3.79points in2018–20(11/20 wins),
−112.19points in2021–26(5/20), and ranges−1,130.38..+929.95points
over the full period. Joint−incumbent recently is+3.552points(20/20).
Joint−simple B is−67.16points full(9/20),−24.19points in2018–20(2/20),
+66.12points in2021–26(14/20), and+1.309points recently(16/20).
No regime switch or threshold was selected from these outcomes.

Full10bp table entries are independent phase medians, not paired effects:

| Method | Net cumulative gain | CAGR | Drawdown loss | Sharpe | Traded notional/NAV/year |
|---|---:|---:|---:|---:|---:|
|Joint buy/cash exit|1,689.71%|39.66%|37.04%|1.154|23.57|
|Learned B retention|1,910.54%|41.56%|43.25%|1.180|15.25|
|Incumbent daily rule|1,649.73%|39.30%|43.06%|1.133|16.61|
|Simple B retention|1,617.01%|38.99%|44.71%|1.110|10.02|
|QQQ|367.05%|19.54%|35.12%|0.868|0.116|
|SPY|210.62%|14.03%|33.72%|0.784|0.116|

Joint table median exceeds the incumbent table median, yet its median matched
effect is negative: phase pairing matters. The large ETF gap is shared with
reconstructed stock selection and is not attested live alpha. Joint median
fees are0.7637initial-NAV units versus0.6341learned B. Overlapping252-session
win rates are81.06%against SPY and71.74%against QQQ, versus85.30%/80.42%
for learned B. The combined overlay cannot identify which decision side caused
the gain loss or churn; attribution is required.

Fixed63-session circular blocks,2,000 replicates,seed0 and the same resampled
clock across all phases give joint−learned B annualized mean log-growth spreads
of−0.410/−1.327/−3.401percentage points at0/10/25bp. Corresponding95%percentile
intervals are[−7.200,+5.799]/[−7.892,+4.786]/[−10.569,+2.964]. All nine
cost/control intervals include zero. These descriptive intervals do not repair
reconstructed eligibility, prior research selection or structural change.

## Verification and preserved failures

VERIFIED sourcee8505b221bdd4cd21f2c0a3b13e52d720ab93bea:192pinned-image
cases pass, no skips(177repository,9unchanged independent,6parent-source journal
parity). Independent source review found and corrected a favorable-forecast tiny
reset trim disappearing at the trade floor and refused unsupported funding/event
combinations before outcomes. Five pre-existing empty-slice warnings remain.

The independent saved-artifact proof authenticates2,282source files, frozen
forecasts/controls, all60new ledgers and causal verdicts,720matched contrasts,
cash, covered shares, fees, price units and complete NAV metrics. Verification
does not fit or replay a strategy. Its initial run failed on an overbroad funding
check: a sell-only FOMC reduction declared a potential sale-inclusive budget,
but bought nothing. A narrowly corrected check constrains actual gross purchases
including fees to original cash; all original23corruption assertions remain and
three additional boundary cases pass. Corrected26native/image tests and actual
artifact verification PASS. The failed proof log remains preserved.

The compact reader's actual-metric schema was corrected before readback;
six native/image tests and independent review pass. It uses `annual` for CAGR
and positive drawdown loss, retains every account/contrast and applies paired
arithmetic. Source/result are immutable; producer, verifier and reader exited0.

Original315,551,130-byte result SHA256:
`8bb4cb5d9ca2ac797395be88f69d693d9f9ee4df592ce419dd4d738b246eebb7`.
Independent proof SHA256:
`cc31794054ab02b90c9df75865643a092352cb00a482f92e3f1b3ff6978803f3`.
Complete [compact artifact](joint-cash-selection-results-2026-10-03.json) SHA256:
`1c83155fdf5c90a7b2922899757dfbefd25247caf49c7f6fd6e526004fad818a`.
Verifier source SHA256:
`ed9d496c1cea95e4020f076328f845cab1965b2d19b2bc50171cdd50c9580f81`.
Actual proof log SHA256:
`a4b794b3714d149bd7093c2ce44803700250ccc7cd9def0f264f25f365b7c391`.

Private Spark output:/home/animallya96/scratch/cash-selection-funded-run-20261003-e8505b22/study.
Verification:/home/animallya96/scratch/cash-selection-verification-20261003-e8505b22.
CPU-only, network disabled, original inputs/source read-only. Model container
IDs/start times remain unchanged. No broker-account/order writes, live source
or UI changes. Research ledgers were written to private output only.

FAILED economic objective: consistent improvement in paired full-period net
gain with low unnecessary turnover. UNVERIFIED: full live-policy replacement,
combined causal intraday execution, profitable exits relative to entry basis,
future reliability and historical publication-time eligibility. Both buying and
profit-taking remain the objective; this result supplies a precise next test,
not grounds for promotion or abandonment.
