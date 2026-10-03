# Held-B comparison: supplemental uncertainty readback

Locked before reading economic scores or curves. The producer's real monthly
fits and partial account journals already exist; this is a supplemental analysis
registration, not a claim that it preceded fitting. The original source,
candidate, labels, controls, costs, windows and 180-account grid do not change.

For each of the three costs, compare learned retention separately with the
incumbent and unconditional B retention. Pair the same twenty reset offsets.
Compute each session's log NAV return difference, then average those differences
across all twenty offsets. Resample the common session index for all offsets
together: twenty overlapping books are not twenty independent experiments.

Use a fixed circular moving-block bootstrap: 63 sessions per block, 2,000
replicates, random seed 0, full registered period only. Draw enough uniformly
sampled block starts to cover the original return count and truncate the last
block to that count. Report the point estimate and 2.5th/97.5th percentile
interval for annualized mean log-return advantage (252-session annualization).
This is a log-growth spread, not percentage points of cumulative portfolio gain,
a probability of beating the market, or an independent stock-opportunity count.
The main report still leads with actual paired net cumulative gains, drawdown,
turnover and both funded benchmark accounts.

Missing or nonpositive NAV refuses this analysis. Keep every cost and both
controls; do not select favorable phases, infer separate trials from phases,
search other block lengths, tune a policy from an interval or repeat scoring.
Use only independently authenticated completed curves; no refitting, account
simulation, provider requests, journal changes or live-policy changes.

The interval assumes the observed dependence and return distribution are
informative under block resampling. Circular joins are artificial. It does not
correct current-vintage universe/grade reconstruction, model selection across
prior research, structural market change or reuse of recent data. This secondary
diagnostic cannot establish investable alpha, future reliability, exact live
parity or adoption. Preserve split-period and reused-recent results separately.
