# What the desk's analysts actually measure

## September 25 correction: intraday confirmation and expired provenance

The original tooltip incorrectly said intraday price-sensitive votes could
bypass the three-session wait. Current technical/plain-value readers call
`Opinion.stances()` and apply the same persistence rule with today's live bar.
The holdings reader honors those computed stances. Its legacy fallback for
snapshots without a stance still uses bare thresholds, so the replacement text
is deliberately scoped to **computed intraday votes**, not every old snapshot.

Opportunity components now say `intraday reading`, not `current bar`: that
field denotes provenance and survives expiry. The score's original bar time,
last-reading state, prior-close context and nightly valuation label are retained.
No score, grade, eligibility, persistence rule or stored record changed.

VERIFIED on the shared checkout: both original wording failures reproduced;
22 final browser cases pass with zero skips/flaky results and zero browser
diagnostics, including fresh-to-expired transition and mobile/detail surfaces.
TypeScript and production build pass with existing CSS/chunk warnings. Root
also inspected the complete expired-card screenshot. One immediate candidate
run failed strict request diagnostics during a Vite edit-triggered reload;
the quiescent exact source passed without weakening assertions.
Evidence: `/private/tmp/anios-intraday-wording.updDSi/RECEIPT.md`, SHA256
`8f51c17396169a91571fffc47254d00eaf347e690643b753b5435d76f1cdf91a`.
Deployed UI remains UNVERIFIED; no deployment or provider/model request.
Diagram impact: NONE — wording only, unchanged data and ownership flows.

## Objective and acceptance boundary

Make the existing analyst labels, evidence dates and explanations match the
implemented score without changing scores, votes, grades, policy, account state
or saved history. A combined A+ must not be presented as intrinsic fair value,
an individual analyst's letter grade, a profit probability or a current Buy.
Both stock details surfaces and the opportunity breakdown must use the same
meanings. Missing evidence, missing/invalid values and unknown provenance must
remain explicit. The browser acceptance path includes desktop and 390px mobile.

Started clean on `main` at `f1e717a9d5abdcb370c35856970a365e7c26a349`;
`git pull --rebase origin main` was current. Backend explanations and frontend
presentation were assigned separately. Only these coordinated task changes
were present on resumption. No model prompt, fit, historical study, execution
policy, holding, order, deployment, permission or persisted record is changed.
The frontend type exposes existing record metadata, not a new backend API.
Diagram impact: NONE — unchanged data flow.

## Meaning, not a valuation verdict

| Display | Implemented meaning | Does not establish |
| --- | --- | --- |
| F: Growth & margins | Relative ranks of revenue YoY/QoQ growth, gross margin and revenue acceleration; at least two finite legs | Complete financial quality, balance-sheet safety or fair value |
| S: Earnings-release tone | Guidance, demand, guidance-change and pricing tone from the release reader | Current investor/news sentiment or a fair-value estimate |
| V: Relative valuation | Group-relative P/S, optionally blended with a ranked growth-gap input | Intrinsic fair value, analyst consensus or a target price |
| Analyst numbers/signs | Rounded cross-sectional percentiles and separate recorded votes | Individual letter grades or probabilities |
| A+/A/B/C | Combined grade from votes and the core-analyst veto | A standalone executable instruction or good entry price |

The growth gap subtracts a relative-P/S valuation proxy from model-estimated
revenue growth. The proxy annualizes quarterly revenue by multiplying by four;
it is not trailing-twelve-month revenue or a measured market growth expectation.
Price/book is descriptive Value context, not an active score leg. Market cap
still affects Value's peer grouping even though it is omitted from prose.

A strong growth or upbeat-release reading can coexist with a high valuation.
This work does not verify any website's AAOI overvaluation percentage, identify
the cause of a price decline, or recommend buying a dip. The original AAOI
question exposed a mismatch between the display's broad labels and the narrower
implemented measures; relabeling does not qualify the strategy economically.

The [August 6, 2026 AAOI earnings release filed with the SEC](https://www.sec.gov/Archives/edgar/data/1158114/000168316826006055/aaoi_ex9901.htm)
illustrates the distinction, without proving which facts established a saved
vote. For Q2 ended June 30, revenue was $191.922m versus $102.952m a year earlier
and $151.144m in Q1: **+86.42% YoY / +26.98% QoQ**. GAAP gross margin was
**27.7%**, versus **30.3%** a year earlier; GAAP net loss was **$22.8m**, versus
**$9.1m**. These are comparable three-month GAAP measures, not evidence of fair
value. The [Q2 Form 10-Q](https://www.sec.gov/Archives/edgar/data/1158114/000143774926026278/aaoi20260630_10q.htm)
reports first-half operating cash outflow as a separate six-month measure:
$73.781m versus $116.389m a year earlier, an improvement despite remaining
negative. Strong revenue growth and upbeat management guidance can coexist with
losses and cash consumption. This is not an assessment of a current executable
price or confirmation of a website's overvaluation percentage.

## Targeted corrections

- Shared labels cover stock details, the guide, opportunity contributions and
  recorded vote changes. Percentiles and votes have distinct explanations;
  absent/invalid numbers or signs do not become neutral readings.
- Fiscal period ends come only from the `fundamental` metadata saved with the
  evening record, per metric. They are not filing/release timestamps and can
  differ across metrics. Invalid calendar dates remain unavailable.
- A visible warning says no source-release link is recorded for the S vote.
  The separately fetched earnings read cannot establish which release supplied
  that recorded vote. Dates are not borrowed from it.
- Evening votes use three-session confirmation. Computed intraday votes apply
  the same rule with the live bar as today's session; they do not count each
  candle as another day. Today's readings may differ from those that established
  a persisted vote, so the explanation is not causal attribution. The original
  September 24 wording incorrectly claimed an intraday bypass; corrected above.
- A recorded vote change no longer claims price independence when Value moved.
  A grade change with no recorded vote difference no longer invents a continuous
  score threshold as its cause. Reaction-date markers are not publication or
  re-read timestamps.
- Backend F/S/Value descriptions prefer score-related readings before the
  correlation-based selection heuristic. Fallback and full context say
  `not scored by this analyst`, since another component can use the reading.
  Missing peer distributions cannot produce high/low-in-book claims.
- The active gap has a precise proxy label and is included in Value's evidence
  selection. The corrected operating-cash-flow/revenue field has an English
  name. Technical explanation selection/formatting is unchanged.
- Original recorded headlines, reasons and model commentary stay unchanged in
  the dated archive. No historical record is regenerated to apply new wording.

## Backend verification and preserved failures

Local evidence: `/private/tmp/anios-analyst-meaning.7EGfTl/`, with exact commands,
image identity, source hashes, failed JUnit files and `BACKEND_ACCEPTANCE.md`.
The initial regression was **11 failed / 1 passed**; the expanded pre-edit
regression was **18 failed / 2 passed**. These failures reproduce the missing
gap, unlabelled context, context displacing scored evidence, misleading gap
meaning, missing cash-flow name and unsupported peer placement.

VERIFIED corrected regression: **136 passed, 22 existing warnings, 2.07s**,
including 20 new cases. Rendering preserves evidence, ranks, scores, stances,
votes and grades, including raw-rank reversal against a still-held vote and
missing-gap fallback. Ruff, Black and diff checks pass. The warnings are existing
synthetic all-NaN/empty-slice cases, not suppressed by this change.

Production SHA256:
`5892bf378263190bc8bfe452a50ed8f1ce12b7987dc1bfd39a4e671ff6844f6b`.
New test SHA256:
`639ba0030c963e386dc8996a955e14c953e22f94b0af68219dd1e3256a8d8495`.
Network-disabled image:
`sha256:63056fccae989b0ef65bb198bc913da58c87648169a50c1e2422b9b3c267d8ca`.

Independent final-source proof: **15/15 edge assertions** and **810/810
technical-equivalence assertions** against the baseline implementation.
`/private/tmp/anios-explanation-review.gve8arKC/` retains the driver, both source
copies, result and manifest; all four payload files / 436,172 bytes match on
readback. Result SHA256:
`4a7ce6b38997fd765eb73605597ed00c5a975a2c005117acf736b451b52d0c28`;
manifest SHA256:
`6ff36121c5b9a540bf78c5d085882d4ab2cd19e5070497bbec1bdce792e1d8ad`.

## Browser verification and preserved failures

Local evidence: `/private/tmp/anios-analyst-semantics.TaBMw4/`. The original
new browser regression fails as intended (**1 failed / 8 not run**). Independent
review then identifies and reproduces three additional edges (**3 failed**):
invalid analyst parts, a Value-only vote flip incorrectly claiming price was not
an input, and unchanged votes incorrectly claiming a continuous-score threshold.
The final full-evidence invalid-vote label is also reproduced (**1 failed**)
before its correction. All failed-run diagnostics have empty browser/error/write
arrays. Failed attempts and their source identities remain retained.

VERIFIED intermediate full matrix `full-04`: **127/127 in 88.870s**, with no
skips/flaky/unexpected tests; all 21 timing/meaning diagnostic records have zero
console errors, page exceptions, failed requests, HTTP errors, unexpected
requests or forbidden writes. The final fallback label and coherent synthetic
live-rank fixture then pass **12/12 in 9.039s** (`focused-final`), with all 12
diagnostic records empty. TypeScript/build passed before that final small change;
the exact committed-tree matrix/build repeat is recorded separately.

The suite exercises missing, invalid and mixed fiscal dates; separates later
earnings data from the saved vote; preserves archived text; checks both details
surfaces with/without a personal row; and checks mobile overflow and visibility.
Root reviewed the mobile evidence-date screenshot. The broader 106 existing
Desk cases and nine prior timing cases remain in the full matrix. API traffic is
intercepted; the new cases forbid writes except the explicitly non-recording
preview POST. This proves isolated UI behavior, not live persistence or a current
AAOI quote. Existing CSS/chunk build warnings remain.

Final precommit receipt `ACCEPTANCE.md` SHA256:
`9901fa75de70ddcf70d84aa29927485305e85362a6ae8ad181e6f2f28fd70851`.


## Exact-commit acceptance and publication

VERIFIED implementation checkpoint:
`f361d6389490d152fab56484af4f17e448d73a33`, tree
`1be23a8527ece80c368a63aaebd65d2541e85085`. The exact clean committed source
repeated **127/127 browser tests in 88.424284s**, no failures/skips/flaky results;
all 21 six-field browser diagnostic records are empty. TypeScript and production
build pass (3,638 modules, Vite build 1.22s), with the existing warnings.
All eight monitored frontend hashes agree before/after. Root and implementing
agent inspected the exact desktop/mobile screenshots. A fresh isolated Vite
runtime exercised the real checkout, not the deployment clone; the built bundle
is not deployed. The image remains the pinned Playwright 1.63.0 image.

Separate exact-commit backend acceptance repeats **136/136 in 2.03s**, with
22 existing fixture warnings; scoped Ruff/Black and diff checks pass. HEAD, tree,
clean state and both source hashes agree before/after. Network remained disabled.

Receipt roots and SHA256:

- `/private/tmp/anios-analyst-commit.pdhR2L/ACCEPTANCE.md`:
  `5d2569a1b38b3eff983b99b42102dc71a6d439f20d1f0a32e0d0cd71934a45ea`.
- `/private/tmp/anios-analyst-committed.1NKN7v/ACCEPTANCE.md`:
  `466347b15f540df4ac4d486cf8ad765cc09aa8dbcbb02c578d78dc12c944cc02`.

Published to `spark main`, then to GitHub **from Spark**, with divergence 0/0.
No deployment, model fit, trading/account write or completed-study rerun.

VERIFIED fresh evidence retention at
`/home/animallya96/anios/data/market/research/analyst-semantics-20260924.wowffj_5/`:
**788 payload files / 44,337,810 bytes**, zero missing, changed, unexpected or
transferred symlink files. Original and exact-commit evidence are separate roots.
Initial local preparation refused 63 pytest `*current` symlink aliases without
following them or contacting Spark. Each exact alias was then explicitly
approved for exclusion only after its mapped non-symlink directory and complete
regular-file subtree were verified retained (57 files). The mappings and proof
are embedded in the request, plan and receipt; no unique evidence was omitted.
The transport's offline guards pass **19/19**. Earlier UI evidence (44 + 369
files) and all local source artifacts remain unchanged.

Readback receipt `retention/retention-readback.json` SHA256:
`700487f831d896218f28b10a622ddd247aa3af4e3c49abde623cc3df546e1e4c`.
Local driver, failed preparation evidence, frozen plan and receipts:
`/private/tmp/anios-analyst-retention.mOZHUm/`.

## Historical-input defect reproduced independently

This separate read-only investigation does not change the learner. At baseline
`f1e717a9`, the actual `desk.run → challenger.expectations_gap →
_universe_panel/build_panel → _records` path fails to propagate the historical
`asof`. With the requested date held at 2024-06-28, appending a synthetic
2025-01-02 partition leaves the book unchanged but changes the gap's loaded
historical close from **11 to 91**. All four gap reads receive `asof=None`,
and a later-filed fact enters the records. Explicitly pinned production readers
retain the old data, isolating caller cutoff propagation as the failing boundary.

VERIFIED reproduction: **17/17 assertions pass**; both required fixed-asof
historical-input invariants **FAIL**. Actual `MarketStore` reads are exercised;
ordinary analysts are stubbed and execution stops at `_features`, before any
fit. Calls to `_block`, `_dataset`, `_carried`, `_fit_predict`: **zero**.
This proves loaded-input drift, not changed predictions, affected real securities,
AAOI causation or inflated returns. No completed study was rerun or retuned.

Evidence: `/private/tmp/anios-asof-boundary.rm8CgF/`; **21 payload files /
182,315 bytes**, 12 boundary identities, all verified by readback. It retains
the driver, copied source, synthetic Parquet partitions, results and manifest.
Result SHA256:
`73565641cb4771d43d3dc07b88615a231c1ab00a134fcdd733e0ee492f5400cd`;
manifest SHA256:
`ac112eb7b49658b7ddc1228bd76c85e430f347ad746f8bccd1b7e7dfff7b6aea`.

## Remaining limits and next atomic work

The normal S record still lacks immutable release provenance; this patch
discloses the absence, it does not repair that lineage. F dates identify reference
periods for recorded evidence, not the information-publication time or necessarily
the readings that established an earlier vote. The legacy technical explanatory
registry still lists support distance where falling-regime scoring uses band
position; it requires a separate tested correction.

Historical cutoff propagation, label-publication eligibility, future calendar/
global cohort dependence, release timing, mutable tag/tone history, legacy
zero-fill bypass and current membership/sectors still block qualification of
the large reconstructed returns. Preserve the completed rejected allocation
study; fix input causality with bounded noninterference fixtures, not retuning.
Primary financial-source accuracy, real-model tone quality, deployed UI and
writable-account persistence remain UNVERIFIED by these isolated tests.
