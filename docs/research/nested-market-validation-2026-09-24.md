# Nested market study — implementation evidence, September 24, 2026

This records implementation and saved-evidence verification, not qualification
of a new strategy. The separate
[frozen protocol](nested-market-study-2026-09-24.md) was declared before market
outcomes and retains SHA256
`11898d28ad41c8e625a54a56f604b7daac508a91bc85dc6ba1a3ac4cfffec483`.

## Implementation acceptance

VERIFIED: **1,033 tests passed**, **1 deliberately deselected** completed-study
reproduction, **5 existing empty-slice warnings**, **24.86 seconds**. New source,
input and study suites contribute **126**, **186** and **47** cases respectively.
Scoped Ruff lint/format and `git diff --check` pass. No deployed-system gate or
model-serving test was needed for this offline, no-prompt change; full deployment
gates and deployed behavior remain UNVERIFIED. No deployment occurred.

Actual source-to-feature synthetic acceptance constructs all22 features, fits
real regressions, executes six matched accounts at10/25bp, retains the archive
and runs20 actual standalone journal-verifier subprocesses. A separate
independently supplied-input fixture runs20 more. It checks exact `/3` parity,
funded controls, real fold boundaries, cumulative-notional attribution,
future-prefix non-interference, raw-label retention and complete archive readback.
Synthetic results do not establish investment performance.

Three final-review gaps were reproduced and corrected before outcomes:

- Report grades could change after assembly, leaving candidate basket gross .15
  while the changed incumbent targeted0. Binding now covers consumed report
  arrays, regime exposure/tightening, sides, themes, configuration and assembly
  source; changes during assembly or before/after the run are rejected.
- The FOMC CSV and NYSE holiday JSON used by the unchanged event policy were not
  in source evidence. Both are now hashed/copied, and process-local cached holiday
  interpretation is refreshed before constructing the event path.
- Valid journals did not alone prevent altered summaries, curves or labels from
  being archived. A complete evidence digest now binds those values, actual arrays,
  fits/predictions/proofs and actual journal contents, with pre/post-archive checks.

The local runtime is Python3.12.14, NumPy2.5.3, pandas3.0.6, PyArrow25.0.0 and
exchange-calendars4.13.2, on the exact checkout mounted at `/app` in image
`sha256:63056fccae989b0ef65bb198bc913da58c87648169a50c1e2422b9b3c267d8ca`.
Optional research dependencies were installed in a disposable `/deps` directory,
not into a live service. Full final JUnit and retained synthetic archives:
`/private/tmp/anios-nested-market-acceptance.teTufe/acceptance-02.xml` and
`pytest-02/`. The earlier979-test proof remains in `acceptance-01.xml`/`pytest-01/`.

Exercised source SHA256:

- Inputs: `b126f2886adae265f9b4d7eb07694478d3e0035f5666ca001b7bed52bfcf547e`.
- Sources: `a2f9fab54d53f8e45e61e9edb850619cef11576c8e464411a28829a4e803e320`.
- Study: `9d0a602bd6d1cbbcc512c5b00a1b193504f6cacacfb5569545eb4d2899be89d7`.
- CLI: `1fd03c2505e6b198b9fdaa2b7a65187924701cb3104202495e470622d1a6b014`.

## Real source acceptance, without fitting

VERIFIED: pinned report and source manifest, **191/191** source file hashes,
**570/570** exact report/source field comparisons including NaNs, and all
**2,945 XNYS sessions**. Original report remains95 columns; execution panel96.
Assembly produces2,939 raw labels per target and2,739 after the fixed200-row
training warmup. First outer session is2020-01-06. No all-name intersection,
future-availability filtering or history interpolation is used.

The full loader proof is `source-loader-proof.json` in the same evidence folder,
SHA256 `6de5cd2501506361545b67f7c94e0936c3f64b087cd0a73b1c4fff0734b64515`.
All96 fetch timestamps follow the final exchange close, September18 20:00UTC.
**FAILED vendor OHLC consistency:** terminal Q open118.080001831 is below
low118.150001526, and TYL open340.859985352 is above high340.640014648.
These values are preserved and explicitly flagged, not repaired or claimed
harmless: terminal opens can affect fills and labels. Their hashes match the
frozen vintage. Historical membership, precomputed report causality, then-known
adjustments and complete financial-quality features remain UNVERIFIED.

## Documentation browser acceptance

Diagram impact: UPDATED — market-data. All32 source/render/page checks pass;
31 unrelated SVGs remain byte-identical. Browser acceptance covers19 labels,
7 changed-node bounds, SVG/source navigation and100/125/300% zoom/reset, with
zero page exceptions, console errors or failed requests. Root inspected the
focused research branch. Evidence:
`/private/tmp/anios-market-study-diagram.i2IPJH/`.

## Original acceptance path (superseded; do not rerun saved market outcomes)

The pre-run plan was to run the frozen CLI once on the pinned historical inputs,
retaining command, stdout/stderr and exit status even on failure, then verify every saved
account and archive hash before interpreting full, rolling, actual-fold and
causal-regime scorecards. The implementation checkpoint itself asserted no market
outcome. Subsequent failed attempts and independently recovered results are
recorded below; this original plan is not authorization to refit those outcomes.
No result can automatically promote the strategy.

## First historical attempt: failed accounting acceptance, no performance result

Implementation checkpoint `22eb5c8b0d239700a76bdd98d48d14cf120bbb0f` was
published to Spark and then GitHub from Spark. The exact committed code repeated
**1,033 passed,1 deselected,5 existing warnings in23.41s**. Its first frozen
historical CLI attempt ran8.13s and exited2 at an independent common-buy-scale
check. `market-run-01/` preserves command, source revision, script, stdout,
stderr and status. No completed historical result was produced or retuned.

A passive observer captured the unchanged failing account under
`account-failure-01/`, snapshot SHA256
`3035f4b3f468bc3e688c13528c890cb02e3188b4502d2e82aa4fcb8b23d518df`.
At event293,2019-01-24, an independently carried cash difference3.0986e-16
was amplified by a1.5342e-7 request into a2.0197e-9 scale difference. The
original verifier compared total requested money with its negligible-money
threshold and refused the account, even though the discrepancy's monetary
effect was3.10e-16. No different funding behavior was found.

An independent80-digit Decimal reconstruction covers all798 saved events:
maximum cash difference6.69e-16, units7.83e-18 and NAV8.32e-16. The valid
proof is `decimal-reconstruction-proof-02.json`; the first observer draft had
an initialization typo, is explicitly disclaimed in `DECIMAL-PROOF-NOTE.md`,
and remains preserved rather than counted as proof.

The targeted verifier correction checks the recorded funding formula and both
monetary discrepancy calculations under the existing NAV-relative bound. It
does not change producer trades, account carry or global tolerances. The
unchanged captured journal now passes379 marks through the actual standalone
CLI: `corrected-verifier-cli.json` and `corrected-verifier-receipt.json`.
Maximum replay residuals: cash1.28e-15, units1.70e-17, NAV1.55e-15. No market
refit was needed for that accounting proof. Complete historical study performance
remains unverified until a subsequent frozen attempt succeeds.

Correction acceptance: **1,063 passed,1 deliberately deselected,5 existing
warnings in26.90s**, including30 new scale cases and the entire previous study
acceptance. Scoped lint/format pass. Source SHA256
`319461ccb83585f76e4c6910d10fbad787717a6998a5fcbe22bdf44eff69cc21`;
new test SHA256
`5da367a8f61fe5a703f8151a755def3c3b9b90eadcce858d41d8f7b753fa38e8`.
Proof `acceptance-scale-02.xml`/`pytest-scale-02/`. Diagram impact: NONE — this
correction is internal numerical validation, with the same account/data flows.

## Second historical attempt: archive out of memory, saved journals verified

The frozen retry used clean checkpoint
`e749c0af98aa104a04d0b12992e427265f7469e2`, unchanged protocol and the same
single-threaded local research runtime. It ran from 19:05:28.508630 to
19:14:46.168824 UTC on September 24 (557.66 seconds). **FAILED:** child exit
`-9`, wrapper exit 247, confirmed Docker `oom` event for container `89a5985692dc`
at Unix nanoseconds `1790277286133718470`. Last observed memory was 7.127 GiB
against the 7.652-GiB Docker limit. The exact Python statement at termination
is UNVERIFIED; no model setting, strategy rule or source price was altered.

All 124 journal directories and verification files, copied code/protocol,
`evidence.json` (about 1 GiB), `summary.json`, `source-hashes.json` and
`arrays.npz` were present. The original root `manifest.json` is absent. The
attempt is preserved as failed, not relabeled as a completed CLI, and no
replacement producer manifest has been created.

A separate observer inventories the retained files and invokes the existing
standalone journal CLI on each ledger. **VERIFIED: 634 files / 1,688,236,289
bytes; 124/124 accounting checks; 62,668 closing marks.** All CLI proofs equal
their saved counterparts, and file hashes match before/after. This does not
reconstruct the original final whole-evidence digest. No producer or fit was
rerun. Independent model/selection and metric recovery passed as recorded below.

Evidence is under `market-run-02/` in the acceptance directory above:

- `completion.json`, `oom-observation.json`: the failed process and Docker event.
- `interrupted-files-inventory.json`: observer inventory, SHA256
  `cc25cd0fa6c304aac227ab4c16a92f4058b00b6c6c1796a064975271eff40204`.
- `interrupted-journal-proof.json`: independent accounting, SHA256
  `5e3fbb34472714e8d8f0aef243600fbc503bcaba6c94b69c648444ffa372163e`.

The observer receipts are outside `study/`; its saved bytes are unchanged.
Historical source availability, financial quality, membership completeness,
vendor correctness, strategy adoption and deployed behavior remain UNVERIFIED.

## Recovered model and metric evidence

The standalone streaming observer parses the saved JSON to EOF and checks all
**874 arrays**, all **191** source files, **288** direct price comparisons and
independently reconstructed endpoint labels. It verifies **14** outer folds,
**112** inner accounts, **12** outer accounts, **46** unique fit receipts /
**138** target fits, **234,186** training-row checks across those fits and
**68,556** forecast values (these counts reuse dates across targets and folds).
Training cutoffs, feature/label availability, train-only transformations,
normal equations, candidate ordering, worst-cost selection and carried-fold
trading all pass. Maximum forecast difference is **0**; maximum relative
normal-equation residual is **1.2574e-14**. These are declared data-availability
checks, not authentication of historical vendor vintages.

This observer ran for **70.49 seconds**, peak RSS **812,988 KiB** (about
794 MiB), under a 3-GiB container cap. It uses separately installed, pinned
`ijson==3.4.0`; no runtime service or repository dependency was changed. Its
synthetic equivalence and prior 11-corruption semantic self-test pass. The
original file inventory matches the accounting observer's independently
recorded inventory exactly. The original advertised whole-evidence digest
remains **UNVERIFIED**, and the producer's completion remains **FAILED**.

A separate arithmetic checker, importing no strategy or metric producer,
passes **728/728 comparisons** and **8 synthetic self-checks** across full
metrics, primary objective, rolling windows and causal-regime attribution.
Maximum numerical difference is **3.55e-15**; rolling counts/wins/ties and
regime chronology/counts agree exactly. All 12 outer proofs are bound to the
standalone account replay. It does not certify predictive edge or adoption.

External evidence, relative to the acceptance root:

- `RECOVERY-VERIFICATION-01.md`: exact command, image, parser hashes and limits.
- `recovery-study-verifier.py`: SHA256
  `229b3d649e67fd390ae76dd8254ad184f2450953e9ed57a8ed3a8c18fe20c1fa`.
- `recovery-market-proof-01.json`: SHA256
  `ec3d4ac37fa59c290f25b1d291935831bbf0a243683507f8998c0888963a2bf1`.
- `independent-metric-math/proof-01.json`: SHA256
  `2b9d716b4f257157605789995aec7d539bc07829337cc362f165774b007fca6b`.
- Original `market-run-02/study/summary.json`: SHA256
  `fc2e01e0999017ece889926ffa67ecd2088ba5114a44691576c59090a0a228de`.

## Recovered exploratory result: reject this gate

**The candidate fails the frozen wealth hurdle at both costs.** It beats SPY
and QQQ over this full sample but loses substantially to `/3`, its matched
stock-only adapter and equal weight. Its ending wealth is **48.75% / 52.39%
lower than the same adapter without the gate** at 10/25 bp. Its closing-NAV
drawdown is also worse than that no-gate control. This is evidence against this
particular gate, not against every possible timing model. No parameter is tuned
after this result and no live policy is changed.

Same **1,685 closing marks / 1,684 return intervals**, 2020-01-06 through
2026-09-18, at both costs. Ending wealth is final marked NAV per starting NAV1,
not liquidated proceeds. CAGR uses 252-session years. Maximum drawdown uses
closing marks only. Gross trading is **buys plus sells**, annualized over mean
observed NAV; it is not conventional one-sided turnover.

| One-way cost | Account | Ending wealth | CAGR | Max closing drawdown | Annual gross trading / mean NAV |
| --- | --- | ---: | ---: | ---: | ---: |
| 10 bp | New ridge allocation gate | 4.0584× | 23.32% | −35.47% | 14.71× |
| 10 bp | Matched stock-only adapter | 7.9186× | 36.29% | −32.57% | 8.21× |
| 10 bp | Unchanged `/3` | 22.3868× | 59.23% | −37.33% | 13.65× |
| 10 bp | Funded SPY | 2.5843× | 15.27% | −33.72% | 0.09× |
| 10 bp | Funded QQQ | 3.4719× | 20.47% | −35.12% | 0.08× |
| 10 bp | Equal weight | 11.2780× | 43.70% | −36.98% | 4.04× |
| 25 bp | New ridge allocation gate | 3.4763× | 20.50% | −36.50% | 14.87× |
| 25 bp | Matched stock-only adapter | 7.3015× | 34.65% | −33.59% | 8.23× |
| 25 bp | Unchanged `/3` | 19.8579× | 56.40% | −37.58% | 13.64× |
| 25 bp | Funded SPY | 2.5805× | 15.24% | −33.72% | 0.09× |
| 25 bp | Funded QQQ | 3.4667× | 20.45% | −35.12% | 0.08× |
| 25 bp | Equal weight | 10.8710× | 42.91% | −37.27% | 4.03× |

Candidate versus the no-gate adapter isolates this gate under matched execution.
Candidate versus `/3` is a whole-policy comparison: `/3` has different cadence,
entry/exit and funding rules. All accounts begin in cash, cash yields zero,
costs apply per traded dollar, and there is no terminal liquidation. SPY/QQQ
are funded constant-exposure controls, not uncharged adjusted-price curves.
This is not a tax, actual settlement, market-impact or capacity simulation.

### Chronological consistency

The candidate beats `/3` in **1/14 actual carried folds** at each cost, versus
the no-gate adapter in **4/14** at 10 bp and **3/14** at 25 bp. It beats SPY
in **8/14**, QQQ in **9/14**, and equal weight in **3/14 / 2/14**. Folds are
not independent trials: fits expand over overlapping training history and the
account carries its capital and positions. The final fold has 46 intervals;
the other 13 have 126. No short-fold CAGR is used as an annual result.

Candidate benchmark beat rates below use overlapping compounded-return windows,
not prediction or trade accuracy. Every 63-session column contains **1,622**
windows; every 252-session column **1,433**. Ties stay in the denominator but
are not wins. QQQ has **192** ties at 63 sessions for each cost; all other
candidate comparisons have zero ties.

| Cost | Comparator | 63-session beat rate | 252-session beat rate |
| --- | --- | ---: | ---: |
| 10 bp | `/3` | 19.17% | 0.00% |
| 10 bp | SPY | 55.98% | 59.04% |
| 10 bp | QQQ | 47.16% | 67.27% |
| 25 bp | `/3` | 17.63% | 0.00% |
| 25 bp | SPY | 52.90% | 47.59% |
| 25 bp | QQQ | 43.46% | 59.60% |

### Causal regime attribution

Each interval is labeled from the preceding SPY close: at/above or below its
trailing 200-session mean, and 20-return volatility above or at/below its
trailing 252-observation median. These are prior-condition labels, **not**
green/red-day predictions. Positive returns can occur below the trend mean.

The entries below are candidate-minus-comparator **mean daily excess log
returns in basis points on the selected intervals**, shown as 10 bp / 25 bp
cost results. They do not describe a separately traded switching strategy or
annualized stitched regime returns.

| Prior SPY condition | Intervals / months / episodes | vs `/3` | vs SPY | vs QQQ |
| --- | --- | ---: | ---: | ---: |
| At/above mean, high volatility | 518 / 44 / 37 | −7.03 / −7.48 | −1.97 / −3.16 | −1.54 / −2.72 |
| At/above mean, low volatility | 833 / 59 / 32 | −11.63 / −11.67 | +7.30 / +6.51 | +4.47 / +3.68 |
| Below mean, high volatility | 296 / 23 / 16 | −13.29 / −13.50 | −2.01 / −2.76 | −4.84 / −5.59 |
| Below mean, low volatility | 37 / 5 / 10 | +4.96 / +4.59 | +1.42 / +0.34 | +1.92 / +0.84 |
| Unknown/unavailable | 0 / 0 / 0 | unavailable | unavailable | unavailable |

The gate has negative mean excess log returns against every primary comparator
in both high-volatility buckets; this does not say it lost on every individual
day. Its only bucket positive against all three primary comparators has just
37 intervals over five observed months; it is not a basis for selecting a new
regime-specific rule after seeing this table. Months and episodes are not
independent trials. All 1,684 intervals remain represented.

### Boundaries and next work

The very large reconstructed `/3` and equal-weight returns do **not** establish
reliable live expectations. Historical membership, financial quality,
precomputed report causality and then-known adjustments are not audited; two
terminal vendor price inconsistencies remain. This is examined history, not
an untouched holdout, and the financial feature coverage does not qualify a
quality-stock selector. The new gate itself uses price-only features and gross
five-session return proxies, not calibrated next-day downside probabilities.

Keep `/3` unchanged and this challenger unpromoted. Next engineering work is
bounded archive JSON/file buffering with byte-equivalence and memory checks,
without refitting this result. Next economic evidence work is auditing the
incumbent report's historical availability and sourced quality/membership
coverage; do not search another model grid on these outcomes and call it an
independent test. No deployment, holding change or order is authorized here.

## Retention and publication boundary

Spark archive root:
`/home/animallya96/anios/data/market/research/nested-market-20260924.xEBPm7/`.
Readback verifies **193 original source files / 192,833,769 bytes**, then
**4,199 static acceptance/failed-run/diagram files / 1,786,630,468 bytes** and
**42 supplemental recovery files / 1,065,977 bytes**. All prior 4,392 files
were rehashed before/after the supplement. Retention receipts are outside the
failed study and do not replace its absent completion manifest.

- `static-retention-01/retention-readback.json`: SHA256
  `7dc92deef299c4d27588021b1761b32b72a8640f9d5965096606696c545ba190`.
- `supplemental-retention-01/retention-readback.json`: SHA256
  `fd415384fd5cc57a9e66766555bedd739dacd5c38f8336b0a8c6e09717a75294`.

The original rsync partial is preserved separately under
`transport-evidence-4k18k383/`; stopping only its two confirmed stale transfer
processes let rsync unlink that temporary. No original source file was deleted.
The supplemental copy includes pinned parser source, native libraries and
licenses; 15 volatile bytecode cache files are explicitly excluded.

This result changes documentation only. Code is pushed to `spark main`, then
GitHub from Spark; an authorized live deployment must run on Spark through
`scripts/deploy.sh`. No deployment was performed here.
Diagram impact: NONE — evidence and results documentation, unchanged data flow.
