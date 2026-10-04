# Conditional stock-risk evidence

VERIFIED optional consumer source `d8c69b36c35814c7851f22cabbe1a807563ddc7f`:
239 native tests42.28s and239 pinned-image tests16.05s, neither skips;
27 independent formula/proper-score synthetic checks. The20 new cases cover
stock-specific dispersion with conserved mean, exact identity scaling, true
total-loss mass, unknown/zero context, numeric underflow/overflow refusal,
actual saved-head admission/provenance, immutable copies, future feature and
current-label invariance. Original acceptance assertions remain unchanged;
the shared synthetic factory's default is unchanged.

One fixed saved-data correction and separate artifact verification, network-none/
1CPU/2GB. All2375 source files and16 original input/baseline artifacts authenticated
before/after.204638 requested cases across94 stocks/2177 sessions,415 groups;
147476 common mature scored cases. Exactly the same availability/denominators
as the original report: no additional volatility refusals on these actual bytes.
All missing/immature cases remain. Baseline model/reference scores were read
unchanged from authenticated saved rows, not regenerated or fitted.

The transformation normalizes each original dated gross error by its own stock
volatility and rescales it to current volatility. It retains the shared dates,
probabilities and each stock's original expected arithmetic return; a wider
range cannot invent an expected gain. It neither grants trading permission nor
changes entry thresholds, grade exits, account logic or the active study.

Nominal80% interval coverage at0bp; cost transformation is monotone, so coverage
is identical at10/25bp on the same cases. These are price-component forecasts,
not broker fills, funded gains or guarantees for future stocks/sessions.

| Group | Cases | Original coverage | Corrected coverage | Original mean width | Corrected mean width |
|---|---:|---:|---:|---:|---:|
| All | 147476 | 77.49% | 80.02% | 6.61% | 7.70% |
| High market volatility | 46655 | 70.22% | 81.32% | 6.32% | 8.87% |
| Middle market volatility | 53568 | 78.90% | 79.59% | 6.66% | 7.37% |
| Low market volatility | 47253 | 83.09% | 79.22% | 6.83% | 6.91% |
| AAOI | 1905 | 75.38% | 79.90% | 12.12% | 15.15% |
| COHR | 1905 | 75.17% | 78.22% | 7.90% | 9.46% |
| Reused recent window | 2670 | 76.40% | 84.98% | 7.86% | 10.00% |

VERIFIED conditional coverage improvement: the high-volatility undercoverage
largely disappears, with current stock context and no fitted multiplier. The
recent reused window is now wider than needed for nominal80% coverage; do not
claim universal calibration or select a regime-specific exception from these
results. More coverage alone is not sufficient because excessive width costs
sharpness. Proper scores retain that penalty.

| Group,0bp | Corrected Brier | Original Brier | Past-only Brier | Corrected CRPS | Original CRPS | Past-only CRPS |
|---|---:|---:|---:|---:|---:|---:|
| All | .258357 | .260022 | .249803 | .016881 | .016884 | .016573 |
| High market volatility | .262542 | .268787 | .249721 | .018762 | .018895 | .018371 |
| Reused recent | .253288 | .256944 | .250377 | .019239 | .019083 | .018918 |

FAILED confidence advantage remains: corrected Brier still trails the past-only
reference, and aggregate CRPS improvement versus the original is very small.
Recent CRPS is worse. Expected-return conditioning still needs evidence; the
volatility correction is not a new price-prediction edge or profit proof.

NEXT required deliverable is a fixed funded sizing/holding policy integration on
the reviewed physical-accounting path, keeping this uncertainty explicit. Use
the existing jointly certified growth optimizer and corrected scenario reader;
actual cash, whole shares, fees, corporate actions, missing held risk, grade/
safety exits and no fabricated sale funding. Compare cumulative gain against
the unchanged rule and BOTH SPY/QQQ, with fixed costs and starts. Do not wait
passively for the active300-book timing study or repeat its completed controls.
Confidence/mean calibration is a subsequent targeted mechanism if necessary;
proper-score improvements must not replace the primary funded-gain objective.

The original timing study remains sourceb5894a74, unmodified. Five first-start
0bp books have completed; their reported full gains are rule856.42%, boosting
827.57%, ridge833.99%, SPY190.50%, QQQ350.63%. These are provisional study outputs
on current-vintage grades/universe and conditional raw-share proxies, with
unspendable dividend receivables included in wealth. They are not independently
verified completion of all300 books, paid-cost evidence, pristine historical
live grades or adoption evidence. Preserve the remaining starts/costs/benchmarks.

UNVERIFIED: funded benefit of corrected risk, a complete entry/exit replacement,
live/account parity and deployment. No live policy changed in this checkpoint.
Diagram impact NONE: optional numeric research inside the existing risk boundary.

Evidence root on Spark:
`/home/animallya96/scratch/holding-volatility-20261004-d8c69b36/proof/`.

- ReportSHA847b4c3a39d880cadbffa853b5a5b1b90b4696b6a879aaf9683b8d7f4b9e0aeb.
- CasesSHAe2878652fd2029b72a0d18ddcb377faab5a506ae297b6a6b2d0c3209b51ee540.
- VerificationSHA4b72dde4a875fe68bcf4b3056c582c22f0b89753d797ca6f29b2ac15b09883a3.
- TestsSHA c3a173abdc7bae486918f75e110edda35cdd0b9c6f6098acc7b6224304ac7752.
- Full source manifestSHA d04d0a4e23ab935ca01c78b5441b53654e7634c072d21339d2995916b4e37890.
- Diagnostic helperSHA6ba949bb98c9db32447f2735906c1c3a8df13a206e6e44a8f1c4d2e001c6c873.
- Separate verifierSHA50e9860042bef5113ffe4520bb368df3f84cde53ad70f930e016b206755ba39e.

The independent verifier checks every candidate's direct-power formula against
the exact reconstructed archived-producer sample, then applies the unchanged
independent CRPS/empirical-quantile/PIT oracle to those exact floats. Means,
availability, source receipts, untouched baseline values, common aggregates
and reliability counts are checked separately. A preliminary synthetic proof
incorrectly required bit-exact quantile membership across equivalent floating
algorithms; corrected only the proof composition, adding the independent
scenario comparison and saved receipt check. No acceptance assertion, model,
active collector/source, baseline or completed saved diagnostic changed.

Exact commands, mounts and hashes:
`/tmp/codex-holding-volatility-execution-receipt-20261004.json` locally and
`proof/execution-receipt.json` remotely. Do not rerun this completed diagnostic.
