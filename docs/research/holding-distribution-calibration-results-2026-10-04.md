# Holding-distribution evidence

VERIFIED optional consumer source `b04185c5b5d37333ec7072f94618000e32d61e9e`:
219 tests on the exact archived tree in pinned image5c6c5605 (12.45s, no skips),
219 native tests across two runs (191/31.78s +28/2.69s, no skips). Weighted CRPS
against pairwise arithmetic, costs/ties/total loss, domain refusal, empirical
quantiles/PIT, actual saved-head reader, preserved unavailable requests and
early-close/delayed/unknown endpoint handling.72 separate synthetic checks of
the independent equal-weight score verifier also pass. No live caller changed.

One frozen saved-data diagnostic; a separate read-only verification recomputed
proper scores and group means/reliability counts from original numeric arrays.
204638 declared stock/session cases,94 stocks,2177 sessions2018-02-01..2026-09-30;
415 reporting groups. Original risk/parent/bridge/prepared/price bytes and the
2373-file consumer tree authenticated before/after. No fit, estimator restore,
numeric inference, account replay, threshold change or selected stock/window.

Prediction availability is147654 available/56984 unavailable. Outcomes are
178722 known/25728 past missing/188 immature. Only147476 cases have both an
available forecast and a known outcome; model/reference use exactly these same
cases at every cost. The reused recent window has3008 requested/2670 scored
cases; it is not pristine holdout. Missing cases remain in the saved evidence.

Lower Brier and CRPS are better. CRPS uses one-session arithmetic-return units;
coverage is measured against the declared80% empirical interval.

| Window | Per-side cost | Model Brier | Past-only Brier | Model CRPS | Past-only CRPS | Model coverage | Past-only coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| All | 0bp | .260022 | .249803 | .016884 | .016573 | 77.49% | 77.62% |
| All | 10bp | .259978 | .250063 | .016850 | .016540 | 77.49% | 77.62% |
| All | 25bp | .252899 | .244089 | .016800 | .016491 | 77.49% | 77.62% |
| Reused recent | 0bp | .256944 | .250377 | .019083 | .018918 | 76.40% | 75.96% |
| Reused recent | 10bp | .255364 | .248515 | .019044 | .018880 | 76.40% | 75.96% |
| Reused recent | 25bp | .249270 | .242925 | .018987 | .018824 | 76.40% | 75.96% |

The reference is each stock's strictly earlier empirical realized returns on
the same bank dates, without conditioning on today's model forecast. Full
stock, split-period, original-support and causal stock/market-volatility groups
and ten reliability bins are in the report. No outcome-selected regime switch.

FAILED confidence advantage: the conditioned mean head worsens proper scores
versus this simple reference on the declared aggregate; probabilities far from
50% are frequently unsupported by realized frequencies. Original grade-qualified
cases are also worse (.260498 versus .249187 Brier at0bp); this is not explained
solely by expanding coverage to ungraded names. It does not prove no funded
policy could benefit from the forecasts, but cannot justify interpreting these
probabilities as reliable confidence for live sizing.

FAILED conditional interval calibration: model coverage is70.22% in high market
volatility,78.90% in middle and83.09% in low; the unconditioned reference shows
the same pattern (71.07%/79.02%/82.51%). Current volatility features influence the
mean head but the error bank does not scale each historical error to current
stock volatility. High-stock-volatility coverage is74.74%; AAOI75.38%, COHR75.17%,
STX76.06%, WDC76.27% (each1905 scored cases). This is a concrete risk-distribution
weakness, not a reason to change a dip threshold or pick a favorable regime.

Next bounded hypothesis: use causal per-stock volatility to scale the same dated
joint error scenarios, preserve possible total loss and missing support, and
calibrate confidence only from strictly earlier outcomes. Register the precise
transformation and evaluation contract before its outputs; change one mechanism
at a time. Keep the original saved producer and existing controls immutable.
Then test actual funded sizing/holding through reviewed whole-share/cash/
corporate-action accounting. Proper scores alone cannot establish compounded
gain, advantage over the live rule/SPY/QQQ, or adoption.

UNVERIFIED: improved confidence after that change, funded gain advantage,
live/account parity and deployment. The300-account original timing study remains
running under sourceb5894a74, unmodified. Partial first-start0bp rule and boosting
books exist but are not the complete fixed-cost/start/benchmark comparison.
No production deployment or live rule replacement occurred in this checkpoint.

Evidence root on Spark:
`/home/animallya96/scratch/holding-calibration-20261004-b04185c5/proof/`.

- `diagnostic/report.json`: SHA256 db8d0d807598683f6682bee4ec6785e7623f4689cf4436bf8cca428520cfe0e7.
- `diagnostic/cases.jsonl.gz`: SHA256 f6a94a4c4eab299e44efac5cd19432314bf8ab5e893d4ce84d2eff503ca262f0.
- `diagnostic/verification.json`: SHA256 6949cb5741de620f9ac4572278b5a5f31b7a52461731401ff1fc19655db7a4c0.
- Tests: SHA256 a17fecf734c3b9d12ca7ebf53280e715b44b0351e1435ded56cb40865e10ae37.
- Whole source manifest: SHA256 20e6eeae0df89ab90e436a2190341833606fbb7f2e862ce4a4050756963bfc29.
- Fixed diagnostic/proof helper: SHA256 b585633e824c1a8ce0ce2980d2e8f2385414b9c8f80e28a3dcabf140dfc22b9e.

Exact commands/mounts/hashes: local
`/tmp/codex-holding-calibration-execution-receipt-20261004.json` and remote
`proof/execution-receipt.json`. Both phases network-none/1CPU/2GB/source read-only;
source tests2CPU/4GB. Every available case's model/reference CRPS independently
checked by the equal-weight order-statistic identity, quantiles by empirical CDF
brackets, probabilities/PIT/costs by direct counts/arithmetic; aggregate means and
bins recomputed from saved rows. No simulation or forecast regeneration in proof.
