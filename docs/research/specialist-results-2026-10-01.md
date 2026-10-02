# Specialist implementation and fixed results

Implemented on `codex/specialist-contributions-20261001`; evaluated source
`12f14e39197c4b0f151d96d68662efcc86ffd7bc`. No live policy change.
The [frozen protocol](specialist-contributions-2026-10-01.md) defines the
opportunities, units, clock, controls and adoption boundaries.

**VERIFIED:** native joint Chronos-2/TimesFM-3, native Kronos intraday paths,
TTM/Ledoit–Wolf anchored sizing, causal scenario classification, monthly
matured-utility selection, and shared funded comparisons are implemented.
Actual inference ran on CPU: 456 joint forecasts and all 24 fixed timing
cases. No GPU, provider request, service change or order was needed.

**VERIFIED:** all 189 relevant tests passed on `12f14e39` without skips in
20.36 seconds in the isolated Spark runtime, including all eleven timing-account
cases. Actual CLI acceptance, Ruff and diff checks pass.
Independent reviews reproduced and corrected zero covariance, zero-duration
labels, unmatched exposure controls, unverified training histories, rehashed
future contexts, later-price funding leakage and pre-permission execution.
No assertion or forecast-validation requirement was weakened.

## Funded gain and controls

September 3–30, 2026: 19 NAV marks, 18 returns, two fixed reset decisions,
NAV 1, next adjusted opens, zero cash yield. Both cost conventions use the
same funded accounting. The incumbent is the registered grade `/5` with a
ten-session cadence on the fixed twelve-symbol cohort; it is **not** the
full live desk or its intraday execution. Grades and source availability are
reconstructed/assumed, not attested original history.

| Account | Gain, 10 bp | Gain, 25 bp | Drawdown, 10 bp | Mean exposure, 10 bp |
|---|---:|---:|---:|---:|
| Incumbent control | −2.1508% | −2.1894% | 2.8144% | 10.3611% |
| Covariance only | −2.1508% | −2.1894% | 2.8144% | 10.3611% |
| TTM risk sizing | −1.7903% | −1.8224% | 2.3430% | 8.603% |
| TTM exposure-matched incumbent | −1.7903% | −1.8224% | 2.3430% | 8.603% |
| Joint Chronos-2 | 0.0000% | 0.0000% | 0.0000% | 0.0000% |
| Joint TimesFM-3, research only | 0.0000% | 0.0000% | 0.0000% | 0.0000% |
| Joint + risk | 0.0000% | 0.0000% | 0.0000% | 0.0000% |
| Combined selector | −2.1508% | −2.1894% | 2.8144% | 10.3611% |
| Membership equal weight | +3.9302% | +3.5939% | 3.555% | 91.648% |
| SPY | −1.0684% | −1.2167% | 2.423% | 94.710% |
| QQQ | +2.8430% | +2.6891% | 2.157% | 94.737% |

The joint-only gross control, joint-risk gross control and joint-risk
composition control also remain cash at 0%. They are retained in the JSON.
Annualized CAGR/Sharpe are descriptive over eighteen intervals; a twenty-session
rolling win rate has zero windows and remains null. No 2016–20/2021–26 or
other-regime result is fabricated from this slice.

The first reset has no grade-qualified intent. The second has only AAOI at
25%. TTM reduces that weight to 20.8094%, improving gain by 36.05 bp and
reducing drawdown. Its matched control has identical NAV within `2.22e-16`:
this is exposure reduction, **not** a composition edge or benchmark victory.
Its turnover is 0.2141 versus incumbent 0.2572; fees are 0.0002141 versus
0.0002572 NAV units at 10 bp. Both joint methods reject that intent under the
registered positive-excess rule and remain cash. Cash avoids this particular
loss; it demonstrates neither stock-selection alpha nor superior total gain.

All eighteen observable return scenarios are `up_low`. No down/high-volatility
edge can be inferred. The selector correctly retains 100% incumbent: there is
only one matured reset utility row, all zero. This cannot satisfy twenty
observations across three prediction months. Its generic convex fit is tested,
but there is no qualified learned market fit. The fixed evaluator refuses
unverified external utility histories until their funded archive is authenticated.

## Forecast and timing applicability

Each joint model retains all 228 forecasts: 108 mature labels and 120 immature,
none silently omitted. Only eleven grade-qualified paired labels across nine
decision days can be scored, with overlapping ten-session outcomes.

| SPY-relative return error | Independent MSE | Joint MSE |
|---|---:|---:|
| Chronos-2 | 0.00276344 | 0.00296042 |
| TimesFM-3 | 0.00265806 | 0.00383833 |

Joint context did not improve error on this conditional sample. These MSEs
are diagnostics, not funded returns or independent statistical replicates.

The 24 fixed Kronos cases retain six coherent forecasts, sixteen malformed
OHLC refusals with all eight original paths preserved, and two missing TSLA
prefixes. No redraw, candle repair or outcome-selected substitution was used.
The funded timing denominator contains 23 no-intent opportunities and one
AAOI intent. AAOI's paths are malformed, so both the bounded candidate and
causal availability-matched control remain unfilled at 0%. The next-open
control is −2.1508%. That difference reflects **missing-evidence abstention**,
not validated entry/exit skill. There is no executed sell sample or midpoint
fill proof. Whole-share proxy engineering and adjusted-unit research accounts
remain explicitly separate.

## Evidence and decision

**VERIFIED:** actual CLI result is
`/home/animallya96/scratch/specialist-runtime-20261001/funded-study.json`,
SHA256 `15ff07ee1a354e10234b89e99a5c59b307561d9e2741668fe1f06f10aa6e1960`.
Independent review matched all fourteen implementation file hashes to the
clean `12f14e39` tree and all thirteen input-file hashes to frozen bytes.
The artifact contains every account path, fees, turnover, risk, scenario counts,
benchmark differences, forecast labels, timing receipts and runtime versions.
Model/runtime identities are documented in the separate
[joint](specialist-forecast-runtime-2026-10-01.md),
[risk](specialist-risk-contract-2026-10-01.md) and
[timing](specialist-timing-runtime-2026-10-01.md) reports.

**FAILED boundary, corrected:** the first CLI attempt stopped before writing
any result because optional CVXPY was importable but had no distribution
metadata. Provenance now records the actual imported module versions. The
original inference and all policy parameters were preserved; no tuning or new
model sampling occurred during this correction.

**UNVERIFIED:** profitable specialist edges, other-market regimes, genuinely
untouched out-of-sample performance, pretrained training cutoffs, original
historical tradability, full live parity and real fills. None qualifies for
live adoption. Keep the incumbent. TTM's potential risk role needs prospective
funded evidence; a wider, genuinely dated eligible universe is required before
the joint or timing contributions can claim an economic edge.

KiT remains unavailable for native implementation: rechecked official
[repository](https://github.com/Luciferbobo/KiT) still contains only README,
assets and license, and says code is forthcoming. No substitute is labelled
KiT. Chroma contributes a causal specialist-selection principle, not a
reproduction of its pretrained model. TimesFM outputs remain research-only.

Diagram impact: NONE — optional research adapters use the existing isolated
market research/account/artifact boundaries. No live ownership, service, API
or UI flow changed. All 33 diagrams and the published page are synchronized.
