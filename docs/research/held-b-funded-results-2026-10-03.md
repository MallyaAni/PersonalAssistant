# Learned sale-versus-hold: funded result

The learned retention component improves paired net gains over the incumbent
daily grade-rotation rule in this fixed reconstructed comparison. It also beats
simple B retention over the full period. The advantage is phase-dependent,
uncertainty intervals include zero, and simple retention wins the early era
and reused recent window. This supports further integration testing; it does
not establish a reliable live replacement.

This component chooses whether to retain an existing eligible B holding instead
of rotating it. It does not select new purchases or initiate profit-taking from
held A/A+ stocks. Buying and profit-taking are both still in scope. The deployed
1% executor schedules already selected purchases and sales against the session
open; it is not a position-based 1% profit target. Live policy and UI are unchanged.

## Fixed comparison

2018-02-01..2026-09-30, 2,177 NAV observations/2,176 return sessions,
94 current-vintage stocks plus SPY/QQQ. Three arms, twenty carried reset offsets,
NAV1, zero cash yield, fractional adjusted units, costs of 0/10/25bp per side.
Daily next-open purchases, legacy next-close sales, green-open sale suppression,
presale cash funding and FOMC lifecycle are common to all stock arms. This is
not exact current intraday execution or broker/midpoint fills.

The fixed monthly models use thirteen completed-close features, mature
next-open[t+1]→open[t+11] labels, stock-minus-SPY means and a separate absolute
SPY head. Whole-date purging, 504-day minimum/756-day maximum and the August17
label cutoff were preserved. Actual fits: 104 stock heads and 104 SPY heads
across 141 monthly receipts, first fitted February2018. See the
[protocol](held-b-funded-comparison-plan-2026-10-03.md).

Each paired difference is calculated before taking its median. Values below
are percentage points of cumulative net gain, not relative terminal-wealth
percentages or CAGR differences. Twenty offsets overlap; they are not twenty
independent trials.

| Cost/side | Learned−rule, full | Winning offsets | Learned−rule, recent | Winning offsets | Learned−simple retention, full | Winning offsets |
|---|---:|---:|---:|---:|---:|---:|
|0bp|+189.42|15/20|+1.036|19/20|+372.74|18/20|
|10bp|+159.35|16/20|+1.158|20/20|+257.86|18/20|
|25bp|+195.08|16/20|+1.155|20/20|+130.91|16/20|

At10bp, full learned−rule ranges from −186.61 to +475.34 points.
Split-period paired medians are +10.79points in2018–20 (17/20 winning) and
+9.19points in2021–26 (11/20). Against simple B retention, they are
−30.82points in2018–20 (1/20), +206.93points in2021–26 (19/20), and
−0.706points recently (4/20). The recent32sessions, August17–September30,
have been reused; they are not an untouched test. No regime switch is selected
from these results.

Full-period10bp metrics below are independent medians of twenty stock accounts;
subtracting table medians is not the paired improvement above.

| Method | Net cumulative gain | CAGR | Drawdown loss | Sharpe | Traded notional/NAV/year |
|---|---:|---:|---:|---:|---:|
|Learned B retention|1,910.54%|41.56%|43.25%|1.180|15.25|
|Incumbent daily rule|1,649.73%|39.30%|43.06%|1.133|16.61|
|Simple B retention|1,617.01%|38.99%|44.71%|1.110|10.02|
|QQQ|367.05%|19.54%|35.12%|0.868|0.116|
|SPY|210.62%|14.03%|33.72%|0.784|0.116|

The large ETF gap includes shared reconstructed stock selection. It is not
attested investable alpha or performance of today's live account. Learned
retention slightly worsens median drawdown versus the rule while reducing
normalized traded notional, summing purchases and sales. Absolute fees in initial-NAV units need not fall when
the account grows larger. Median overlapping252-session win rates are85.30%
against SPY and80.42% against QQQ.

## Uncertainty and verification

The [supplemental uncertainty analysis](held-b-uncertainty-addendum-2026-10-03.md)
was locked before reading scores, after fitting/partial journals existed.
Fixed63-session circular blocks,2,000replicates,seed0; all twenty offsets share
the resampled clock. At10bp, phase-average annualized mean log-growth advantage
over the rule is0.717log percentage points, with a95%percentile interval of
−0.598..+2.201. Over simple retention it is1.292points, interval−2.712..+5.433.
All six cost/control intervals include zero. These assumptions do not correct
universe/grade reconstruction, prior research selection or structural change.

VERIFIED source95ee87086ac336ea81e80f6b29a693a62d686602. The prior242native/image
cases and47affected native/image cases pass without skips; Ruff clean. The
independent verifier's21native/image corruption cases and the uncertainty
reader's11native/image cases pass. Its first image invocation failed only because
the private script was mounted at the wrong path; no assertions were altered.

Actual independent evidence verification passes2271source files,96original
parquets, exact preparation/labels/purge,208saved heads and prediction readback
with maximum error0. All186journal archives,180stock accounts,sixETF accounts,
primary scorecards and480paired contrasts reconcile. No model refit or strategy
resimulation was used for verification. Every declared account/window has
zero missing evaluated NAV returns; genuine missing source cells and unavailable
forecasts remain preserved. At10bp, retain12184retention decisions,1960replacement
decisions,6311unavailable destinations,3802unavailable eligibility cases,
225mandatory overrides and5unavailable forecasts across twenty accounts; these
are overlapping decision incidents, not independent opportunities.

Original962,303,748-byte result SHA256:
`d9781a5910cb5d5893ce88e42a8e29ce4507cfc57049e012745b61e0b24017b7`.
Independent proof SHA256:
`d855eea0eb910748f01142a3b44f027079f1665afd9570d95c0d0f1a879a238f`.
Verifier log SHA256:
`031e39787e3be6cb43fa829eeaa13aeaf25474c49fcea1e64f1cac266a0f09bd`.
The [complete compact readback](held-b-funded-results-2026-10-03.json) retains
every account,cost,offset,window,paired contrast and both benchmark scorecards.
The [uncertainty artifact](held-b-uncertainty-results-2026-10-03.json) retains
all six contrasts and its exact code/registration/input/proof hashes.

Private Spark output: `/home/animallya96/scratch/retention-funded-run-20261003-95ee8708/study`.
Proof: `/home/animallya96/scratch/retention-funded-verification-20261003-95ee8708/retention-funded-independent-proof-95ee8708.json`.
The numerical job and verifier had no network/GPU access; model container IDs
and start times remain unchanged. The failed pre-outcome all-NaN estimator fit
at a8bc36aa remains preserved; its targeted correction changed no labels,
hyperparameters, windows or economic thresholds.

UNVERIFIED: historical publication-time grades/universe, future reliability,
full purchase/profit-taking selection, current intraday parity and adoption.
The next atomic boundary is a joint, account-aware selection contract for
new buys and held A/A+ profit-taking, followed by its matched funded comparison.
Execution timing and selection must remain distinct; timing an existing sell
cannot justify creating one. Do not tune this model or pick a favorable
retention/regime variant from the outcomes.
